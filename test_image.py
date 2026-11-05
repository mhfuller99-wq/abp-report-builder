"""The production image copies only what the Dockerfile names.

Import the server from that copy, not from the repository tree, so a missing
module fails here the same way it fails on Render.
"""
import ast
import http.client
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_FOR_IMPORT = {'fitz': 'pymupdf'}


def copy_instructions(dockerfile):
    instructions = []
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not line.upper().startswith('COPY '):
            continue
        parts = line.split()
        instructions.append((parts[1:-1], parts[-1]))
    return instructions


def stage_image(dest):
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    for sources, target in copy_instructions(dockerfile):
        matches = []
        for src in sources:
            matches.extend(sorted(ROOT.glob(src.rstrip('/'))))
        if not matches:
            raise AssertionError('Dockerfile COPY matched nothing: ' + ' '.join(sources))
        into_dir = target.endswith('/') or target in {'.', './'} or len(matches) > 1
        for match in matches:
            if target in {'.', './'}:
                out = dest / match.name
            elif match.is_dir():
                out = dest / target.strip('/')
            elif into_dir:
                out = dest / target.strip('/') / match.name
            else:
                out = dest / target
            if match.is_dir():
                shutil.copytree(match, out, dirs_exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(match, out)


def runtime_modules():
    pending = {'abp_server.py'}
    seen = set()
    while pending - seen:
        name = next(iter(pending - seen))
        seen.add(name)
        tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split('.')[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module.split('.')[0]]
            for module in modules:
                if (ROOT / f'{module}.py').is_file():
                    pending.add(f'{module}.py')
    return seen


def third_party_imports():
    found = set()
    for name in runtime_modules():
        tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split('.')[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module.split('.')[0]]
            for module in modules:
                if module in sys.stdlib_module_names or (ROOT / f'{module}.py').is_file():
                    continue
                found.add(PACKAGE_FOR_IMPORT.get(module, module))
    return found


class ImagePackagingTests(unittest.TestCase):
    def test_dockerfile_copies_every_runtime_module_and_dependency(self):
        modules = runtime_modules()
        self.assertIn('abp_schedule.py', modules)
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            stage_image(stage)
            copied = {path.name for path in stage.glob('*.py')}
            self.assertTrue(modules <= copied, sorted(modules - copied))
            self.assertTrue((stage / 'abp_ui.js').is_file())
            self.assertTrue((stage / '04_Company_Branding' / 'favicon.png').is_file())
            self.assertFalse(list(stage.rglob('*.pdf')))
        requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8').lower()
        for package in third_party_imports():
            self.assertIn(package, requirements)

    def test_staged_image_imports_and_answers_healthz(self):
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            stage_image(stage)
            imported = subprocess.run(
                [sys.executable, '-c',
                 'import abp_server, abp_schedule; print(abp_schedule.__file__)'],
                cwd=stage, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            self.assertIn(str(stage), imported.stdout)
            port = '18771'
            server = subprocess.Popen(
                [sys.executable, 'abp_server.py', port],
                cwd=stage, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                ready = False
                for _ in range(80):
                    line = server.stdout.readline()
                    if not line:
                        break
                    if 'Listening on' in line:
                        ready = True
                        break
                self.assertTrue(ready, 'server did not start')
                self.assertIsNone(server.poll())
                connection = http.client.HTTPConnection('127.0.0.1', int(port), timeout=5)
                connection.request('GET', '/healthz')
                response = connection.getresponse()
                body = response.read()
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertEqual(body, b'ok')
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                if server.stdout:
                    server.stdout.close()


if __name__ == '__main__':
    unittest.main()
