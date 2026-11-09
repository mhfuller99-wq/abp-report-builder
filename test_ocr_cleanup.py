"""Exercise parent cleanup with a real child killed after creating OCR temp files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from abp_ocr import extract


@unittest.skipUnless(os.name == 'posix', 'OCR worker requires POSIX')
class CleanupTests(unittest.TestCase):
    def exercise(self, timeout):
        original_popen = subprocess.Popen
        observed = {}
        script = '''
import json, pathlib, sys, tempfile, time
root = pathlib.Path(sys.argv[1])
directory = tempfile.mkdtemp(prefix='abp-ocr-')
(pathlib.Path(directory) / 'page.png').write_bytes(b'private page raster')
(root / 'ready.json').write_text(json.dumps(directory))
if sys.argv[2] == 'timeout':
    time.sleep(30)
else:
    (root / 'result.json').write_text(json.dumps({'review_candidates': [], 'warnings': []}))
'''

        def spawn(args, **kwargs):
            root = Path(args[-1])
            observed['root'] = root
            for variable in ('TMPDIR', 'TEMP', 'TMP'):
                self.assertEqual(kwargs['env'][variable], str(root))
            child = original_popen(
                [sys.executable, '-c', script, str(root), 'timeout' if timeout else 'success'],
                **kwargs)
            observed['child'] = child
            deadline = time.monotonic() + 5
            while not (root / 'ready.json').exists():
                if child.poll() is not None or time.monotonic() >= deadline:
                    child.kill()
                    child.wait()
                    self.fail('Test child did not create its temporary raster')
                time.sleep(.01)
            directory = Path(json.loads((root / 'ready.json').read_text()))
            observed['directory'] = directory
            self.assertEqual(directory.parent, root)
            self.assertTrue((directory / 'page.png').exists())
            return child

        with patch('abp_ocr.subprocess.Popen', side_effect=spawn):
            report = extract(b'test source', timeout=.05 if timeout else 5)
        self.assertFalse(observed['root'].exists())
        self.assertFalse(observed['directory'].exists())
        self.assertIsNotNone(observed['child'].poll())
        self.assertEqual(report['review_candidates'], [])
        if timeout:
            self.assertTrue(any('failed' in warning for warning in report['warnings']))
            self.assertLess(observed['child'].returncode, 0)
        else:
            self.assertEqual(report['warnings'], [])
            self.assertEqual(observed['child'].returncode, 0)

    def test_success_removes_child_temp_files(self):
        self.exercise(timeout=False)

    def test_sigkill_removes_child_temp_files(self):
        self.exercise(timeout=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
