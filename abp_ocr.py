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
from abp_ocr_regions import render_geometry, raster_regions, ruled_regions, hood_information_candidates, information_parser_limited


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
    max_preview_pixels: int = 6_000_000
    max_region_pixels: int = 3_000_000
    max_page_pixels: int = 16_000_000
    max_regions: int = 24
    max_regions_per_page: int = 6
    max_detected_regions: int = 12
    max_coverage_regions: int = 240
    region_dpi: int = 216


def word(x, y, x2, y2, text, confidence=None):
    return {'box': [x, y, x2, y2], 'text': text, 'confidence': confidence}


def equipment_candidates(words,source,page,method):
    """Raster schedule values enter only the separate, unverified image queue.

    Keep the native parser's coordinate/header constraints. Any low-confidence
    crop leaves values blank. Measurement/report crops are never design input.
    No image value is fed into native resolution or automatically verified.
    """
    from abp_schedule import parse_page,UNIT_TOTALS
    from abp_design import inferred_form
    text=' '.join(w['text'] for w in words)
    if not re.search(r'\b(?:SCHEDULE|DESIGN|REQUESTED)\b',text,re.I):return []
    if re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|AS FOUND|TEST REPORT|FINAL READING)\b',text,re.I):return []
    if len(words)>30000:return []
    # Normalize printed dash variants and bordering table rules only. Never
    # repair digits or infer a missing identity. Original OCR evidence remains.
    def token(value):return value.translate(str.maketrans({'–':'-','—':'-','−':'-','‐':'-','‑':'-'})).strip('|{}[]')
    tuples=[(*w['box'],token(w['text'])) for w in words]
    confidence={(tuple(w['box']),token(w['text'])):w.get('confidence') for w in words}
    confident=all(w.get('confidence') is not None and w['confidence']>=80 for w in words)
    found=[];seen=set()
    for item in parse_page(tuples,page,source):
        values={k:v for k,v in item.get('values',{}).items() if k in UNIT_TOTALS}
        if item.get('tag') in seen:continue
        seen.add(item['tag'])
        reviewed = {}
        for field,value in values.items():
            evidence=item.get('value_words',{}).get(field,[])
            scores=[confidence.get((tuple(w[:4]),w[4])) for w in evidence]
            if confident or (scores and all(c is not None and c>=80 for c in scores)):
                reviewed[field]=value
        found.append({'kind':'equipment','tag':item['tag'],'source':source,'page':page,
            'method':method,'status':'UNVERIFIED','include':False,
            'review_values':reviewed,'values':{},
            'review_reasons':['Image schedule candidate: compare every value, equipment ID, column heading and source revision.'
                if confident else 'OCR confidence is checked per tag, heading and value; uncertain fields left blank for manual source review.'],
            'template':inferred_form(item['tag'],{'text_proposed':item.get('text',{})}), 'evidence':words[:300],
            'confidence_min':min((w.get('confidence') or 0 for w in words),default=0)})
    return found


def tesseract_region_words(page, pixels, timeout, clip=None, psm=11, max_zoom=3.):
    """OCR a displayed crop, retaining the pixmap's exact fractional origin."""
    import pymupdf
    started = time.monotonic()
    rect = page.rect if clip is None else (pymupdf.Rect(clip) & page.rect)
    zoom, estimate = render_geometry(rect, pixels, max_zoom)
    pix = None
    with tempfile.TemporaryDirectory(prefix='abp-ocr-') as directory:
        source = Path(directory) / 'page.png'
        output = Path(directory) / 'recognized'
        try:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect,
                                  colorspace=pymupdf.csGRAY, alpha=False)
            if pix.width * pix.height > estimate:
                raise ValueError('Raster budget exceeded')
            ox, oy = pix.x, pix.y
            pix.save(str(source))
        finally:
            # MuPDF's decoded image cache otherwise grows across previews/crops.
            pix = None
            pymupdf.TOOLS.store_shrink(100)
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired('render', timeout)
        subprocess.run([sys.executable, str(Path(__file__).with_name('abp_limits.py')), '--exec-with-parent',
                        str(os.getpid()), 'tesseract', str(source), str(output), '-l', 'eng', '--psm', str(psm), 'tsv'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=remaining, check=True)
        tsv = output.with_suffix('.tsv')
        if tsv.stat().st_size > 8_000_000:
            raise ValueError('OCR text budget exceeded')
        result = []
        # Tesseract TSV contains literal inch/double-quote tokens; it does not
        # CSV-escape them. CSV quoting can swallow following rows as one word.
        for row in csv.DictReader(io.StringIO(tsv.read_text(encoding='utf-8')), delimiter='\t', quoting=csv.QUOTE_NONE):
            if row['level'] != '5' or not row['text'].strip():
                continue
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            confidence = float(row['conf'])
            if not math.isfinite(confidence):
                raise ValueError('Invalid OCR confidence')
            result.append(word((ox+x) / zoom, (oy+y) / zoom, (ox+x+w) / zoom, (oy+y+h) / zoom,
                               row['text'], confidence))
            if len(result) > 30_000:
                raise ValueError('OCR word budget exceeded')
        return result


def tesseract_words(page, pixels, timeout):
    """Compatibility full-page PSM6 fallback for small/unruled images and plans."""
    return tesseract_region_words(page, pixels, timeout, psm=6,
                                  max_zoom=math.sqrt(pixels / page.rect.get_area()))


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
    return result + hood_information_candidates(words, source, page, method)


def extract_local(data, source='synthetic.pdf', budget=Budget(), engine=tesseract_words, retain_words=True,
                  region_engine=None, selector=None, page_numbers=None, checkpoint=None):
    """Native and OCR candidates remain separate and unverified.

    Inspect bounded previews for ruled raster tables, then OCR selected crops.
    Preserve full-page PSM6 fallback for small/unruled content. Skipped images,
    budgets, and all areas outside the crops stay explicit in compact coverage.
    """
    import pymupdf
    region_engine = region_engine or tesseract_region_words
    selector = selector or ruled_regions
    if len(data) > budget.max_pdf_bytes:
        raise ValueError('PDF byte budget exceeded')
    if any(not math.isfinite(value) or value <= 0 for value in vars(budget).values()):
        raise ValueError('Budgets must be finite and positive')
    started = time.monotonic()
    report = {'review_candidates': [], 'pages': [], 'coverage': [], 'warnings': [], 'complete_takeoff': False}
    attempted = total_pixels = regions_attempted = raster_pages = coverage_count = 0
    coverage_warning = False

    def record_region(coverage, region):
        nonlocal coverage_count, coverage_warning
        if coverage_count < budget.max_coverage_regions:
            coverage.setdefault('regions', []).append(region)
            coverage_count += 1
        else:
            coverage['regions_omitted'] = coverage.get('regions_omitted', 0) + 1
            if not coverage_warning:
                report['warnings'].append('Coverage region limit reached; omitted areas require manual review.')
                coverage_warning = True

    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if doc.needs_pass:
            raise ValueError('Encrypted PDF requires an unlocked copy')
        if len(doc) > 300:
            raise ValueError('PDF has more than 300 pages')
        for number, page in enumerate(doc, 1):
            if checkpoint:checkpoint(report)
            if page_numbers is not None and number not in page_numbers:continue
            entry = {'page': number, 'ocr_status': 'not_needed'}
            coverage = {'page': number, 'status': 'native_text_only',
                        'unexamined_content': 'Native extraction is not a complete takeoff; verify source.'}
            report['pages'].append(entry)
            report['coverage'].append(coverage)
            native = [word(*w[:5]) for w in page.get_text('words')]
            if len(native) > budget.max_words:
                entry['ocr_status'] = coverage['status'] = 'native_word_budget_skipped'
                report['warnings'].append(f'Page {number}: native word budget exceeded; review manually.')
                pymupdf.TOOLS.store_shrink(100)
                continue
            for w in native:
                w['box'] = list(pymupdf.Rect(w['box']) * page.rotation_matrix)
            if retain_words:
                entry.update(native_words=native, ocr_words=[])
            if information_parser_limited(native):
                coverage['status'] = 'native_parser_limited'
                report['warnings'].append(f'Page {number}: hood header-complexity budget exceeded; manual review required.')
            report['review_candidates'].extend(hood_candidates(native, source, number, 'native'))
            try:
                images, image_overflow = raster_regions(page, len(native))
            finally:
                pymupdf.TOOLS.store_shrink(100)
            eligible = [r for r in images if r['status'] == 'raster_unexamined']
            for region in images:
                record_region(coverage, region)
            if image_overflow:
                report['warnings'].append(f'Page {number}: image region limit reached; unlisted images require manual review.')
                coverage['image_regions_truncated'] = True
            # Title blocks often contain hundreds of native characters while
            # the actual schedules use outlined glyphs, not extractable text.
            native_characters = sum(len(w['text']) for w in native)
            sparse = native_characters < 40 or (page.rect.get_area() > 1_000_000 and native_characters < 500)
            if not eligible and not image_overflow and not sparse:
                if images:
                    coverage['status'] = 'small_marginal_images_skipped'
                    coverage['unexamined_content'] = 'Small marginal images were not OCR-read; verify manually.'
                continue
            page_deadline = min(started + budget.total_seconds, time.monotonic() + budget.per_page_seconds)
            page_pixels = page_regions = 0
            page_attempted = False

            def available(pixels):
                return (time.monotonic() < page_deadline and total_pixels + pixels <= budget.max_total_pixels
                        and page_pixels + pixels <= budget.max_page_pixels)

            def consume(pixels):
                nonlocal total_pixels, page_pixels
                total_pixels += pixels
                page_pixels += pixels

            def recognize(rect, psm, full_page=False):
                nonlocal attempted, regions_attempted, page_regions, page_attempted
                max_pixels = budget.max_pixels if full_page else min(budget.max_pixels, budget.max_region_pixels)
                # Use the remaining pixel allowance for the next table instead
                # of skipping a readable crop merely because its ideal render
                # would exceed the per-page allowance. Caps never increase.
                max_pixels = min(max_pixels,budget.max_total_pixels-total_pixels,budget.max_page_pixels-page_pixels)
                if max_pixels < 10000:
                    r={'box':list(rect),'status':'budget_skipped','method':f'ocr_psm{psm}',
                       'reason':'Pixel budget exhausted; manual review required.'}
                    record_region(coverage,r)
                    return None,r
                _, pixels = render_geometry(rect, max_pixels, (budget.dpi if full_page else budget.region_dpi) / 72)
                r = {'box': list(rect), 'status': 'budget_skipped', 'method': f'ocr_psm{psm}', 'pixels': pixels}
                record_region(coverage, r)
                if not available(pixels) or regions_attempted >= budget.max_regions or page_regions >= budget.max_regions_per_page:
                    r['reason'] = 'Pixel, region or time budget exhausted; manual review required.'
                    return None, r
                consume(pixels)
                regions_attempted += 1
                page_regions += 1
                if not page_attempted:
                    page_attempted = True
                    attempted += 1
                try:
                    remaining = max(.001, page_deadline - time.monotonic())
                    ocr = (engine(page, pixels, remaining) if full_page else
                           region_engine(page, pixels, remaining, clip=list(rect), psm=psm,
                                         max_zoom=budget.region_dpi / 72))
                    if len(ocr) > budget.max_words:
                        raise ValueError('OCR word budget exceeded')
                    if retain_words:
                        entry['ocr_words'].extend(ocr)
                    parser_limited = information_parser_limited(ocr)
                    if parser_limited:
                        report['warnings'].append(f'Page {number}: hood header-complexity budget exceeded; manual review required.')
                    candidates = hood_candidates(ocr, source, number, 'ocr') + equipment_candidates(ocr,source,number,'ocr')
                    if full_page:
                        candidates = diffuser_candidates(ocr, source, number) + candidates
                    for candidate in candidates:
                        candidate['region'] = list(rect)
                        candidate['region_coordinate_space'] = 'displayed_pdf_points'
                    report['review_candidates'].extend(candidates)
                    r['status'] = 'review_candidate' if candidates else ('no_supported_table_recognized' if ocr else 'no_text')
                    if parser_limited:
                        r['parser_limited'] = True
                        r['reason'] = 'Hood header-complexity budget exceeded; manual review required.'
                        if not candidates:
                            r['status'] = 'parser_limited'
                    r['candidate_count'] = len(candidates)
                    return candidates, r
                except (OSError, ValueError, RuntimeError, MemoryError, subprocess.SubprocessError) as exc:
                    r['status'] = 'failed'
                    r['reason'] = type(exc).__name__ + '; manual review required.'
                    report['warnings'].append(f'Page {number}: OCR failed ({type(exc).__name__}); manual review required.')
                    return None, r
                finally:
                    pymupdf.TOOLS.store_shrink(100)

            if raster_pages >= budget.max_pages or not available(1):
                entry['ocr_status'] = coverage['status'] = 'budget_skipped'
                coverage['unexamined_content'] = 'Raster content not examined; manual review required.'
                report['warnings'].append(f'Page {number}: OCR budget exhausted; manual review required.')
                continue
            raster_pages += 1
            boxes = []
            preview_failed = False
            try:
                _, preview_pixels = render_geometry(page.rect, min(budget.max_preview_pixels, budget.max_pixels), 1.)
                if not available(preview_pixels):
                    entry['ocr_status'] = coverage['status'] = 'budget_skipped'
                    report['warnings'].append(f'Page {number}: preview pixel/time budget exhausted; manual review required.')
                    coverage['unexamined_content'] = 'Raster content not examined; manual review required.'
                    continue
                consume(preview_pixels)
                boxes, _, truncated = selector(page, max_pixels=min(budget.max_preview_pixels, budget.max_pixels),
                                               max_regions=budget.max_detected_regions, deadline=page_deadline)
                coverage['preview_pixels'] = preview_pixels
                if truncated:
                    coverage['selection_truncated'] = True
                    report['warnings'].append(f'Page {number}: table-selection budget exhausted; undetected regions require manual review.')
                # A visually ruled schedule need not intersect an embedded
                # bitmap: CAD frequently outlines its text. Raster filtering
                # here discarded real schedules and kept only title blocks.
            except (OSError, ValueError, RuntimeError, MemoryError) as exc:
                preview_failed = True
                coverage['selection_failed'] = type(exc).__name__
                report['warnings'].append(f'Page {number}: table preview failed; bounded full-page fallback attempted if budget permits.')
            finally:
                pymupdf.TOOLS.store_shrink(100)
            statuses = []
            if boxes:
                coverage['unexamined_content'] = 'All content outside selected table crops; manual review required.'
                retries = []
                for box in boxes:
                    candidates, r = recognize(pymupdf.Rect(box), 11)
                    statuses.append(r['status'])
                    # Different segmentation only when no supported candidate was
                    # found. Never replace/suppress a low-confidence candidate.
                    if candidates == []: retries.append(box)
                # Give every distinct table a first pass before spending the
                # same bounded page budget on alternate segmentation.
                for box in retries:
                    _, fallback = recognize(pymupdf.Rect(box), 6)
                    statuses.append(fallback['status'])
            else:
                coverage['unexamined_content'] = 'Full-page OCR may miss content and associations; manual review required.'
                candidates, r = recognize(page.rect, 6, full_page=True)
                statuses.append(r['status'])
                coverage['fallback'] = 'preview_failed' if preview_failed else 'no_ruled_raster_table'
            if statuses and all(s == 'budget_skipped' for s in statuses):
                entry['ocr_status'] = coverage['status'] = 'budget_skipped'
            elif statuses and all(s == 'failed' for s in statuses):
                entry['ocr_status'] = coverage['status'] = 'failed'
            else:
                entry['ocr_status'] = 'review_required' if any(s not in {'no_text', 'failed', 'budget_skipped'} for s in statuses) else 'no_text'
                coverage['status'] = 'partial_review_required'
            if 'budget_skipped' in statuses:
                report['warnings'].append(f'Page {number}: region OCR budget exhausted; skipped areas require manual review.')
            if page_attempted:
                report['warnings'].append(f'Page {number}: OCR is unverified and may miss or misread content; review the original.')
            if len(report['review_candidates']) > 500:
                raise ValueError('Too many OCR review candidates; split source documents')
    report.update(ocr_attempted_pages=attempted, ocr_regions_attempted=regions_attempted,
                  pixels_processed=total_pixels, raster_pages_attempted=raster_pages)
    if checkpoint:checkpoint(report)
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


def extract(data, source='source.pdf', timeout=65, *, path=None, page_numbers=None, progress=None):
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
            if page_numbers is not None and (not page_numbers or len(page_numbers)>300 or any(type(p)!=int or not 1<=p<=300 for p in page_numbers)):
                raise ValueError('Invalid OCR page selection')
            (root/'request.json').write_text(json.dumps({'timeout':max(1,timeout-2),'page_numbers':page_numbers}),encoding='utf-8')
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
                started=time.monotonic(); last=None
                while child.poll() is None:
                    remaining=timeout-(time.monotonic()-started)
                    if remaining<=0:raise subprocess.TimeoutExpired('image reading',timeout)
                    try:child.wait(timeout=min(.5,remaining))
                    except subprocess.TimeoutExpired:pass
                    saved=root/'checkpoint.json'
                    if progress and saved.exists():
                        state=json.loads(saved.read_text(encoding='utf-8')); marker=len(state.get('coverage',[]))
                        if marker!=last:progress({'stage':'images','pages_completed':marker});last=marker
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                saved=root/'checkpoint.json'
                if saved.exists() and saved.stat().st_size<=2_000_000:
                    report=json.loads(saved.read_text(encoding='utf-8'))
                    report['warnings'].append('Image time budget reached; completed page results preserved. Remaining pages require retry or manual review.')
                    report['interrupted']=True
                    for item in report['review_candidates']:item['source']=source
                    return report
                return {'review_candidates':[],'coverage':[],'warnings':[source+': image stage failed to finish within its time budget; no page completed. Retry selected pages.'],'failure_kind':'time_budget'}
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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'review_candidates': [], 'coverage':[], 'warnings': [source + ': image worker failed ('+type(exc).__name__+'); retry selected pages or review manually.'], 'failure_kind':'worker_failure'}
    finally:
        _OCR_SLOT.release()


def _worker(directory):
    import json
    import resource
    from abp_limits import bind_to_parent
    bind_to_parent(os.environ['ABP_PARENT_PID'])
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (48 * 1024**2, 48 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    root = Path(directory)
    request=json.loads((root/'request.json').read_text(encoding='utf-8')) if (root/'request.json').exists() else {}
    def checkpoint(report):
        compact={'review_candidates':[], 'warnings':report['warnings'][-200:],'coverage':report['coverage'], 'complete_takeoff':False}
        for candidate in report['review_candidates']:
            item=dict(candidate)
            if 'evidence' in item:
                item['evidence_text']=' '.join(w['text'] for w in item.pop('evidence'))[:1000]
            compact['review_candidates'].append(item)
        encoded=json.dumps(compact,allow_nan=False).encode()
        if len(encoded)>2_000_000:raise ValueError('Checkpoint response exceeds budget')
        tmp=root/'checkpoint.tmp';tmp.write_bytes(encoded);os.replace(tmp,root/'checkpoint.json')
    report = extract_local((root / 'source.pdf').read_bytes(), source='uploaded PDF', retain_words=False,
                          budget=Budget(total_seconds=request.get('timeout',60)),page_numbers=request.get('page_numbers'),checkpoint=checkpoint)
    compact = {'review_candidates': report['review_candidates'], 'warnings': report['warnings'],
               'ocr_attempted_pages': report['ocr_attempted_pages'], 'complete_takeoff': False,
               'coverage': report['coverage'], 'ocr_regions_attempted': report['ocr_regions_attempted'],
               'pixels_processed': report['pixels_processed']}
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
