import http.client,io,json,tempfile,threading,time,unittest
from unittest.mock import patch
import abp_server as app
from abp_jobs import Jobs
from test_upload_memory import body

class JobApiTests(unittest.TestCase):
    def test_scan_is_accepted_then_reconnects_without_a_long_request(self):
        release=threading.Event()
        def read(blobs,runner):release.wait(2);return {'records':[{'tag':'EF-1'}],'scan_status':'review_required'}
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'ABP_SCAN_TMPDIR':tmp}):
            jobs=Jobs(threading.Lock(),read,lambda p:b'checked-xlsx')
            server=app.ReportHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,data=None,headers={}):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);conn.request(method,path,data,headers)
                response=conn.getresponse();result=response.read();status=response.status;conn.close();return status,result
            try:
                with patch.object(app,'JOBS',jobs),patch.object(app,'LAN_MODE',False):
                    status,data=request('POST','/api/jobs/scan',body([('files','one.csv',b'TAG,CFM\nEF-1,75')]),{'Content-Type':'multipart/form-data; boundary=ABP-test'})
                    self.assertEqual(status,202);token=json.loads(data)['id']
                    self.assertEqual(request('GET','/api/jobs/'+token)[0],200)
                    self.assertEqual(request('GET','/api/jobs/'+token+'/result')[0],409)
                    self.assertEqual(request('GET','/healthz')[0],200)
                    with patch.object(app,'LAN_MODE',True),patch.object(app,'ACCESS_PASSWORD','synthetic-password-123'):
                        self.assertEqual(request('GET','/api/jobs/'+token)[0],401)
                    release.set()
                    if jobs.worker:jobs.worker.join(3)
                    status,data=request('GET','/api/jobs/'+token+'/result');self.assertEqual(status,200)
                    self.assertEqual(json.loads(data)['records'][0]['tag'],'EF-1')
                    self.assertEqual(request('GET','/api/jobs/'+'f'*48)[0],404)
                    invalid={'project':'Blocked','templates':['Notes.xlsx'],'scan_state':{'status':'incomplete','complete_takeoff':False,'source_checkpoints':[],'warnings':[]}}
                    status,data=request('POST','/api/jobs/build',json.dumps(invalid),{'Content-Type':'application/json'})
                    self.assertEqual(status,400);self.assertIn(b'incomplete',data)
            finally:release.set();server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
