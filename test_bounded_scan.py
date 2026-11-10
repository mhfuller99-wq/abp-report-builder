"""Synthetic-only bounded scanner and API failure regression coverage."""
import hashlib, io, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import abp_scan
import abp_server
from test_schedule_pdf import synthetic_schedule_pdf

class BoundedScanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('ABP_SCAN_TMPDIR'))
        self.root=Path(self.temp.name)
    def tearDown(self):
        self.assertEqual(list(self.root.iterdir()),[])
        self.temp.cleanup()
    def scan(self,data,**kw):
        class Reader(io.BytesIO):
            def read(self,n=-1):
                if not 0<n<=65536:raise AssertionError('unbounded parent PDF read')
                return super().read(n)
        return abp_scan.scan('synthetic.pdf',Reader(data),stage_root=self.root,**kw)
    def test_streaming_hash_and_native_fidelity(self):
        from abp_schedule import parse_pdf
        data=synthetic_schedule_pdf(); expected=parse_pdf('synthetic.pdf',data)
        report=self.scan(data,ocr_timeout=0)
        self.assertEqual(report['status'],'completed_native_stage')
        self.assertEqual([report['candidates'],report['warnings'],report['outlets']],json.loads(json.dumps(expected)))
        self.assertEqual(report['source']['sha256'],hashlib.sha256(data).hexdigest())
        self.assertEqual(report['ocr']['review_candidates'],[])
        self.assertFalse(report['complete_takeoff'])
    def test_memory_limit(self):
        report=self.scan(synthetic_schedule_pdf(),address_mb=32)
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['candidates'],[])
    def test_malformed_is_incomplete(self):
        self.assertEqual(self.scan(b'broken PDF')['status'],'incomplete')
    def test_output_limit(self):
        self.assertEqual(self.scan(synthetic_schedule_pdf(),max_result=10)['reason'],'result size limit')
    def test_input_limit(self):
        self.assertEqual(self.scan(b'x'*100,input_limit=50)['reason'],'input size limit')
    def test_tiny_wall_limit(self):
        self.assertEqual(self.scan(synthetic_schedule_pdf(),timeout=.000001)['status'],'incomplete')
    def test_server_preserves_success_with_explicit_incomplete(self):
        report=abp_scan.incomplete('test budget exhausted')
        with patch.object(abp_server,'bounded_pdf_scan',return_value=report):
            result=abp_server.read_sources([('first.csv',b'TAG,CFM\nEF-1,400'),('bad.pdf',b'broken')])
            self.assertEqual(result['scan_status'],'incomplete')
            self.assertIn('EF-1',result['tags'])
            self.assertFalse(result['complete_takeoff'])
    def test_ocr_sequential_and_path_based(self):
        calls=[]
        def ocr(data,source,timeout,path):
            self.assertIsNone(data);self.assertTrue(Path(path).exists())
            calls.append(source)
            return {'review_candidates':[{'tag':'KH-1','source':source,'review_values':{'exhaust_cfm':900},'page':1}], 'warnings':['review only']}
        with patch('abp_ocr.extract',side_effect=ocr):
            report=self.scan(synthetic_schedule_pdf())
        self.assertEqual(calls,['synthetic.pdf'])
        self.assertEqual(report['ocr']['review_candidates'][0]['tag'],'KH-1')
        self.assertNotIn('KH-1',[x['tag'] for x in report['candidates']])
    def test_busy_rejected(self):
        abp_scan.SLOT.acquire()
        try:self.assertEqual(self.scan(b'')['reason'],'scan busy')
        finally:abp_scan.SLOT.release()

    def test_api_failure_releases_lock_and_health_survives(self):
        import http.client, threading
        from test_upload_memory import body
        payload=body([('files','broken.pdf',b'broken PDF')])
        server=abp_server.ReportHTTPServer(('127.0.0.1',0),abp_server.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('POST','/api/scan',payload,{'Content-Type':'multipart/form-data; boundary=ABP-test'})
            response=conn.getresponse();self.assertEqual(response.status,200)
            report=json.loads(response.read());conn.close()
            self.assertEqual(report['scan_status'],'incomplete');self.assertFalse(report['complete_takeoff'])
            self.assertEqual(report['records'],[])
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('GET','/healthz');response=conn.getresponse();self.assertEqual(response.status,200);response.read();conn.close()
            self.assertTrue(abp_server.WORK_LOCK.acquire(timeout=2));abp_server.WORK_LOCK.release()
        finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
