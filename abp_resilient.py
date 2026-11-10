"""Request-local, sequential OCR after all native sources. No persistent uploads."""
import hashlib
import os
import tempfile
import time
from pathlib import Path
from abp_limits import mark_staging


def deferred_ocr(name, source, identity, timeout):
    """Re-stage a seekable upload; verify identity before using its image evidence."""
    from abp_ocr import Budget, extract
    empty={'review_candidates':[], 'warnings':[name+': image reading incomplete; review original images manually.'], 'coverage':[]}
    if timeout <= 0 or identity.get('bytes',0)>Budget().max_pdf_bytes:
        return empty
    start=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='native-',dir=os.environ.get('ABP_SCAN_TMPDIR')) as directory:
            root=Path(directory);mark_staging(root);path=root/'source.pdf'
            digest=hashlib.sha256();total=0
            source.seek(0)
            with path.open('xb') as output:
                os.chmod(path,0o600)
                while True:
                    chunk=source.read(65536)
                    if not chunk:break
                    total+=len(chunk)
                    if total>identity['bytes'] or time.monotonic()-start>=timeout:return empty
                    digest.update(chunk);output.write(chunk)
            if total!=identity['bytes'] or digest.hexdigest()!=identity['sha256']:return empty
            remaining=timeout-(time.monotonic()-start)
            if remaining<=0:return empty
            return extract(None,name,timeout=remaining,path=path)
    except Exception:
        return empty
