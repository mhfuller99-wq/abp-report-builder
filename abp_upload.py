"""Bounded-memory multipart uploads; temporary files are closed after each request."""
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from tempfile import TemporaryFile
import re
import os
import time

CHUNK = 64 * 1024

class Reader:
    def __init__(self, stream, length):
        self.stream, self.remaining, self.buffer = stream, length, b''
        self.deadline=time.monotonic()+60

    def more(self):
        if not self.remaining:
            raise ValueError('Incomplete multipart upload')
        if time.monotonic()>self.deadline:raise ValueError('Upload time limit reached')
        read=getattr(self.stream,'read1',self.stream.read)
        chunk = read(min(CHUNK, self.remaining))
        if time.monotonic()>self.deadline:raise ValueError('Upload time limit reached')
        if not chunk:
            raise ValueError('Upload ended before its declared length')
        self.remaining -= len(chunk)
        self.buffer += chunk

    def until(self, markers, write, limit):
        count = 0
        keep = max(map(len, markers)) - 1
        while True:
            matches = [(self.buffer.find(m), m) for m in markers if m in self.buffer]
            if matches:
                end, marker = min(matches, key=lambda x:x[0])
                if count + end > limit: raise ValueError('Upload part exceeds its size limit')
                write(self.buffer[:end]); self.buffer = self.buffer[end+len(marker):]
                return marker
            size = max(0, len(self.buffer)-keep)
            if count + size > limit: raise ValueError('Upload part exceeds its size limit')
            if size:
                write(self.buffer[:size]); count += size; self.buffer = self.buffer[size:]
            self.more()

@contextmanager
def multipart(stream, length, content_type, limit):
    header = BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\n\r\n').encode('ascii'))
    boundary = header.get_boundary()
    if header.get_content_type() != 'multipart/form-data' or not boundary or not re.fullmatch(r"[ -~]{1,70}",boundary):
        raise ValueError('Expected a multipart document upload')
    marker = b'--'+boundary.encode('ascii')
    reader = Reader(stream,length); parts=[]
    try:
        while len(reader.buffer)<len(marker)+2: reader.more()
        if not reader.buffer.startswith(marker+b'\r\n'): raise ValueError('Invalid multipart boundary')
        reader.buffer=reader.buffer[len(marker)+2:]
        while True:
            chunks=[]; reader.until([b'\r\n\r\n'],chunks.append,16384)
            headers=BytesParser(policy=default).parsebytes(b''.join(chunks)+b'\r\n\r\n')
            if headers.get_content_disposition()!='form-data':raise ValueError('Invalid upload disposition')
            name=headers.get_param('name',header='content-disposition')
            if not name:raise ValueError('Upload field is missing its name')
            if len(parts)>=100:raise ValueError('Upload at most 100 parts at a time')
            file=TemporaryFile(dir=os.environ.get("ABP_SCAN_TMPDIR")); parts.append((name,headers.get_filename(),file))
            ending=reader.until([b'\r\n'+marker+b'\r\n',b'\r\n'+marker+b'--'],file.write,limit)
            file.seek(0)
            if ending.endswith(b'--'):break
        # Drain the declared body without retaining an epilogue in memory.
        reader.buffer=b''
        while reader.remaining:
            reader.more(); reader.buffer=b''
        yield parts
    finally:
        for _,_,file in parts:file.close()
