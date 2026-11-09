"""Linux worker lifecycle and private, marked staging recovery."""
import json, os, signal, sys, time
from pathlib import Path

def bind_to_parent(expected):
    """Kill this process on parent death, including across an exec (Linux only)."""
    if sys.platform!='linux':raise RuntimeError('Linux process supervision required')
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0:raise OSError(ctypes.get_errno(),'parent supervision unavailable')
    if os.getppid()!=int(expected):os.kill(os.getpid(),signal.SIGKILL)

def mark_staging(root):
    (Path(root)/'owner.json').write_text(json.dumps({'pid':os.getpid(),'created':time.time(),'kind':'abp-private-staging-v1'}))

def cleanup_orphan_staging(directory, *, grace=60):
    """Only same-UID, app-marked, old directories with a dead owner are eligible.

    Live/ambiguous owners and unknown/unmarked files are untouched. Intended for
    a private configured application staging root, never a general temp cleanup.
    """
    import shutil, stat
    root=Path(directory);removed=0
    if not root.is_dir() or root.is_symlink():return removed
    for child in root.iterdir():
        if not child.name.startswith(('native-','abp-ocr-job-')):continue
        try:
            info=child.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():continue
            marker=child/'owner.json'
            if marker.is_symlink() or marker.stat().st_size>1024:continue
            owner=json.loads(marker.read_text())
            if owner.get('kind')!='abp-private-staging-v1':continue
            if time.time()-float(owner['created'])<grace:continue
            pid=owner['pid']
            if type(pid)!=int or pid<=1:continue
            try:os.kill(pid,0)
            except ProcessLookupError:
                shutil.rmtree(child);removed+=1
            except PermissionError:pass
        except (OSError,ValueError,KeyError,TypeError):continue
    return removed

if __name__=='__main__':
    if len(sys.argv)<4 or sys.argv[1]!='--exec-with-parent':raise SystemExit(2)
    bind_to_parent(int(sys.argv[2]))
    os.execvp(sys.argv[3],sys.argv[3:])
