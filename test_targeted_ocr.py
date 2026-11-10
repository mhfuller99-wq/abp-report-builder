"""Synthetic regressions only. No customer text or images belong in this file."""
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from abp_ocr import Budget, extract_local, hood_candidates, tesseract_region_words, word
from abp_ocr_regions import raster_regions, render_geometry, ruled_regions


def information_words(confidence=99):
    def w(x, y, width, text):
        return word(x, y, x + width, y + 10, text, confidence)
    return [w(0,0,30,'HOOD'),w(40,0,100,'INFORMATION'),w(0,30,25,'TAG'),
            w(110,20,40,'TOTAL'),w(100,35,25,'EXH'),w(130,35,25,'CFM'),
            w(210,20,40,'TOTAL'),w(205,35,50,'SUPPLY'),w(215,50,30,'CFM'),
            w(0,75,40,'HD-1'),w(110,75,40,'2400'),w(210,75,40,'1800'),w(300,75,40,'233')]


def ruled_pdf(rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(pymupdf.Rect(60,150,540,250), color=(0,0,0), width=1)
    page.draw_line((60,190),(540,190), color=(0,0,0), width=1)
    page.draw_line((200,150),(200,250), color=(0,0,0), width=1)
    page.set_rotation(rotation)
    return doc


class HoodInformationTests(unittest.TestCase):
    def candidate(self, words=None, method='ocr'):
        return hood_candidates(information_words() if words is None else words, 'synthetic.pdf', 2, method)[0]

    def test_distinct_fields_no_inference(self):
        c=self.candidate()
        self.assertEqual(c['review_values'], {'exhaust_cfm':2400,'supply_cfm':1800})
        self.assertEqual(c['kind'],'kitchen_hood');self.assertEqual(c['values'],{})
        self.assertFalse(c['include']);self.assertEqual(c['status'],'UNVERIFIED')
        self.assertNotIn('system',c);self.assertNotIn('makeup_air_cfm',c['review_values'])

    def test_low_header_confidence_is_per_field(self):
        words=information_words();words[4]['confidence']=79.49
        c=self.candidate(words)
        self.assertEqual(c['review_values'],{'supply_cfm':1800})
        self.assertEqual(c['field_evidence']['exhaust_cfm']['printed_text'],'2400')
        self.assertEqual(c['field_evidence']['exhaust_cfm']['confidence_min'],79.49)

    def test_low_title_or_tag_withholds_both(self):
        for index in (0,1,9):
            words=information_words();words[index]['confidence']=70
            self.assertEqual(self.candidate(words)['review_values'],{})

    def test_missing_confidence_ocr_withheld_native_allowed(self):
        self.assertEqual(self.candidate(information_words(None))['review_values'],{})
        self.assertEqual(self.candidate(information_words(None),'native')['review_values'],{'exhaust_cfm':2400,'supply_cfm':1800})

    def test_no_title_or_actual_does_not_parse(self):
        self.assertEqual(hood_candidates(information_words()[2:],'x',1,'ocr'),[])
        for text in ('ACTUAL','MEASURED','INITIAL','FINAL'):
            words=information_words()+[word(400,30,440,40,text,99)]
            self.assertEqual(hood_candidates(words,'x',1,'ocr'),[])

    def test_duplicate_and_missing_values_no_guess(self):
        words=information_words()+[word(110,76,150,86,'2900',99)]
        self.assertNotIn('exhaust_cfm',self.candidate(words)['review_values'])
        words=[w for w in information_words() if w['text']!='1800']
        self.assertNotIn('supply_cfm',self.candidate(words)['review_values'])

    def test_unknown_units_and_oversized_values(self):
        words=information_words();words[8]['text']='L/S'
        self.assertNotIn('supply_cfm',self.candidate(words)['review_values'])
        words=information_words();words[10]['text']='2000000'
        self.assertNotIn('exhaust_cfm',self.candidate(words)['review_values'])

    def test_duplicate_header_no_silent_choice(self):
        words=information_words()+[word(110,21,150,31,'TOTAL',99)]
        self.assertNotIn('exhaust_cfm',self.candidate(words)['review_values'])

    def test_values_above_header_not_read(self):
        words=information_words()
        for w in words[9:]:w['box'][1]-=60;w['box'][3]-=60
        self.assertEqual(self.candidate(words)['review_values'],{})

    def test_pathological_headers_are_bounded(self):
        from abp_ocr_regions import information_parser_limited
        words=information_words()+[word(110,20,150,30,'TOTAL',99) for _ in range(1000)]
        self.assertTrue(information_parser_limited(words))
        self.assertEqual(hood_candidates(words,'x',1,'ocr'),[])


class SelectorTests(unittest.TestCase):
    def test_table_deduplicated_and_rotated(self):
        for rotation in (0,180):
            with ruled_pdf(rotation) as doc:
                boxes,pixels,truncated=ruled_regions(doc[0])
                self.assertEqual(len(boxes),1);self.assertFalse(truncated)
                self.assertLessEqual(pixels,6_000_000)
                self.assertLess(boxes[0][1],150 if rotation==0 else 550)

    def test_blank_not_invented(self):
        with pymupdf.open() as doc:
            doc.new_page();self.assertEqual(ruled_regions(doc[0])[0],[])

    def test_expired_preview_reported(self):
        with ruled_pdf() as doc:
            self.assertTrue(ruled_regions(doc[0],deadline=0)[2])

    def test_tiny_render_budget_fails(self):
        with self.assertRaises(ValueError):render_geometry(pymupdf.Rect(0,0,600,800),1,1)

    def test_fractional_origin_exact_mapping(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            clip=pymupdf.Rect(60.17,150.29,540.39,250.61)
            zoom,_=render_geometry(clip,1_000_000,2.5)
            expected=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
            ox,oy=expected.x,expected.y;expected=None
            def recognize(args,**kwargs):
                output=Path(args[args.index('tesseract')+2]+'.tsv')
                output.write_text('level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\t20\t30\t40\t99\tTEST\n')
                return subprocess.CompletedProcess(args,0)
            with patch('abp_ocr.subprocess.run',side_effect=recognize):
                found=tesseract_region_words(page,1_000_000,5,clip=clip,max_zoom=2.5)
            self.assertEqual(found[0]['box'],[(ox+10)/zoom,(oy+20)/zoom,(ox+40)/zoom,(oy+60)/zoom])
            self.assertNotAlmostEqual(found[0]['box'][0],clip.x0+10/zoom)

    def test_logo_heuristic_and_overflow(self):
        class Page:
            rect=pymupdf.Rect(0,0,612,792);rotation_matrix=pymupdf.Matrix(1,1)
            def get_image_info(self):return [{'bbox':(27,27,173,63)},{'bbox':(30,160,580,650)}]
        regions,truncated=raster_regions(Page(),100)
        self.assertFalse(truncated);self.assertEqual(regions[0]['status'],'small_marginal_image_skipped')
        self.assertEqual(regions[1]['status'],'raster_unexamined')
        self.assertEqual(raster_regions(Page(),10)[0][0]['status'],'raster_unexamined')
        self.assertTrue(raster_regions(Page(),100,limit=1)[1])

    def test_total_preview_and_region_pixel_budgets(self):
        with ruled_pdf() as doc:
            result=extract_local(doc.tobytes(),budget=Budget(max_total_pixels=10),retain_words=False)
            self.assertEqual(result['coverage'][0]['status'],'budget_skipped')
            self.assertEqual(result['ocr_attempted_pages'],0)

    def test_selected_crop_stays_partial_and_has_no_words(self):
        with ruled_pdf() as doc:
            result=extract_local(doc.tobytes(),region_engine=lambda *a,**k:information_words(),retain_words=False)
            self.assertEqual(result['review_candidates'][0]['tag'],'HD-1')
            self.assertEqual(result['coverage'][0]['status'],'partial_review_required')
            self.assertIn('outside',result['coverage'][0]['unexamined_content'])
            self.assertFalse(result['complete_takeoff'])
            self.assertTrue(all('words' not in key for key in result['coverage'][0]))

    def test_psm6_fallback_and_region_cap_explicit(self):
        calls=[]
        def engine(*a,**kw):calls.append(kw['psm']);return []
        with ruled_pdf() as doc:
            result=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            self.assertEqual(calls,[11,6])
            calls.clear()
            result=extract_local(doc.tobytes(),region_engine=engine,budget=Budget(max_regions=1),retain_words=False)
            self.assertEqual(calls,[11])
            self.assertEqual(result['coverage'][0]['regions'][-1]['status'],'budget_skipped')
            self.assertTrue(any('region OCR budget' in w for w in result['warnings']))

    def test_large_unruled_page_retains_full_page_fallback(self):
        with pymupdf.open() as doc:
            doc.new_page(width=2592,height=1728)
            calls=[]
            result=extract_local(doc.tobytes(),engine=lambda *a:calls.append(a[1]) or [],
                                 selector=lambda *a,**kw:([],4_500_000,False),retain_words=False)
            self.assertEqual(len(calls),1)
            self.assertEqual(result['ocr_attempted_pages'],1)
            self.assertLessEqual(result['pixels_processed'],Budget().max_page_pixels)

    def test_coverage_region_cap_warning(self):
        with ruled_pdf() as doc:
            result=extract_local(doc.tobytes(),region_engine=lambda *a,**k:[],budget=Budget(max_coverage_regions=1),retain_words=False)
            self.assertEqual(len(result['coverage'][0]['regions']),1)
            self.assertGreater(result['coverage'][0]['regions_omitted'],0)
            self.assertTrue(any('Coverage region limit' in w for w in result['warnings']))

    def test_unrecognized_tables_do_not_invent_diffusers(self):
        with ruled_pdf() as doc:
            words=[word(0,0,150,10,'MECHANICAL PLAN',99),word(100,100,120,108,'SA',99),word(100,110,120,118,'125',99)]
            result=extract_local(doc.tobytes(),region_engine=lambda *a,**kw:words)
            self.assertEqual(result['review_candidates'],[])


if __name__=='__main__':unittest.main()
