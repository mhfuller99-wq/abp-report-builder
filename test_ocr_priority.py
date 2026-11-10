"""Synthetic ordering regressions; no customer documents or text."""
import time,unittest
import pymupdf
from abp_ocr import Budget,extract_local,prioritized_pages


class PriorityTests(unittest.TestCase):
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
