"""Disk-staged native PDF scanning with supervised resource limits."""
import hashlib, json, os, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from abp_limits import bind_to_parent, mark_staging

SLOT = threading.Lock()  # Single PROCESS only; deployment needs global admission.
BASE = Path(__file__).resolve().parent
MAX_INPUT = 200_000_000
MAX_RESULT = 4_000_000

class ScanIncomplete(ValueError):
    pass

def staging_root():
    return os.environ.get('ABP_SCAN_TMPDIR') or tempfile.gettempdir()


def incomplete(reason, source=None):
    return {'status':'incomplete', 'complete_takeoff':False, 'reason':reason,
            'candidates':[], 'outlets':[], 'chunks':[], 'warnings':[
                'Native scan incomplete: '+reason+'. No partial native results accepted; split the PDF or review manually.'],
            'source':source, 'image_review':None}


def scan(name, stream, *, timeout=30, address_mb=256, stage_root=None, max_result=MAX_RESULT, ocr_timeout=65, input_limit=MAX_INPUT):
    """Stage bounded chunks; spawn fresh interpreter; do not import native libs here.

    Native and OCR workers run sequentially; no full-PDF bytes enter the server.
    """
    if sys.platform != 'linux': return incomplete('unsupported resource controls')
    if not SLOT.acquire(blocking=False): return incomplete('scan busy')
    started=time.monotonic(); proc=None; source=None
    try:
        with tempfile.TemporaryDirectory(prefix='native-', dir=stage_root or staging_root()) as directory:
            root=Path(directory); mark_staging(root); total=0; digest=hashlib.sha256()
            with (root/'source.pdf').open('xb') as output:
                os.chmod(root/'source.pdf',0o600)
                while True:
                    chunk=stream.read(65536)
                    if not chunk: break
                    total+=len(chunk)
                    if total>min(input_limit,MAX_INPUT): return incomplete('input size limit')
                    output.write(chunk); digest.update(chunk)
                    if time.monotonic()-started>timeout: return incomplete('staging time limit')
            source={'name':Path(name).name[:160], 'sha256':digest.hexdigest(), 'bytes':total}
            (root/'request.json').write_text(json.dumps({'source':source,'address_mb':address_mb}))
            proc=subprocess.Popen([sys.executable,'-I',str(BASE/'abp_scan.py'),'--worker',str(root)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=True,env={'PATH':os.defpath,'HOME':directory,'TMPDIR':directory,
                                           'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','ABP_PARENT_PID':str(os.getpid())})
            reason=None
            try:
                proc.wait(timeout=max(.001,timeout-(time.monotonic()-started)))
            except subprocess.TimeoutExpired:
                reason='wall time limit'
            finally:
                try: os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait()
            result=root/'result.json'
            if reason: return incomplete(reason,source)
            if proc.returncode or not result.exists(): return incomplete('worker failed or resource limit',source)
            if result.stat().st_size>max_result: return incomplete('result size limit',source)
            report=json.loads(result.read_text())
            report['source']=source
            report['elapsed_seconds']=round(time.monotonic()-started,3)
            # Native process is reaped before admitting the separate OCR worker.
            from abp_ocr import extract
            ocr_timeout=max(0,ocr_timeout-(time.monotonic()-started))
            if ocr_timeout > 0:
                report['ocr']=extract(None,source['name'],timeout=ocr_timeout,path=root/'source.pdf')
            else:
                report['ocr']={'review_candidates':[], 'warnings':[source['name']+': image-reading time budget exhausted; review images manually']}
            return report
    except (ValueError,OSError,subprocess.SubprocessError):
        return incomplete('staging or worker failure',source)
    finally:
        SLOT.release()


def worker(directory):
    # Limits apply BEFORE importing MuPDF or parsing any document.
    import resource
    bind_to_parent(os.environ['ABP_PARENT_PID'])
    root=Path(directory); request=json.loads((root/'request.json').read_text())
    cap=request['address_mb']*1024**2
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap))
    resource.setrlimit(resource.RLIMIT_CPU,(25,25))
    resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_RESULT,MAX_RESULT))
    resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    sys.path.insert(0,str(BASE))
    import pymupdf
    from abp_schedule import parse_pdf
    name=request['source']['name']; path=str(root/'source.pdf')
    with pymupdf.open(filename=path) as doc:
        if doc.page_count>300: raise ValueError('page limit')
        page_count=doc.page_count
    found,warnings,outlets=parse_pdf(name,path=path)
    chunks=[]; chars=0
    with pymupdf.open(filename=path) as doc:
        for i,page in enumerate(doc):
            words=page.get_text('words') or []
            text=' '.join(w[4] for w in sorted(words,key=lambda w:(w[1],w[0])))
            chars+=len(text)
            if chars>1_000_000: raise ValueError('text budget')
            chunks.append([f'page {i+1}',text])
            pymupdf.TOOLS.store_shrink(100)
    if len(found)>2000 or len(outlets)>500: raise ValueError('candidate budget')
    report={'status':'completed_native_stage','complete_takeoff':False,'candidates':found,
            'outlets':outlets,'chunks':chunks,'warnings':warnings,'pages':page_count,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    encoded=json.dumps(report,allow_nan=False).encode()
    if len(encoded)>MAX_RESULT: raise ValueError('result budget')
    (root/'result.json').write_bytes(encoded)

if __name__=='__main__': worker(sys.argv[2])
