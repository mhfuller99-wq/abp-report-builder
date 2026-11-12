"""Synthetic checks for mixed plan content, small crops, and visible omissions."""
import unittest
from unittest.mock import patch
import pymupdf
from abp_ocr import Budget, extract_local, word


class PlanIntegrationTests(unittest.TestCase):
    def test_keyed_grilles_use_distinct_markers_and_exact_flow_reread(self):
        from test_keynotes import fixture
        words,markers,notes=fixture()
        for original in words:
            if original['text']=='225CFM':original['confidence']=40
        with pymupdf.open() as doc:
            page=doc.new_page(width=1200,height=900)
            page.insert_text((20,30),'HVAC PLAN')
            def engine(*args,psm,clip,**kwargs):
                if psm==6:return [dict(w) for w in words if w['box'][0]>=584]
                if psm==7:return [word(*clip,'225CFM',95)]
                if psm==10:
                    return [dict(w) for w in words if w['text'].isdigit() and
                            clip[0] <= (w['box'][0]+w['box'][2])/2 <= clip[2] and
                            clip[1] <= (w['box'][1]+w['box'][3])/2 <= clip[3]]
                return []
            with patch('abp_ocr.paired_text_regions',return_value=([],False)), \
                 patch('abp_ocr.keynote_regions',return_value=(markers,notes,False)):
                report=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            candidates=[c for c in report['review_candidates'] if c['method']=='ocr_keynote']
            self.assertEqual([c['review_values']['design_cfm'] for c in candidates],[225,135,135])
            self.assertTrue(all(c['values']=={} and not c['include'] for c in candidates))

    def test_small_crops_precede_tiles_and_repeat_does_not_add_outlet(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_text((20,30),'HVAC PLAN')
            calls=[]
            def engine(*args,psm,**kwargs):
                calls.append(psm)
                return [word(100,100,130,106,'824CD',95),word(100,110,135,116,'175CFM',95)]
            with patch('abp_ocr.paired_text_regions',return_value=([[95,95,140,120]],False)):
                report=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            self.assertEqual(calls[0],6)
            self.assertEqual(len(report['review_candidates']),1)
            self.assertEqual(report['review_candidates'][0]['review_values'],{'design_cfm':175})
            self.assertFalse(report['review_candidates'][0]['include'])
            self.assertFalse(report['complete_takeoff'])
            self.assertLessEqual(report['pixels_processed'],Budget().max_page_pixels)

    def test_native_callouts_do_not_suppress_outlined_plan_search(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_text((20,30),'HVAC PLAN')
            for x in (100,200,300):
                page.insert_text((x,100),'A',fontsize=10)
                page.insert_text((x-5,117),'250',fontsize=10)
            calls=[]
            result=extract_local(doc.tobytes(),region_engine=lambda *a,**k:calls.append(k['clip']) or [],retain_words=False)
            self.assertTrue(calls)
            self.assertEqual(result['coverage'][0]['selection'],'plan_tiles')

    def test_checkpoint_lists_pending_bottom_tiles(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_text((20,30),'HVAC PLAN')
            snapshots=[]
            def checkpoint(report):
                import copy
                snapshots.append(copy.deepcopy(report))
            report=extract_local(doc.tobytes(),region_engine=lambda *a,**k:[],
                                 budget=Budget(max_regions_per_page=1),checkpoint=checkpoint,retain_words=False)
            tiles=report['coverage'][0]['planned_tiles']
            self.assertEqual(len(tiles),6)
            self.assertTrue(any(t['status']=='budget_skipped' for t in tiles))
            self.assertTrue(any(s['coverage'] and s['coverage'][0].get('planned_tiles') and
                                all(t['status']=='not_examined' for t in s['coverage'][0]['planned_tiles'])
                                for s in snapshots))


if __name__=='__main__':unittest.main()
