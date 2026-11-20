"""Synthetic ordering regressions; no customer documents or text."""
import copy,io,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from abp_ocr import Budget,extract_local,interrupted_result,prioritized_pages


class PriorityTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','production supervisor uses POSIX process groups')
    def test_supervisor_recovers_checkpoint_when_a_worker_exits_nonzero(self):
        from abp_ocr import extract
        def stopped_worker(args,**kwargs):
            root=Path(args[-1])
            (root/'checkpoint.json').write_text(json.dumps({'complete_takeoff':False,'coverage':[],
                'warnings':[],'review_candidates':[{'source':'worker','page':1,'values':{},'include':False}]}))
            from unittest.mock import Mock
            return Mock(pid=12345,returncode=1,poll=lambda:1)
        with patch('subprocess.Popen',side_effect=stopped_worker),patch('os.killpg'):
            result=extract(b'synthetic worker input','schedule.pdf')
        self.assertEqual(result['review_candidates'][0]['source'],'schedule.pdf')
        self.assertFalse(result['complete_takeoff'])
        self.assertEqual(result['failure_kind'],'worker_failure')

    def test_native_raster_allocation_failure_keeps_the_page_in_review(self):
        def failed_preview(*args,**kwargs):
            raise pymupdf.mupdf.FzErrorSystem('synthetic allocation failure')
        with pymupdf.open() as doc:
            doc.new_page()
            result=extract_local(doc.tobytes(),selector=failed_preview,engine=lambda *args:[])
        self.assertEqual(result['coverage'][0]['selection_failed'],'FzErrorSystem')
        self.assertFalse(result['complete_takeoff'])
        self.assertTrue(any('preview failed' in warning for warning in result['warnings']))

    def test_schedule_worker_can_select_equipment_forms_without_loading_spreadsheets(self):
        subprocess.run([sys.executable,'-c',
            'import sys; from abp_design import inferred_form; '
            'assert inferred_form("RTU-1")=="Air Moving Equipment.xlsx"; '
            'assert "openpyxl" not in sys.modules and "numpy" not in sys.modules'],
            cwd=Path(__file__).resolve().parent,check=True)

    def test_crash_and_timeout_preserve_only_the_atomic_snapshot_as_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            snapshot={'review_candidates':[{'source':'uploaded PDF','page':2,'include':False,'values':{}}],
                      'warnings':[],'complete_takeoff':False,'in_progress_page':2,
                      'coverage':[{'page':1,'status':'native_text_only'},{'page':2,'status':'native_text_only'}]}
            (root/'checkpoint.tmp').write_text('unfinished')
            self.assertEqual(interrupted_result(root,'drawing.pdf','worker_failure')['coverage'],[])
            (root/'checkpoint.json').write_text(json.dumps(snapshot))
            for kind in ('time_budget','worker_failure'):
                result=interrupted_result(root,'drawing.pdf',kind)
                self.assertTrue(result['interrupted'])
                self.assertFalse(result['complete_takeoff'])
                self.assertEqual(result['failure_kind'],kind)
                self.assertEqual(result['review_candidates'],[{**snapshot['review_candidates'][0],'source':'drawing.pdf'}])
                self.assertEqual(result['coverage'][0],snapshot['coverage'][0])
                self.assertEqual(result['coverage'][1]['status'],'partial_review_required')

    def test_small_table_gets_first_pass_when_only_one_region_fits(self):
        calls=[]
        with pymupdf.open() as doc:
            doc.new_page()
            result=extract_local(doc.tobytes(),region_engine=lambda *a,**kw:calls.append(kw['clip']) or [],
                selector=lambda *a,**kw:([[20,200,540,450],[20,20,540,100]],10,False),
                budget=Budget(max_regions=1),retain_words=False)
        self.assertEqual(calls,[[20,20,540,100]])
        self.assertTrue(any(r['status']=='budget_skipped' for r in result['coverage'][0]['regions']))
        self.assertFalse(result['complete_takeoff'])

    def test_source_allowance_respects_the_remaining_job_deadline(self):
        from abp_jobs import SourceRunner
        with tempfile.TemporaryDirectory() as directory:
            runner=SourceRunner({'root':Path(directory),'sources':[{'name':'synthetic.pdf','sha256':'a'*64}]},lambda **p:None)
            runner.save(0,'native',{'pages':3})
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
