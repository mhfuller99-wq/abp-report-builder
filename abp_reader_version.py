"""Content version for checkpoint reuse; independent of Git being installed."""
import hashlib
from pathlib import Path

def reader_version():
    digest=hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob('abp_*.py')):
        digest.update(path.name.encode());digest.update(b'\0');digest.update(path.read_bytes().replace(b'\r\n',b'\n'))
    return digest.hexdigest()

READER_VERSION=reader_version()
