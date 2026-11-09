"""Bounded, review-only PDF recognition. Never feed this output to resolve_proposed.
No writes to source PDFs, workbooks, repositories, or external services.
"""
import os
import sys
import csv
import io
import math
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Budget:
    max_pages: int = 12
    max_pixels: int = 8_000_000
    max_total_pixels: int = 40_000_000
    dpi: int = 180
    per_page_seconds: float = 15
    total_seconds: float = 60
    max_words: int = 30_000
    max_pdf_bytes: int = 40_000_000


def word(x, y, x2, y2, text, confidence=None):
    return {'box': [x, y, x2, y2], 'text': text, 'confidence': confidence}


def tesseract_words(page, pixels, timeout):
    """Render displayed page orientation; map pixels back to displayed PDF points."""
    import pymupdf
    zoom = math.sqrt(pixels / (page.rect.width * page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    if pix.width * pix.height > pixels + 2 * (pix.width + pix.height):
        raise ValueError('Raster budget exceeded')
    with tempfile.TemporaryDirectory(prefix='abp-ocr-') as directory:
        source = Path(directory) / 'page.png'
        output = Path(directory) / 'recognized'
        pix.save(str(source))
        subprocess.run([sys.executable, str(Path(__file__).with_name('abp_limits.py')), '--exec-with-parent', str(os.getpid()), 'tesseract', str(source), str(output), '-l', 'eng', '--psm', '6', 'tsv'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=timeout, check=True)
        tsv = output.with_suffix('.tsv')
        if tsv.stat().st_size > 8_000_000:
            raise ValueError('OCR text budget exceeded')
        result = []
        for row in csv.DictReader(io.StringIO(tsv.read_text()), delimiter='\t'):
            if row['level'] != '5' or not row['text'].strip():
                continue
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            result.append(word(x / zoom, y / zoom, (x+w) / zoom, (y+h) / zoom,
                               row['text'], float(row['conf'])))
        return result


def lines(words):
    grouped = []
    for w in sorted(words, key=lambda w: (w['box'][1], w['box'][0])):
        if not grouped or abs(w['box'][1] - grouped[-1][0]['box'][1]) > 4:
            grouped.append([w])
        else:
            grouped[-1].append(w)
    return [sorted(row, key=lambda w: w['box'][0]) for row in grouped]


def hood_candidates(words, source, page, method):
    """Only supported, explicit one-line CFM headers; ambiguous layouts stay blank.

    Dedicated schema avoids generic design_cfm and outside-air interpretation.
    No fan/duct connections, supply percentages, or actual measurements inferred.
    """
    result = []
    table = None
    for row in lines(words):
        text = ' '.join(w['text'] for w in row).upper()
        if re.fullmatch(r'(?:KITCHEN )?HOOD SCHEDULE', text):
            table = {'heading': row, 'header': None}
            continue
        if 'SCHEDULE' in text:
            table = None
            continue
        if table is None:
            continue
        if re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|FINAL)\b', text):
            table = None
            continue
        if row[0]['text'].upper() in {'TAG', 'MARK'}:
            # Exact complete header prevents nearby schedules/unknown units being mixed.
            if re.fullmatch(r'(?:TAG|MARK) EXHAUST CFM (?:MAKEUP|MAKE-UP) CFM', text):
                table['header'] = row
            else:
                table['header'] = None
            continue
        if not re.fullmatch(r'(?:KH|KEH|HOOD|H)-\d+(?:\.\d+)*[A-Z]?', row[0]['text'].upper()):
            continue
        if row[0]['box'][1] - table['heading'][0]['box'][1] > 450:
            continue
        tag = row[0]['text'].upper()
        header = table['header']
        values = {}
        reasons = ['Confirm hood identity and each design airflow against source.']
        if header and len(row) == 3 and len(header) == 5:
            # Column bands from tag/exhaust/makeup header centers; require strict alignment.
            centers = [(header[i]['box'][0] + header[i+1]['box'][2])/2 for i in (1, 3)]
            for name, center, cell in zip(('exhaust_cfm', 'makeup_air_cfm'), centers, row[1:]):
                cell_center = (cell['box'][0] + cell['box'][2])/2
                token = cell['text']
                if abs(cell_center - center) < 28 and re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', token):
                    value = float(token.replace(',', ''))
                    if math.isfinite(value) and 0 <= value <= 1_000_000:
                        values[name] = value
                    else:
                        reasons.append(f'{name}: value outside review limits; left blank.')
                else:
                    reasons.append(f'{name}: unreadable or misaligned cell; left blank.')
        else:
            reasons.append('Unsupported or ambiguous header/row; flows left blank.')
        relevant = table['heading'] + (header or []) + row
        confidence = [w['confidence'] for w in relevant if w['confidence'] is not None]
        if confidence and min(confidence) < 80:
            values = {}
            reasons.append('Low OCR confidence in tag, header or value; flows left blank.')
        result.append({'tag': tag, 'kind': 'kitchen_hood', 'review_values': values,
                       'values': {}, 'status': 'UNVERIFIED', 'include': False,
                       'source': source, 'page': page, 'method': method,
                       'coordinate_space': 'displayed_pdf_points',
                       'confidence_min': min(confidence) if confidence else None,
                       'evidence': relevant, 'review_reasons': reasons})
    return result


def extract_local(data, source='synthetic.pdf', budget=Budget(), engine=tesseract_words, retain_words=True):
    """Native and OCR streams stay separate; no conflict suppression or autoaccept.

    Raster-containing pages get OCR even when native text is plentiful. Sparse
    vector pages get OCR too. Full-page OCR is intentional for mixed content.
    """
    import pymupdf
    if len(data) > budget.max_pdf_bytes:
        raise ValueError('PDF byte budget exceeded')
    if min(budget.max_pages, budget.max_pixels, budget.max_total_pixels, budget.dpi,
           budget.per_page_seconds, budget.total_seconds, budget.max_words) <= 0:
        raise ValueError('Budgets must be positive')
    started = time.monotonic()
    report = {'review_candidates': [], 'pages': [], 'warnings': [], 'complete_takeoff': False}
    attempted = total_pixels = 0
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if doc.needs_pass:
            raise ValueError('Encrypted PDF requires an unlocked copy')
        if len(doc) > 300:
            raise ValueError('PDF has more than 300 pages')
        for number, page in enumerate(doc, 1):
            native = [word(*w[:5]) for w in page.get_text('words')]
            if len(native) > budget.max_words:
                report['warnings'].append(f'Page {number}: native word budget exceeded; review manually.')
                continue
            # Native coordinates are unrotated; transform to displayed orientation.
            for w in native:
                w['box'] = list(pymupdf.Rect(w['box']) * page.rotation_matrix)
            entry = {'page': number, 'ocr_status': 'not_needed'}
            if retain_words:
                entry.update(native_words=native, ocr_words=[])
            report['pages'].append(entry)
            report['review_candidates'].extend(hood_candidates(native, source, number, 'native'))
            needs_ocr = bool(page.get_image_info()) or sum(len(w['text']) for w in native) < 40
            if not needs_ocr:
                continue
            remaining = budget.total_seconds - (time.monotonic() - started)
            pixels = min(budget.max_pixels, math.ceil(page.rect.width * page.rect.height * (budget.dpi/72)**2))
            if attempted >= budget.max_pages or total_pixels + pixels > budget.max_total_pixels or remaining <= 0:
                entry['ocr_status'] = 'budget_skipped'
                report['warnings'].append(f'Page {number}: OCR budget exhausted; manual review required.')
                continue
            attempted += 1
            total_pixels += pixels
            try:
                ocr = engine(page, pixels, min(remaining, budget.per_page_seconds))
                if len(ocr) > budget.max_words:
                    raise ValueError('OCR word budget exceeded')
                if retain_words:
                    entry['ocr_words'] = ocr
                report['review_candidates'].extend(diffuser_candidates(ocr, source, number))
                entry['ocr_status'] = 'review_required' if ocr else 'no_text'
                report['review_candidates'].extend(hood_candidates(ocr, source, number, 'ocr'))
                report['warnings'].append(f'Page {number}: OCR is unverified and may miss or misread content; review the original.')
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                entry['ocr_status'] = 'failed'
                report['warnings'].append(f'Page {number}: OCR failed ({type(exc).__name__}); manual review required.')
    report['ocr_attempted_pages'] = attempted
    if len(report['review_candidates']) > 500:
        raise ValueError('Too many OCR review candidates; split source documents')
    return report


def diffuser_candidates(words, source, page):
    """Use existing conservative geometry readers, without guessing associations."""
    from abp_schedule import parse_supply_outlets
    from abp_mechanical import keyed_outlets
    if not words:
        return []
    tuples = [(*w['box'], w['text'], 0, 0, 0) for w in words]
    found = parse_supply_outlets(tuples, page, source) + keyed_outlets(tuples, page, source, {})
    result = []
    for item in found:
        values = {'design_cfm': item['design_cfm']} if item.get('design_cfm') is not None else {}
        # Page-wide threshold is intentionally conservative until per-symbol linkage exists.
        if any(w['confidence'] is None or w['confidence'] < 80 for w in words):
            values = {}
        result.append({'kind': 'diffuser', 'tag': '', 'values': {}, 'review_values': values,
                       'status': 'UNVERIFIED', 'include': False, 'source': source, 'page': page,
                       'method': 'ocr', 'type': item.get('type', ''), 'size': item.get('size', ''),
                       'evidence_text': item.get('evidence', '') + ('; page position (points): ' + str(item['position']) if item.get('position') else ''),
                       'position': item.get('position'),
                       'review_reasons': ['Confirm device, size, airflow, duct connection and room in the original drawing.']})
    return result


# Limit concurrent OCR jobs in this service process. Fail clearly rather than queue indefinitely.
import threading
_OCR_SLOT = threading.BoundedSemaphore(1)


def extract(data, source='source.pdf', timeout=65, *, path=None):
    """Run all OCR parsing/rendering in a memory/CPU/wall-clock bounded process.

    Return a compact review-only queue, never native/OCR words to normal parsers.
    Linux resource controls are mandatory; unsupported hosts fail closed.
    """
    import json
    import os
    import signal
    import sys
    if (Path(path).stat().st_size if path is not None else len(data)) > Budget().max_pdf_bytes:
        return {'review_candidates': [], 'warnings': [source + ': OCR input exceeds 40 MB; manual image review required.']}
    if os.name != 'posix' or not _OCR_SLOT.acquire(blocking=False):
        return {'review_candidates': [], 'warnings': [source + ': OCR unavailable or busy; rescan later or review images manually.']}
    try:
        with tempfile.TemporaryDirectory(prefix='abp-ocr-job-', dir=os.environ.get('ABP_SCAN_TMPDIR')) as directory:
            root = Path(directory)
            from abp_limits import mark_staging
            mark_staging(root)
            if path is not None:
                import shutil
                shutil.copyfile(path, root / 'source.pdf')
            else:
                (root / 'source.pdf').write_bytes(data)
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(root)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True,
                                     # Keep page rasters/TSV files inside the parent's cleanup
                                     # scope even if the worker is terminated with SIGKILL.
                                     env={'PATH':os.defpath, 'HOME':directory, 'LANG':'C.UTF-8',
                                          'ABP_PARENT_PID':str(os.getpid()), 'OMP_THREAD_LIMIT': '1',
                                          'TMPDIR': directory, 'TEMP': directory, 'TMP': directory})
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise ValueError('OCR time limit reached')
            finally:
                # Clean up any descendant recognizer even if worker crashes.
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            output = root / 'result.json'
            if child.returncode or not output.exists() or output.stat().st_size > 2_000_000:
                raise ValueError('OCR worker failed or exceeded limits')
            report = json.loads(output.read_text())
            for item in report['review_candidates']:
                item['source'] = source
            report['warnings'] = [source + ': ' + message for message in report['warnings']]
            return report
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'review_candidates': [], 'warnings': [source + ': bounded OCR failed; review images manually.']}
    finally:
        _OCR_SLOT.release()


def _worker(directory):
    import json
    import resource
    from abp_limits import bind_to_parent
    bind_to_parent(os.environ['ABP_PARENT_PID'])
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (48 * 1024**2, 48 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    root = Path(directory)
    report = extract_local((root / 'source.pdf').read_bytes(), source='uploaded PDF', retain_words=False)
    compact = {'review_candidates': report['review_candidates'], 'warnings': report['warnings'],
               'ocr_attempted_pages': report['ocr_attempted_pages'], 'complete_takeoff': False}
    for item in compact['review_candidates']:
        if 'evidence' in item:
            item['evidence_text'] = ' '.join(w['text'] for w in item['evidence'])[:1000]
            item['evidence_boxes'] = [w['box'] for w in item.pop('evidence')][:100]
    encoded = json.dumps(compact, allow_nan=False)
    if len(encoded.encode()) > 2_000_000:
        raise ValueError('Review response exceeds budget')
    (root / 'result.json').write_text(encoded)


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        _worker(sys.argv[2])
