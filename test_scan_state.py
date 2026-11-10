import unittest
import http.client,json,threading
from unittest.mock import patch
import abp_server as app

class ScanStateTests(unittest.TestCase):
    def test_incomplete_and_stale_builds_rejected_before_workbook_creation(self):
        for status in ('incomplete','stale','unknown'):
            with patch.object(app,'Workbook') as workbook:
                with self.assertRaisesRegex(ValueError,'no partial report'):
                    app.build({'scan_state':{'status':status,'complete_takeoff':False,'source_checkpoints':[],'warnings':['Missing drawing']}})
                workbook.assert_not_called()
    def test_failed_checkpoint_cannot_claim_success(self):
        state={'status':'review_required','complete_takeoff':False,'source_checkpoints':[{'name':'failed.pdf','native_status':'incomplete','image_status':'not_started'}],'warnings':[]}
        with self.assertRaisesRegex(ValueError,'no partial report'):app.validate_scan_state(state)
    def test_http_legacy_and_forged_empty_history_fail_closed(self):
        server=app.ReportHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def request(payload):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('POST','/api/build',json.dumps(payload),{'Content-Type':'application/json'})
            response=conn.getresponse();result=(response.status,response.read());conn.close();return result
        try:
            with patch.object(app,'build',return_value=b'blank-workbook') as build:
                for payload in ({'records':[{'tag':'EF-1'}]},
                                {'records':[{'tag':'EF-1'}],'scan_state':{'status':'not_scanned','complete_takeoff':False,'source_checkpoints':[],'warnings':[]}},
                                {'records':[{'tag':'EF-1'}],'scan_state':{'status':'review_required','complete_takeoff':False,'source_checkpoints':[],'warnings':[]}}):
                    status,raw=request(payload)
                    self.assertEqual(status,400,raw)
                    build.assert_not_called()
                status,raw=request({'records':[],'scan_state':{'status':'not_scanned','complete_takeoff':False,'source_checkpoints':[],'warnings':[]}})
                self.assertEqual(status,200,raw);build.assert_called_once()
        finally:server.shutdown();server.server_close();worker.join()

    def test_valid_review_state(self):
        app.validate_scan_state({'status':'review_required','complete_takeoff':False,'source_checkpoints':[{'name':'schedule.csv','native_status':'completed_native_stage','image_status':'not_applicable'}],'warnings':[]})
    def test_truncation_marks_source_incomplete(self):
        rows=b'TAG,CFM\n'+b'\n'.join(('EF-%d,400'%n).encode() for n in range(1,502))
        result=app.read_sources([('501.csv',rows)])
        self.assertEqual(result['scan_status'],'incomplete')
        self.assertEqual(result['source_checkpoints'][0]['native_status'],'incomplete')
        self.assertEqual(len(result['records']),500)
if __name__=='__main__':unittest.main()
