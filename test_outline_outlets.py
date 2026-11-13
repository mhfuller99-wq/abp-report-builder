"""Synthetic outline-recognition safeguards; no client files or design values."""
import copy
import time
import unittest
from unittest.mock import patch

import pymupdf

from abp_outline_outlets import atlas, candidates, context_jobs, prepare
from abp_ocr import Budget, extract_local, word


def signature(digit):
    return [((0., 0.), (int(digit)/10., 1.))]


def plan(text, x=100):
    return {'type': 'S1', 'anchor': [x, 80, x+12, 90],
            'crop': [x-5, 87, x+18, 102], 'glyphs': [signature(c) for c in text], 'paths': []}


def readings(index, text, confidence=96, views=(0, 1)):
    return [{'anchor_index': index, 'view': view,
             'words': [{'text': text, 'confidence': confidence}]} for view in views]


def decode(plans, jobs):
    return candidates(plans, jobs, 'synthetic.pdf', 2, time.monotonic()+2)


def drawing(count=2, rotation=0):
    doc = pymupdf.open(); page = doc.new_page(width=600, height=800)
    page.insert_text((20, 30), 'HVAC PLAN')
    for index in range(count):
        page.insert_text((100+index*60, 100), 'S1', fontsize=10)
    anchors = [w for w in page.get_text('words') if w[4] == 'S1']
    for anchor in anchors:
        for digit in range(2):
            x = anchor[0]+digit*7; y = anchor[3]+1
            shape = page.new_shape()
            for a, b in [((x+5,y),(x,y)), ((x,y),(x,y+4)), ((x,y+4),(x+5,y+4)),
                         ((x+5,y+4),(x+5,y+9)), ((x+5,y+9),(x,y+9))]:
                shape.draw_line(a,b)
            shape.finish(width=1.5, color=(0,0,0), closePath=False); shape.commit()
    page.set_rotation(rotation)
    return doc


class OutlineCandidateTests(unittest.TestCase):
    def test_shapes_transfer_only_from_two_distinct_views_and_stay_unverified(self):
        plans=[plan('145'), plan('541',200)]
        original=copy.deepcopy(plans)
        found=decode(plans,readings(0,'145'))
        self.assertEqual([c['review_values'] for c in found],[{'design_cfm':145},{'design_cfm':541}])
        self.assertEqual(plans,original)
        self.assertTrue(all(c['status']=='UNVERIFIED' and not c['include'] and c['values']=={} for c in found))
        self.assertTrue(all(not c['size'] and 'system' not in c for c in found))
        self.assertEqual(found[1]['position'],[200,80])
        self.assertEqual(found[1]['outline_support_anchors'],[[1],[1],[1]])

    def test_one_view_duplicates_and_low_confidence_cannot_teach_digits(self):
        for jobs in (readings(0,'145',views=(0,0)),readings(0,'145',89),readings(0,'145',views=(0,))):
            with self.subTest(jobs=jobs):self.assertEqual(decode([plan('145')],jobs)[0]['review_values'],{})

    def test_conflicting_shape_identity_blanks_both_readings(self):
        plans=[plan('145'),plan('145',200)]
        found=decode(plans,readings(0,'145')+readings(1,'149'))
        self.assertTrue(all(c['review_values']=={} for c in found))
        self.assertEqual(found[0]['outline_shape_reading'],'14?')

    def test_confident_local_alternative_is_retained_and_blocks_flow(self):
        jobs=readings(0,'145')+readings(1,'149',views=(0,))
        found=decode([plan('145'),plan('145',200)],jobs)
        self.assertEqual(found[1]['review_values'],{})
        self.assertEqual(found[1]['outline_readings'][0]['text'],'149')
        self.assertIn('Conflicting',found[1]['review_reasons'][0])

    def test_unknown_digit_never_filled_from_total_or_nearest_numeric_value(self):
        found=decode([plan('145'),plan('146',200)],readings(0,'145'))
        self.assertEqual(found[1]['outline_shape_reading'],'14?')
        self.assertEqual(found[1]['review_values'],{})

    def test_leading_zero_and_non_numeric_tokens_stay_blank(self):
        for text in ('045','I45','14.5','145CFM'):
            self.assertEqual(decode([plan('045')],readings(0,text))[0]['review_values'],{})

    def test_context_reread_has_separate_view_and_does_not_exceed_limit(self):
        plans=[plan('145'),plan('145',200)]
        jobs=readings(0,'145',views=(0,))+readings(1,'145',views=(0,))
        found=context_jobs(plans,jobs,1)
        self.assertEqual(len(found),1);self.assertEqual(found[0]['view'],2)
        self.assertEqual(context_jobs(plans,jobs,0),[])
        self.assertEqual(decode(plans,readings(0,'145',views=(0,2)))[0]['review_values'],{'design_cfm':145})

    def test_page_calibration_does_not_leak_and_deadline_is_honored(self):
        self.assertTrue(decode([plan('145')],readings(0,'145'))[0]['review_values'])
        self.assertEqual(decode([plan('145')],[])[0]['review_values'],{})
        self.assertEqual(candidates([plan('145')],[],'next.pdf',1,time.monotonic()-1),[])
        with self.assertRaises(ValueError):decode([plan('145')]*25,[])


class OutlineGeometryTests(unittest.TestCase):
    def test_rotated_pdf_uses_displayed_native_anchor_coordinates(self):
        with drawing(2) as source,pymupdf.open() as rotated:
            page=rotated.new_page(width=800,height=600)
            page.show_pdf_page(page.rect,source,0,rotate=270)
            page.set_rotation(270)
            native=[{'text':w[4],'box':list(pymupdf.Rect(w[:4])*page.rotation_matrix)} for w in page.get_text('words')]
            plans,limited=prepare(page,native,time.monotonic()+2)
            self.assertEqual(len(plans),2);self.assertFalse(limited)
            anchors=[w['box'] for w in native if w['text']=='S1']
            self.assertEqual([p['anchor'] for p in plans],anchors)

    def test_vector_selection_and_atlas_leave_source_bytes_unchanged(self):
        with drawing() as doc:
            page=doc[0];before=doc.tobytes(no_new_id=True)
            native=[word(*w[:5]) for w in page.get_text('words')]
            plans,limited=prepare(page,native,time.monotonic()+2)
            self.assertEqual(len(plans),2);self.assertFalse(limited)
            cleaned,jobs=atlas(page,plans)
            with cleaned:
                self.assertEqual(len(jobs),4)
                self.assertEqual(jobs[0]['source_box'],plans[0]['crop'])
                self.assertTrue(cleaned[0].get_cdrawings())
            self.assertEqual(doc.tobytes(no_new_id=True),before)

    def test_native_number_is_not_read_again_as_an_outlined_flow(self):
        with drawing(1) as doc:
            page=doc[0];native=[word(*w[:5]) for w in page.get_text('words')]
            anchor=next(w for w in native if w['text']=='S1');box=anchor['box']
            native.append(word(box[0],box[3]+1,box[0]+10,box[3]+8,'55'))
            self.assertEqual(prepare(page,native,time.monotonic()+2)[0],[])

    def test_budget_expiry_and_path_cap_are_explicit(self):
        with drawing() as doc:
            page=doc[0];native=[word(*w[:5]) for w in page.get_text('words')]
            self.assertEqual(prepare(page,native,time.monotonic()-1),([],True))
            self.assertEqual(prepare(page,native,time.monotonic()+2,max_paths=1),([],True))
            plans,limited=prepare(page,native,time.monotonic()+2,max_anchors=1)
            self.assertEqual(len(plans),1);self.assertTrue(limited)

    def test_overlapping_labels_do_not_own_the_same_flow(self):
        with drawing(1) as doc:
            page=doc[0];native=[word(*w[:5]) for w in page.get_text('words')]
            native.append(copy.deepcopy(next(w for w in native if w['text']=='S1')))
            self.assertEqual(prepare(page,native,time.monotonic()+2),([],True))

    def test_integration_checkpoints_before_later_batch_failure(self):
        import subprocess
        snapshots=[];calls=[]
        def batch(page,jobs,timeout,**kwargs):
            calls.append(len(jobs))
            if len(calls)>1:raise subprocess.TimeoutExpired('test',timeout)
            return [[word(*job['box'],'55',96)] for job in jobs]
        with drawing(6) as doc, patch('abp_ocr.paired_text_regions',return_value=([],False)):
            result=extract_local(doc.tobytes(),batch_engine=batch,region_engine=lambda *a,**k:[],
                retain_words=False,checkpoint=lambda r:snapshots.append(copy.deepcopy(r)))
        candidates_=result['review_candidates']
        self.assertEqual(len(candidates_),6)
        self.assertTrue(any(len(s['review_candidates'])==6 for s in snapshots))
        coverage=result['coverage'][0]['planned_outline_regions']
        self.assertEqual([r['views_completed'] for r in coverage],[2,2,2,2,0,0])
        self.assertEqual([r['views_pending'] for r in coverage],[0,0,0,0,2,2])
        self.assertFalse(result['complete_takeoff'])
        self.assertLessEqual(result['pixels_processed'],Budget().max_page_pixels)


if __name__ == '__main__':unittest.main()
