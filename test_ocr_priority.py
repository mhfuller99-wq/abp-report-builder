"""Synthetic ordering regressions; no customer documents or text."""
import copy,io,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from abp_ocr import Budget,extract_local,prioritized_pages


class PriorityTests(unittest.TestCase):
    def test_source_allowance_respects_the_remaining_job_deadline(self):
        from abp_jobs import SourceRunner,write_json
        with tempfile.TemporaryDirectory() as directory:
            runner=SourceRunner({'root':Path(directory),'sources':[{'name':'synthetic.pdf'}]},lambda **p:None)
            write_json(runner.cache(0,'native'),{'pages':3})
            runner.deadline=time.monotonic()+20
            with patch('abp_resilient.deferred_ocr',return_value={'review_candidates':[],'coverage':[]}) as image:
                runner.image('synthetic.pdf',io.BytesIO(),{'bytes':0,'sha256':'a'*64},60)
            self.assertGreater(image.call_args.args[3],0)
            self.assertLessEqual(image.call_args.args[3],20)

    def test_region_checkpoint_survives_before_the_next_region_or_page(self):
        from test_targeted_ocr import information_words
        class Interrupted(BaseException):pass
        retained=[];calls=[]
        def checkpoint(report):
            if report['review_candidates']:
                retained.append(copy.deepcopy(report))
                raise Interrupted()
        with pymupdf.open() as doc:
            doc.new_page()
            with self.assertRaises(Interrupted):
                extract_local(doc.tobytes(),region_engine=lambda *a,**kw:calls.append(kw['clip']) or information_words(),
                    selector=lambda *a,**kw:([[0,0,300,150],[0,200,300,350]],10,False),
                    retain_words=False,checkpoint=checkpoint)
        self.assertEqual(len(calls),1)
        self.assertEqual(retained[0]['review_candidates'][0]['tag'],'HD-1')
        self.assertEqual(retained[0]['coverage'][0]['status'],'partial_review_required')
        self.assertFalse(retained[0]['complete_takeoff'])
        self.assertFalse(retained[0]['review_candidates'][0]['include'])

    def drawing(self):
        doc=pymupdf.open()
        for title in ['MECHANICAL PLAN','GENERAL NOTES','EQUIPMENT SCHEDULES']:
            page=doc.new_page();page.insert_text((20,30),title)
        return doc

    def test_schedule_title_precedes_plans_without_changing_scope(self):
        with self.drawing() as doc:
            self.assertEqual(prioritized_pages(doc,None,time.monotonic()+5),[2,0,1])
            self.assertEqual(prioritized_pages(doc,[1,3],time.monotonic()+5),[2,0])

    def test_expired_priority_hint_does_not_drop_pages(self):
        with self.drawing() as doc:
            self.assertEqual(prioritized_pages(doc,None,0),[0,1,2])

    def test_one_page_budget_reads_schedule_first_and_discloses_other_pages(self):
        calls=[]
        with self.drawing() as doc:
            result=extract_local(doc.tobytes(),engine=lambda page,*args:calls.append(page.number+1) or [],
                selector=lambda *a,**kw:([],10,False),budget=Budget(max_pages=1),retain_words=False)
        self.assertEqual(calls,[3])
        self.assertEqual([p['page'] for p in result['coverage']],[3,1,2])
        self.assertTrue(all(p['status']=='budget_skipped' for p in result['coverage'][1:]))
        self.assertFalse(result['complete_takeoff'])

    def test_memory_and_total_time_budgets_have_not_increased(self):
        self.assertEqual(Budget().total_seconds,60)
        self.assertEqual(Budget().max_page_pixels,16_000_000)
        self.assertLessEqual(Budget().max_region_pixels,3_000_000)


if __name__=='__main__':unittest.main()
