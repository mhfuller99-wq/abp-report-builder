import http.client
import threading
import unittest
from unittest.mock import patch
from abp_server import ReportHTTPServer, Handler


class StartupTests(unittest.TestCase):
    def test_health_served_without_hostname_resolution(self):
        with patch('socket.getfqdn', side_effect=RuntimeError('DNS unavailable')) as resolve:
            with ReportHTTPServer(('0.0.0.0', 0), Handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    connection.request('GET', '/healthz')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    connection.close()
                    resolve.assert_not_called()
                finally:
                    server.shutdown()
                    worker.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
