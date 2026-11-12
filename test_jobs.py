import io,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from abp_jobs import Jobs,merge_pages,SourceRunner

class JobTests(unittest.TestCase):
    def test_short_image_sources_allow_both_page_passes_within_existing_caps(self):
        for count,remaining,expected in ((2,900,90),(20,900,120),(2,25,25)):
            with tempfile.TemporaryDirectory() as directory:
                job={'root':Path(directory),'sources':[{'name':'synthetic.pdf'}]}
                with patch('abp_jobs.time.monotonic',return_value=100):
                    runner=SourceRunner(job,lambda **k:None);runner.deadline=100+remaining
                    result={'review_candidates':[],'coverage':[],'warnings':[]}
                    with patch.object(runner,'load',side_effect=lambda i,k:{'pages':count} if k=='native' else None), \
                         patch('abp_resilient.deferred_ocr',return_value=result) as read:
                        runner.image('synthetic.pdf',io.BytesIO(b''),{},0)
                    self.assertEqual(read.call_args.args[3],expected)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.guard=patch.dict('os.environ',{'ABP_SCAN_TMPDIR':self.temp.name});self.guard.start()
    def tearDown(self):self.guard.stop();self.temp.cleanup()
    def finish(self,jobs,token):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            state=jobs.get(token)
            if state['status'] in ('done','failed'):return state
            time.sleep(.01)
        self.fail('Job did not finish')
    def test_background_job_reconnect_result_and_private_sources(self):
        entered=threading.Event();release=threading.Event();lock=threading.Lock()
        def read(blobs,runner):
            entered.set();release.wait(2);name,stream=blobs[0]
            self.assertEqual(stream.read(),b'TAG,CFM\nEF-1,75')
            return {'records':[{'tag':'EF-1'}],'complete_takeoff':False}
        jobs=Jobs(lock,read,lambda p:b'xlsx')
        created=jobs.create('scan',parts=[('files','sample.csv',io.BytesIO(b'TAG,CFM\nEF-1,75'))]);token=created['id']
        self.assertEqual(len(token),48);self.assertNotIn('root',created);self.assertTrue(entered.wait(1))
        self.assertEqual(jobs.get(token)['status'],'running');self.assertFalse(lock.acquire(blocking=False))
        with self.assertRaises(KeyError):jobs.get('../result.json')
        release.set();job=self.finish(jobs,token)
        self.assertEqual(job['status'],'done');result=json.loads((job['root']/'result.json').read_text())
        self.assertEqual(result['records'][0]['tag'],'EF-1');self.assertEqual(result['source_manifest'][0]['bytes'],15)
        self.assertTrue(lock.acquire(timeout=1));lock.release()
    def test_failures_do_not_lose_next_job(self):
        def build(payload):
            if payload['fail']:raise ValueError('Template check rejected')
            return b'checked'
        jobs=Jobs(threading.Lock(),None,build)
        a=jobs.create('build',payload={'fail':True});self.assertEqual(self.finish(jobs,a['id'])['status'],'failed')
        b=jobs.create('build',payload={'fail':False});job=self.finish(jobs,b['id']);self.assertEqual(job['status'],'done')
        self.assertEqual((job['root']/'report.xlsx').read_bytes(),b'checked')
    def test_native_page_retry_retains_other_pages_and_does_not_upgrade_context(self):
        old={'status':'incomplete','pages':3,'completed_pages':[1,2], 'candidates':[{'reference':'page 1','tag':'EF-1'},{'reference':'page 2','tag':'EF-2'}], 'outlets':[], 'warnings':[], 'chunks':[]}
        new={'status':'completed_native_stage','completed_pages':[3],'candidates':[{'reference':'page 3','tag':'EF-3'}],'outlets':[],'warnings':[]}
        merged=merge_pages(old,new,[3],'native')
        self.assertEqual([c['tag'] for c in merged['candidates']],['EF-1','EF-2','EF-3'])
        self.assertEqual(merged['status'],'incomplete') # Earlier page interpretation did not finish.
        final=merge_pages(merged,dict(new,completed_pages=[1,2],candidates=[]),[1,2],'native')
        self.assertEqual(final['status'],'completed_native_stage')
    def test_image_retry_replaces_only_selected_page(self):
        old={'review_candidates':[{'page':1,'tag':'KH-1'},{'page':2,'tag':'KH-2'}], 'coverage':[{'page':1,'status':'review_required'},{'page':2,'status':'failed'}],'warnings':[]}
        new={'review_candidates':[{'page':2,'tag':'KH-3'}],'coverage':[{'page':2,'status':'partial_review_required'}],'warnings':[]}
        merged=merge_pages(old,new,[2],'images')
        self.assertEqual([c['tag'] for c in merged['review_candidates']],['KH-1','KH-3']);self.assertEqual(len(merged['coverage']),2)
    def test_duplicate_source_names_fail_without_leaking_files(self):
        jobs=Jobs(threading.Lock(),None,None)
        with self.assertRaisesRegex(ValueError,'unique'):
            jobs.create('scan',parts=[('files','a.pdf',io.BytesIO(b'a')),('files','a.pdf',io.BytesIO(b'b'))])
        self.assertEqual(jobs.jobs,{})
    def test_retry_uses_same_source_hash_without_reupload(self):
        def read(blobs,runner):return {'records':[]}
        jobs=Jobs(threading.Lock(),read,None)
        first=jobs.create('scan',parts=[('files','a.pdf',io.BytesIO(b'same source'))]);parent=self.finish(jobs,first['id'])
        (parent['root']/'inflight.tmp').write_bytes(b'uncommitted status')
        nextjob=jobs.create('scan',parent=first['id'],retry={'source_index':0,'stage':'images','page_numbers':[2]});child=self.finish(jobs,nextjob['id'])
        self.assertFalse((child['root']/'inflight.tmp').exists())
        self.assertEqual(parent['sources'],child['sources']);self.assertEqual((parent['root']/'source-0.pdf').read_bytes(),(child['root']/'source-0.pdf').read_bytes())

if __name__=='__main__':unittest.main()
