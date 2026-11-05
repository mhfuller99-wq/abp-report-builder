import http.client
import threading
import unittest

import abp_server
from abp_server import LOGIN_HTML, PAGE, ReportHTTPServer, Handler


class SiteChromeTests(unittest.TestCase):
    def setUp(self):
        self.server = ReportHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(timeout=3)
        self.server.server_close()

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request(method, path, body=body)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, response.getheader('Content-Type'), response.getheader('Location'), payload)
        connection.close()
        return result

    def test_unknown_page_is_branded(self):
        status, content_type, _location, body = self.request('GET', '/not-a-real-page')
        page = body.decode()
        self.assertEqual(status, 404)
        self.assertTrue(content_type.startswith('text/html'))
        self.assertIn('<title>Page not found · ABP Report Builder</title>', page)
        self.assertIn('Air Balance Professionals', page)
        self.assertIn('src="/logo.png"', page)
        self.assertIn('rel="icon"', page)
        self.assertIn('href="/"', page)
        self.assertIn('Back to Report Builder', page)
        self.assertNotIn('id="generate"', page)
        self.assertNotIn('id="files"', page)

    def test_favicon_and_home_chrome(self):
        status, content_type, _location, body = self.request('GET', '/favicon.png')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'image/png')
        self.assertTrue(body.startswith(b'\x89PNG'))
        status, content_type, _location, body = self.request('GET', '/favicon.ico')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'image/x-icon')
        self.assertTrue(body.startswith(b'\x00\x00\x01\x00'))
        status, content_type, _location, body = self.request('GET', '/')
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith('text/html'))
        self.assertIn('rel="icon"', page)
        self.assertIn('href="/favicon.png"', page)
        self.assertIn('id="files"', page)
        self.assertIn('id="generate"', page)
        self.assertIn('rel="icon"', LOGIN_HTML)
        self.assertIn('href="/favicon.png"', PAGE)

    def test_unknown_api_stays_plain_text(self):
        status, content_type, _location, body = self.request('GET', '/api/not-a-route')
        self.assertEqual(status, 404)
        self.assertTrue(content_type.startswith('text/plain'))
        self.assertEqual(body, b'Not found')
        status, content_type, _location, body = self.request('POST', '/api/not-a-route', b'')
        self.assertEqual(status, 404)
        self.assertTrue(content_type.startswith('text/plain'))
        self.assertEqual(body, b'Not found')

    def test_signed_out_unknown_page_still_goes_to_login(self):
        previous = abp_server.LAN_MODE
        abp_server.LAN_MODE = True
        try:
            status, _content_type, location, _body = self.request('GET', '/not-a-real-page')
            self.assertEqual(status, 303)
            self.assertEqual(location, '/login')
            status, content_type, _location, body = self.request('GET', '/login')
            self.assertEqual(status, 200)
            self.assertTrue(content_type.startswith('text/html'))
            self.assertIn('rel="icon"', body.decode())
            status, content_type, _location, body = self.request('GET', '/favicon.png')
            self.assertEqual(status, 200)
            self.assertEqual(content_type, 'image/png')
            self.assertTrue(body.startswith(b'\x89PNG'))
        finally:
            abp_server.LAN_MODE = previous


if __name__ == '__main__':
    unittest.main()
