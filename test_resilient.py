import io,time,unittest
from unittest.mock import patch
import abp_scan,abp_server
from test_schedule_pdf import synthetic_schedule_pdf

class ResilientTests(unittest.TestCase):
    def test_failure_preserves_successful_sources(self):
        result=abp_server.read_sources([('first.csv',b'TAG,CFM\nEF-1,400'),('broken.pdf',b'broken'),('last.csv',b'TAG,CFM\nEF-2,600')])
        self.assertEqual(set(result['tags']),{'EF-1','EF-2'})
        self.assertEqual(result['scan_status'],'incomplete')
        self.assertFalse(result['complete_takeoff'])
        self.assertEqual(len(result['source_checkpoints']),3)
        self.assertTrue(all(r['status']=='UNVERIFIED' for r in result['records']))
    def test_native_before_ocr_and_bounded_shares(self):
        events=[];budgets=[]
        real=abp_server.bounded_pdf_scan
        def native(name,stream,**kw):
            events.append('native:'+name);budgets.append(kw['timeout']);self.assertEqual(kw['ocr_timeout'],0)
            return real(name,stream,**kw)
        def ocr(name,stream,identity,timeout):
            events.append('ocr:'+name)
            self.assertGreater(timeout,0)
            return {'review_candidates':[{'tag':'KH-9','status':'UNVERIFIED','include':False}], 'warnings':[], 'coverage':[{'page':1,'status':'partial_review_required'}]}
        with patch.object(abp_server,'bounded_pdf_scan',side_effect=native),patch('abp_resilient.deferred_ocr',side_effect=ocr):
            r=abp_server.read_sources([(x,synthetic_schedule_pdf()) for x in ['a.pdf','b.pdf']])
        self.assertEqual(events,['native:a.pdf','native:b.pdf','ocr:a.pdf','ocr:b.pdf'])
        self.assertNotIn('KH-9',r['tags']);self.assertEqual(len(r['image_review']),2)
        self.assertTrue(all(b<=30 for b in budgets))
    def test_timeout_then_success_and_idempotence(self):
        real=abp_server.bounded_pdf_scan
        def scan(name,stream,**kw):
            return abp_scan.incomplete('wall time limit') if name=='slow.pdf' else real(name,stream,**kw)
        empty={'review_candidates':[],'warnings':['OCR incomplete'],'coverage':[]}
        results=[];pdf=synthetic_schedule_pdf()
        with patch.object(abp_server,'bounded_pdf_scan',side_effect=scan),patch('abp_resilient.deferred_ocr',return_value=empty):
            for _ in range(2):results.append(abp_server.read_sources([('slow.pdf',b'broken'),('good.pdf',pdf)]))
        self.assertTrue(results[0]['tags']);self.assertEqual(results[0],results[1])
        self.assertEqual(results[0]['source_checkpoints'][0]['reason'],'wall time limit')
    def test_ocr_failure_preserves_native_and_later_sources(self):
        with patch('abp_ocr.extract',side_effect=ValueError('forced OCR failure')):
            r=abp_server.read_sources([('a.pdf',synthetic_schedule_pdf()),('b.csv',b'TAG,CFM\nEF-9,900')])
        self.assertIn('EF-9',r['tags']);self.assertGreater(len(r['tags']),1)
        self.assertEqual(r['scan_status'],'incomplete')
    def test_source_order_does_not_change_design_or_review_safety(self):
        a=('a.csv',b'TAG,CFM\nEF-1,400')
        b=('b.csv',b'TAG,CFM\nEF-1,500\nEF-2,700')
        one=abp_server.read_sources([a,b]);two=abp_server.read_sources([b,a])
        def normalize(result):
            return {r['tag']:(r['status'],r.get('proposed'),sorted(r.get('flags',[]))) for r in result['records']}
        self.assertEqual(normalize(one),normalize(two))
        self.assertFalse(one['complete_takeoff'])

    def test_deferred_ocr_identity_change_is_rejected(self):
        from abp_resilient import deferred_ocr
        with patch('abp_ocr.extract') as extract:
            r=deferred_ocr('a.pdf',io.BytesIO(b'new'),{'bytes':3,'sha256':'wrong'},1)
        extract.assert_not_called();self.assertEqual(r['review_candidates'],[])
    def test_ocr_oversize_skips_before_copy(self):
        from abp_resilient import deferred_ocr
        class NeverRead:
            def seek(self,*args):raise AssertionError('Oversize OCR input should not be restaged')
        with patch('abp_ocr.extract') as extract:
            result=deferred_ocr('big.pdf',NeverRead(),{'bytes':40_000_001,'sha256':'unused'},10)
        extract.assert_not_called();self.assertEqual(result['review_candidates'],[])

    def test_deferred_ocr_tiny_budget_is_bounded(self):
        from abp_resilient import deferred_ocr
        start=time.monotonic()
        r=deferred_ocr('a.pdf',io.BytesIO(b'x'*65536),{'bytes':65536,'sha256':'wrong'},.000001)
        self.assertLess(time.monotonic()-start,1);self.assertEqual(r['review_candidates'],[])
if __name__=='__main__':unittest.main()
