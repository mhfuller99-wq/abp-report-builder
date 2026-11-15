import hashlib,http.client,io,json,tempfile,threading,time,unittest
from unittest.mock import patch
import abp_server as app
from abp_jobs import Jobs
from test_upload_memory import body

class JobApiTests(unittest.TestCase):
    def test_csv_scan_retains_source_hash_for_saved_review_recovery(self):
        source=b'TAG,DESIGN CFM,ESP\nAHU-1,1200,0.5'
        result=app.read_sources([('schedule.csv',io.BytesIO(source))])
        self.assertEqual(result['source_checkpoints'][0]['sha256'],hashlib.sha256(source).hexdigest())
        self.assertFalse(result['complete_takeoff'])

    def test_recovery_upload_validates_identity_before_enqueue(self):
        source=b'TAG,CFM\nEF-1,75';identity=[{'name':'one.csv','sha256':hashlib.sha256(source).hexdigest()}]
        calls=[]
        def read(blobs,runner):calls.append(True);return {'records':[],'scan_status':'review_required'}
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'ABP_SCAN_TMPDIR':tmp}):
            jobs=Jobs(threading.Lock(),read,None)
            server=app.ReportHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def upload(fields):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                conn.request('POST','/api/jobs/scan',body([('files','one.csv',source)]+fields),{'Content-Type':'multipart/form-data; boundary=ABP-test'})
                response=conn.getresponse();data=response.read();status=response.status;conn.close();return status,data
            try:
                with patch.object(app,'JOBS',jobs),patch.object(app,'LAN_MODE',False):
                    for value in (b'null',b'[]',json.dumps([dict(identity[0],sha256='b'*64)]).encode()):
                        self.assertEqual(upload([('recovery_sources',None,value)])[0],400)
                        self.assertEqual(calls,[]);self.assertEqual(jobs.jobs,{})
                    field=('recovery_sources',None,json.dumps(identity).encode())
                    self.assertEqual(upload([field,field])[0],400)
                    status,data=upload([field]);self.assertEqual(status,202)
                    if jobs.worker:jobs.worker.join(3)
                    self.assertEqual(calls,[True]);self.assertEqual(json.loads(data)['sources'][0]['sha256'],identity[0]['sha256'])
            finally:
                if jobs.worker:jobs.worker.join(3)
                server.shutdown();server.server_close();thread.join()

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
