import subprocess
import time
import unittest
import pymupdf
from abp_ocr import Budget, extract_local as extract, hood_candidates, word


def table_words(confidence=None):
    def w(x, y, text, width):
        return word(x, y, x+width, y+12, text, confidence)
    return [w(40,40,'KITCHEN',55),w(100,40,'HOOD',40),w(145,40,'SCHEDULE',80),
            w(40,70,'TAG',30),w(160,70,'EXHAUST',65),w(230,70,'CFM',30),
            w(320,70,'MAKEUP',60),w(385,70,'CFM',30),
            w(40,100,'KH-1',35),w(195,100,'2400',30),w(352,100,'1800',30)]


def pdf(image=True,mixed=False,pages=1):
    d=pymupdf.open()
    for _ in range(pages):
        p=d.new_page(width=500,height=220)
        if image:
            temp=pymupdf.open(); t=temp.new_page(width=500,height=180)
            for w in table_words():
                t.insert_text((w['box'][0],w['box'][1]+12),w['text'],fontsize=12)
            pix=t.get_pixmap(matrix=pymupdf.Matrix(3,3));
            p.insert_image(pymupdf.Rect(0,0,500,180),stream=pix.tobytes('png'))
            temp.close()
        else:
            for w in table_words():
                p.insert_text((w['box'][0],w['box'][1]+12),w['text'],fontsize=12)
        if mixed:
            p.insert_text((20,205),'Native project title and notes with more than forty readable characters',fontsize=9)
    data=d.tobytes(); d.close(); return data


class Tests(unittest.TestCase):
    def candidate(self,words=None):
        return hood_candidates(table_words() if words is None else words,'test',1,'native')[0]
    def test_separate_design_flows(self):
        c=self.candidate(); self.assertEqual(c['review_values'],{'exhaust_cfm':2400,'makeup_air_cfm':1800})
        self.assertEqual(c['values'],{}); self.assertFalse(c['include']); self.assertEqual(c['status'],'UNVERIFIED')
    def test_no_title_no_hood(self):
        self.assertEqual(hood_candidates(table_words()[3:],'test',1,'native'),[])
    def test_ambiguous_no_inference(self):
        words=table_words(); words[-1]['text']='O800'
        self.assertNotIn('makeup_air_cfm',self.candidate(words)['review_values'])
    def test_overrange_flow_blank(self):
        words=table_words();words[-2]['text']='2400000'
        self.assertNotIn('exhaust_cfm',self.candidate(words)['review_values'])
    def test_diffuser_evidence_location_and_confidence(self):
        from abp_ocr import diffuser_candidates
        words=[word(10,10,160,20,'MECHANICAL PLAN',99),word(100,100,120,108,'SA',99),word(100,110,120,118,'125',99)]
        result=diffuser_candidates(words,'synthetic',1)
        self.assertEqual(result[0]['review_values'],{'design_cfm':125})
        self.assertEqual(result[0]['position'],[100,100])
        self.assertFalse(result[0]['include'])
        words[-1]['confidence']=50
        self.assertEqual(diffuser_candidates(words,'synthetic',1)[0]['review_values'],{})
    def test_queue_overflow_preserves_native(self):
        from unittest.mock import patch
        from abp_server import read_sources
        with patch('abp_ocr.extract',return_value={'review_candidates':[{}]*300,'warnings':[]}):
            result=read_sources([('one.pdf',pdf(False)),('two.pdf',pdf(False))])
        self.assertEqual(len(result['image_review']),300)
        self.assertEqual(len(result['sources']),2)
        self.assertTrue(any('queue limit' in w for w in result['warnings']))
    def test_no_units_no_flow(self):
        words=table_words(); words[5]['text']='L/S'
        self.assertEqual(self.candidate(words)['review_values'],{})
    def test_actual_excluded(self):
        words=table_words(); words[4]['text']='ACTUAL'
        self.assertEqual(hood_candidates(words,'test',1,'native'),[])
    def test_low_confidence_blank(self):
        self.assertEqual(self.candidate(table_words(70))['review_values'],{})
    def test_extra_column_ambiguous(self):
        words=table_words()+[word(450,100,480,112,'800')]
        self.assertEqual(self.candidate(words)['review_values'],{})
    def test_native_only_no_ocr(self):
        r=extract(pdf(False),engine=lambda *a: self.fail('Unexpected OCR'))
        self.assertEqual(r['ocr_attempted_pages'],0); self.assertEqual(len(r['review_candidates']),1)
    def test_image_only_actual_ocr(self):
        r=extract(pdf()); self.assertEqual(r['pages'][0]['native_words'],[])
        self.assertTrue(any(c['tag']=='KH-1' for c in r['review_candidates']))
        self.assertEqual(r['review_candidates'][0]['review_values'],{'exhaust_cfm':2400,'makeup_air_cfm':1800})
    def test_mixed_actual_ocr(self):
        r=extract(pdf(mixed=True)); self.assertTrue(r['pages'][0]['native_words'])
        self.assertTrue(any(c['tag']=='KH-1' for c in r['review_candidates']))
    def test_page_budget(self):
        r=extract(pdf(pages=2),budget=Budget(max_pages=1),engine=lambda *a:table_words(99))
        self.assertEqual(r['pages'][1]['ocr_status'],'budget_skipped')
    def test_pixel_budget(self):
        r=extract(pdf(),budget=Budget(max_total_pixels=1),engine=lambda *a:self.fail())
        self.assertEqual(r['ocr_attempted_pages'],0)
    def test_timeout_preserves_native(self):
        def fail(*a): raise subprocess.TimeoutExpired('tesseract',1)
        r=extract(pdf(mixed=True),engine=fail)
        self.assertEqual(r['pages'][0]['ocr_status'],'failed'); self.assertTrue(r['pages'][0]['native_words'])
    def test_missing_engine(self):
        def fail(*a): raise FileNotFoundError('not installed')
        self.assertEqual(extract(pdf(),engine=fail)['pages'][0]['ocr_status'],'failed')
    def test_ocr_word_budget(self):
        r=extract(pdf(),budget=Budget(max_words=1),engine=lambda *a:table_words())
        self.assertEqual(r['pages'][0]['ocr_status'],'failed')
    def test_source_bytes_budget(self):
        with self.assertRaises(ValueError): extract(pdf(),budget=Budget(max_pdf_bytes=1))
    def test_conflicts_are_not_suppressed(self):
        d=pymupdf.open(stream=pdf(False),filetype='pdf')
        blank=pymupdf.Pixmap(pymupdf.csGRAY,pymupdf.IRect(0,0,2,2),False)
        blank.clear_with(255)
        d[0].insert_image(pymupdf.Rect(450,150,460,160),stream=blank.tobytes('png'))
        other=table_words(99); other[-2]['text']='2600'
        r=extract(d.tobytes(),engine=lambda *a:other); d.close()
        self.assertEqual([c['review_values']['exhaust_cfm'] for c in r['review_candidates']],[2400,2600])
        self.assertTrue(all(c['values']=={} for c in r['review_candidates']))
        self.assertFalse(r['complete_takeoff'])
    def test_total_time_budget(self):
        def slow(*a): time.sleep(.02); return []
        r=extract(pdf(pages=2),budget=Budget(total_seconds=.01),engine=slow)
        self.assertEqual(r['pages'][1]['ocr_status'],'budget_skipped')
    def test_rotated_coordinates(self):
        d=pymupdf.open(stream=pdf(False),filetype='pdf'); d[0].set_rotation(90)
        r=extract(d.tobytes()); d.close()
        self.assertTrue(all(0 <= w['box'][0] <= 220 and 0 <= w['box'][1] <= 500 for w in r['pages'][0]['native_words']))
    def test_process_isolation_and_scan_queue(self):
        from abp_ocr import extract as isolated
        from abp_server import read_sources
        report=isolated(pdf())
        self.assertEqual(len(report['review_candidates']),1)
        self.assertNotIn('pages',report)
        scanned=read_sources([('synthetic.pdf',pdf())])
        self.assertEqual(len(scanned['image_review']),1)
        self.assertEqual(scanned['records'],[])
    def test_actual_ocr_diffuser_queue(self):
        from abp_ocr import extract as isolated
        source=pymupdf.open();page=source.new_page(width=400,height=300)
        for x,y,text in [(20,30,'MECHANICAL PLAN'),(100,100,'SA'),(100,110,'125')]:
            page.insert_text((x,y),text,fontsize=8)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3))
        doc=pymupdf.open();page=doc.new_page(width=400,height=300)
        page.insert_image(page.rect,stream=pix.tobytes('png'))
        result=isolated(doc.tobytes());source.close();doc.close()
        candidate=result['review_candidates'][0]
        self.assertEqual(candidate['kind'],'diffuser')
        self.assertEqual(candidate['review_values'],{'design_cfm':125})
        self.assertFalse(candidate['include'])
        self.assertEqual(candidate['size'],'')
    def test_production_stream_does_not_retain_page_words(self):
        report=extract(pdf(pages=8),engine=lambda *args:table_words(99),retain_words=False)
        self.assertEqual(len(report['pages']),8)
        self.assertEqual(len(report['review_candidates']),8)
        self.assertTrue(all('native_words' not in page and 'ocr_words' not in page for page in report['pages']))
        self.assertTrue(all(item['review_values']['exhaust_cfm']==2400 for item in report['review_candidates']))
    def test_dense_native_pages_do_not_accumulate_word_arrays(self):
        doc=pymupdf.open()
        for _ in range(10):
            page=doc.new_page(width=600,height=1600)
            for line in range(100):
                page.insert_text((10,20+15*line),' '.join(['NATIVE']*15),fontsize=7)
        data=doc.tobytes();doc.close()
        report=extract(data,retain_words=False,engine=lambda *args:self.fail('Dense native pages must not invoke OCR'))
        self.assertEqual(len(report['pages']),10)
        self.assertEqual(report['ocr_attempted_pages'],0)
        self.assertTrue(all(set(page)=={'page','ocr_status'} for page in report['pages']))
    def test_worker_timeout_is_explicit(self):
        from abp_ocr import extract as isolated
        result=isolated(pdf(),timeout=.001)
        self.assertEqual(result['review_candidates'],[])
        self.assertTrue(any('failed' in warning for warning in result['warnings']))
    def test_worker_failure_is_explicit(self):
        from abp_ocr import extract as isolated
        result=isolated(b'not a PDF')
        self.assertEqual(result['review_candidates'],[])
        self.assertTrue(any('failed' in warning for warning in result['warnings']))
    def test_invalid_budget(self):
        with self.assertRaises(ValueError): extract(pdf(),budget=Budget(max_pages=0))
    def test_no_guessed_fan_relationship(self):
        c=self.candidate(); self.assertNotIn('system',c); self.assertNotIn('design_cfm',c['review_values'])

if __name__=='__main__': unittest.main(verbosity=2)
