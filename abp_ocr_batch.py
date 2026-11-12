"""Bounded small-crop OCR using one display list and one Tesseract process.

The caller owns scan coverage/checkpoints. This function either returns every
requested crop's words in input order or raises; it never calls a partial batch
complete. Coordinates retain each rendered pixmap's exact fractional origin.
"""
import csv
import io
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from abp_ocr_regions import render_geometry


def tesseract_batch_words(page, jobs, timeout, *, psm=6, max_zoom=4.,
                          max_total_pixels=16_000_000, max_words=30_000,
                          max_tsv_bytes=8_000_000):
    """Read up to 32 ``{'box': [...], 'pixels': integer}`` crop requests.

    One invocation uses one segmentation mode (6 for paired labels/notes,
    10 for isolated markers). All crops share the supplied wall/pixel limits.
    No image or recognized text is persisted outside a temporary directory.
    """
    import pymupdf

    started = time.monotonic()
    if (type(jobs) not in (list, tuple) or len(jobs) > 32
            or psm not in (6, 10)
            or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or timeout <= 0
            or not isinstance(max_zoom, (float, int)) or not math.isfinite(max_zoom) or not 0 < max_zoom <= 5
            or type(max_total_pixels) is not int or not 0 < max_total_pixels <= 40_000_000
            or type(max_words) is not int or not 0 < max_words <= 30_000
            or type(max_tsv_bytes) is not int or not 0 < max_tsv_bytes <= 8_000_000):
        raise ValueError('Invalid OCR batch limits')
    if not jobs:
        return []
    requests = []
    estimated_total = 0
    for job in jobs:
        if not isinstance(job, dict) or type(job.get('pixels')) is not int or not 0 < job['pixels'] <= 8_000_000:
            raise ValueError('Invalid OCR crop pixel allowance')
        rect = pymupdf.Rect(job['box'])
        if not all(math.isfinite(v) for v in rect):
            raise ValueError('Invalid OCR crop geometry')
        rect &= page.rect
        zoom, estimate = render_geometry(rect, job['pixels'], max_zoom)
        estimated_total += estimate
        if estimated_total > max_total_pixels:
            raise ValueError('OCR batch pixel budget exceeded')
        requests.append((rect, zoom, estimate))

    def remaining():
        seconds = timeout - (time.monotonic() - started)
        if seconds <= 0:
            raise subprocess.TimeoutExpired('OCR batch', timeout)
        return seconds

    with tempfile.TemporaryDirectory(prefix='abp-ocr-batch-') as directory:
        directory = Path(directory)
        images = []
        mapping = []
        display = pix = None
        try:
            remaining()
            display = page.get_displaylist()
            for index, (rect, zoom, estimate) in enumerate(requests):
                remaining()
                try:
                    pix = display.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect,
                                             colorspace=pymupdf.csGRAY, alpha=False)
                    if pix.width * pix.height > estimate:
                        raise ValueError('OCR crop raster budget exceeded')
                    mapping.append((pix.x, pix.y, zoom, pix.width, pix.height))
                    image = directory / f'crop-{index:03}.png'
                    pix.save(str(image))
                    images.append(str(image))
                finally:
                    pix = None
                    pymupdf.TOOLS.store_shrink(100)
        finally:
            pix = display = None
            pymupdf.TOOLS.store_shrink(100)

        image_list = directory / 'images.txt'
        image_list.write_text('\n'.join(images) + '\n', encoding='utf-8')
        output = directory / 'recognized'
        subprocess.run([sys.executable, str(Path(__file__).with_name('abp_limits.py')), '--exec-with-parent',
                        str(os.getpid()), 'tesseract', str(image_list), str(output),
                        '-l', 'eng', '--psm', str(psm), 'tsv'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=remaining(), check=True)
        remaining()
        tsv = output.with_suffix('.tsv')
        if tsv.stat().st_size > max_tsv_bytes:
            raise ValueError('OCR batch text budget exceeded')
        result = [[] for _ in jobs]
        pages = set()
        words = 0
        reader = csv.DictReader(io.StringIO(tsv.read_text(encoding='utf-8')),
                                delimiter='\t', quoting=csv.QUOTE_NONE)
        required = {'level', 'page_num', 'left', 'top', 'width', 'height', 'conf', 'text'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('Invalid OCR batch TSV header')
        for index, row in enumerate(reader):
            if index % 128 == 0:
                remaining()
            try:
                number = int(row['page_num'])
                level = int(row['level'])
                if not 1 <= number <= len(jobs) or not 1 <= level <= 5:
                    raise ValueError('Invalid OCR batch page mapping')
                if level == 1:
                    if number in pages:
                        raise ValueError('Duplicate OCR batch page')
                    pages.add(number)
                if level != 5 or not row['text'].strip():
                    continue
                if number not in pages:
                    raise ValueError('Missing OCR batch page header')
                x, y, width, height = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
                confidence = float(row['conf'])
                ox, oy, zoom, image_width, image_height = mapping[number - 1]
                if (not math.isfinite(confidence) or not -1 <= confidence <= 100
                        or x < 0 or y < 0 or width <= 0 or height <= 0
                        or x + width > image_width or y + height > image_height):
                    raise ValueError('Invalid OCR batch word geometry or confidence')
                result[number - 1].append({'box': [(ox+x)/zoom, (oy+y)/zoom,
                                                  (ox+x+width)/zoom, (oy+y+height)/zoom],
                                          'text': row['text'], 'confidence': confidence})
                words += 1
                if words > max_words:
                    raise ValueError('OCR batch word budget exceeded')
            except (KeyError, TypeError, OverflowError) as exc:
                raise ValueError('Malformed OCR batch TSV') from exc
        if pages != set(range(1, len(jobs) + 1)):
            raise ValueError('Incomplete OCR batch page mapping')
        return result
