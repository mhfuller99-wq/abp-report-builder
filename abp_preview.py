"""Supervised read-only page previews; source bytes are never rewritten."""
import os, signal, subprocess, sys, tempfile, threading
from pathlib import Path

SLOT=threading.Lock()

def render(path,page):
    if type(page)!=int or not 1<=page<=300:raise ValueError('Page must be between 1 and 300')
    if sys.platform!='linux':raise ValueError('Bounded page previews require the production Linux runtime')
    if not SLOT.acquire(blocking=False):raise ValueError('Another page preview is loading; try again')
    try:
        with tempfile.TemporaryDirectory(prefix='native-preview-',dir=os.environ.get('ABP_SCAN_TMPDIR')) as folder:
            from abp_limits import mark_staging
            mark_staging(folder);output=Path(folder)/'page.png'
            proc=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--worker',str(path),str(page),str(output)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,
                env={'PATH':os.defpath,'ABP_PARENT_PID':str(os.getpid())})
            try:proc.wait(timeout=15)
            finally:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            if proc.returncode or not output.exists() or output.stat().st_size>5_000_000:raise ValueError('Preview unavailable for this page; open the original source locally')
            return output.read_bytes()
    finally:SLOT.release()

def worker(path,page,output):
    import resource
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from abp_limits import bind_to_parent
    bind_to_parent(os.environ['ABP_PARENT_PID'])
    for which,value in ((resource.RLIMIT_AS,192*1024**2),(resource.RLIMIT_CPU,12),(resource.RLIMIT_FSIZE,5_000_000),(resource.RLIMIT_CORE,0)):
        resource.setrlimit(which,(value,value))
    import pymupdf
    with pymupdf.open(path) as doc:
        if not 1<=page<=len(doc):raise ValueError('Page outside document')
        source=doc[page-1];area=source.rect.get_area();zoom=min(2,(4_000_000/max(area,1))**.5)
        source.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),colorspace=pymupdf.csGRAY,alpha=False).save(output)

if __name__=='__main__':worker(sys.argv[2],int(sys.argv[3]),sys.argv[4])
