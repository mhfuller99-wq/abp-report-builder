import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from abp_limits import cleanup_orphan_staging,mark_staging
from abp_upload import Reader

class LifecycleTests(unittest.TestCase):
    def test_cleanup_only_marked_dead_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('native-dead','native-live','native-unmarked','unrelated'):
                (root/name).mkdir()
            for name in ('native-dead','native-live','unrelated'):
                mark_staging(root/name)
                p=root/name/'owner.json';owner=json.loads(p.read_text());owner['created']=0
                if name!='native-live':owner['pid']=2**30
                p.write_text(json.dumps(owner))
            self.assertEqual(cleanup_orphan_staging(d),1)
            self.assertEqual({p.name for p in root.iterdir()},{'native-live','native-unmarked','unrelated'})
    def test_upload_absolute_deadline(self):
        import io
        reader=Reader(io.BytesIO(b'123'),3)
        reader.deadline=time.monotonic()-1
        with self.assertRaisesRegex(ValueError,'time limit'):reader.more()
    def test_ocr_worker_does_not_inherit_secrets(self):
        from abp_ocr import extract
        observed={}
        def stop(args,**kw):
            observed.update(kw['env']);raise OSError('synthetic launch stop')
        with patch.dict(os.environ,{'ABP_TEST_SECRET':'do-not-forward'}), patch('abp_ocr.subprocess.Popen',side_effect=stop):
            report=extract(b'synthetic')
        self.assertNotIn('ABP_TEST_SECRET',observed)
        self.assertEqual(set(observed),{'PATH','HOME','LANG','ABP_PARENT_PID','OMP_THREAD_LIMIT','TMPDIR','TEMP','TMP'})
        self.assertEqual(report['review_candidates'],[])

    def test_parent_death_reaches_exec_child(self):
        helper=str(Path(__file__).with_name('abp_limits.py'))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target="import os,pathlib,time;pathlib.Path("+repr(str(root/'ready'))+").write_text(str(os.getpid()));time.sleep(60)"
            parent_code="import os,subprocess,sys,time;subprocess.Popen([sys.executable,"+repr(helper)+",'--exec-with-parent',str(os.getpid()),sys.executable,'-c',"+repr(target)+"]);time.sleep(60)"
            parent=subprocess.Popen([sys.executable,'-c',parent_code])
            try:
                end=time.monotonic()+5
                while not (root/'ready').exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue((root/'ready').exists());pid=int((root/'ready').read_text())
                parent.kill();parent.wait()
                end=time.monotonic()+3;running=True
                while running and time.monotonic()<end:
                    try:running=Path(f'/proc/{pid}/stat').read_text().split()[2]!='Z'
                    except FileNotFoundError:running=False
                    if running:time.sleep(.01)
                self.assertFalse(running,'exec child survived parent termination')
            finally:
                if parent.poll() is None:parent.kill();parent.wait()

if __name__=='__main__':unittest.main()
