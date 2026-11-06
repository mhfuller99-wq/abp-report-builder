import io, unittest, threading, http.client, zipfile
from unittest.mock import patch
from abp_upload import multipart, CHUNK
import abp_server as app

def body(parts,boundary='ABP-test'):
    out=b''
    for name,filename,data in parts:
        out+=f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'.encode()
        if filename:out+=f'; filename="{filename}"'.encode()
        out+=b'\r\n\r\n'+data+b'\r\n'
    return out+f'--{boundary}--\r\n'.encode()

class SmallReads(io.BytesIO):
    def read(self,n=-1):return super().read(min(n,7))

class UploadMemoryTests(unittest.TestCase):
    def test_binary_parts_split_boundaries_and_cleanup(self):
        values=[('files','one.pdf',b'\x00\xff\r\n--ABP-testX'+b'x'*CHUNK),('files','two.pdf',b'two'),('approved',None,b'true')]
        data=body(values)
        with multipart(SmallReads(data),len(data),'multipart/form-data; boundary="ABP-test"',len(data)) as parts:
            self.assertEqual([(name,filename,file.read()) for name,filename,file in parts],values)
            handles=[p[2] for p in parts]
        self.assertTrue(all(f.closed for f in handles))

    def test_truncated_and_oversized_parts_fail(self):
        data=body([('files','one.pdf',b'x'*100)])
        for payload,declared,limit in [(data[:-12],len(data),1000),(data,len(data),10)]:
            with self.assertRaises(ValueError):
                with multipart(io.BytesIO(payload),declared,'multipart/form-data; boundary=ABP-test',limit):pass

    def test_busy_job_does_not_block_health_or_read_body(self):
        server=app.ReportHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        app.WORK_LOCK.acquire()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            conn.request('POST','/api/scan',headers={'Content-Length':'100000000'})
            response=conn.getresponse();self.assertEqual(response.status,503);response.read();conn.close()
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            conn.request('GET','/healthz');response=conn.getresponse();self.assertEqual(response.status,200);response.read();conn.close()
        finally:app.WORK_LOCK.release();server.shutdown();server.server_close();worker.join()

    def test_reference_dimensions_rejected_before_loading(self):
        import abp_reference
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:z.writestr('xl/worksheets/sheet1.xml','<worksheet><dimension ref="A1:XFD1048576"/></worksheet>')
        with patch.object(abp_reference,'load_workbook') as load:
            with self.assertRaisesRegex(ValueError,'too many cells'):abp_reference.open_reference(data.getvalue())
            load.assert_not_called()

if __name__=='__main__':unittest.main()
