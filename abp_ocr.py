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
from abp_ocr_regions import render_geometry, raster_regions, ruled_regions, hood_information_candidates, information_parser_limited, complete_raster_tables, circle_regions
from abp_ocr_candidates import merge_diffuser_candidate
from abp_plan_regions import paired_text_regions
from abp_keynotes import keynote_regions, keynote_candidates
from abp_ocr_batch import tesseract_batch_words


@dataclass(frozen=True)
class Budget:
    max_pages: int = 12
    max_pixels: int = 8_000_000
    max_total_pixels: int = 40_000_000
    dpi: int = 180
    per_page_seconds: float = 35
    total_seconds: float = 60
    max_words: int = 30_000
    max_pdf_bytes: int = 40_000_000
    max_preview_pixels: int = 6_000_000
    max_region_pixels: int = 2_000_000
    max_page_pixels: int = 16_000_000
    max_regions: int = 64
    max_regions_per_page: int = 48
    max_detected_regions: int = 12
    max_coverage_regions: int = 240
    region_dpi: int = 216
    callout_dpi: int = 288


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
        # SERVES references in another unit's schedule are not equipment rows.
        if item.get('basis')=='PLAN_TAG':continue
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


def prioritized_pages(doc, page_numbers, deadline):
    """Read title-block schedule sheets before spending OCR time on plans.

    This is an ordering hint, never evidence of complete coverage. Only native
    words are inspected, at most 300 pages, inside the existing wall deadline.
    All selected pages remain in the queue when the hint budget is exhausted.
    """
    import pymupdf
    numbers=[i for i in range(len(doc)) if page_numbers is None or i+1 in page_numbers]
    priorities={}
    for i in numbers:
        if time.monotonic()>=deadline:break
        words=doc[i].get_text('words')
        if len(words)<=30_000 and any(re.fullmatch(r'SCHEDULES?',w[4].strip(' .:;'),re.I) for w in words):
            priorities[i]=0
        pymupdf.TOOLS.store_shrink(100)
    return sorted(numbers,key=lambda i:(priorities.get(i,1),i))


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
                  region_engine=None, selector=None, page_numbers=None, checkpoint=None, batch_engine=None):
    """Native and OCR candidates remain separate and unverified.

    Inspect bounded previews for ruled raster tables, then OCR selected crops.
    Preserve full-page PSM6 fallback for small/unruled content. Skipped images,
    budgets, and all areas outside the crops stay explicit in compact coverage.
    """
    import pymupdf
    region_engine = region_engine or tesseract_region_words
    if batch_engine is None and region_engine is tesseract_region_words:batch_engine=tesseract_batch_words
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
        ordered_pages=prioritized_pages(doc,page_numbers,started+budget.total_seconds)
        for page_offset,index in enumerate(ordered_pages):
            number, page = index+1,doc[index]
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
            from abp_outlets import plan_context, centered_outlets
            from abp_mechanical import page_words
            displayed_words=page_words(page)
            plan_page=plan_context(displayed_words) or bool(re.search(r'(?:FLOOR|CEILING)[ _-]+PLAN',source,re.I))
            # Native callouts do not prove that every device has extractable
            # text: CAD plans commonly mix native labels and outlined glyphs.
            plan_tiles=plan_page
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
            if not eligible and not image_overflow and not sparse and not plan_tiles:
                if images:
                    coverage['status'] = 'small_marginal_images_skipped'
                    coverage['unexamined_content'] = 'Small marginal images were not OCR-read; verify manually.'
                continue
            page_started=time.monotonic()
            page_deadline = min(started + budget.total_seconds, page_started + budget.per_page_seconds)
            page_pixels = page_regions = 0
            page_attempted = False

            def available(pixels):
                return (time.monotonic() < page_deadline and total_pixels + pixels <= budget.max_total_pixels
                        and page_pixels + pixels <= budget.max_page_pixels)

            def consume(pixels):
                nonlocal total_pixels, page_pixels
                total_pixels += pixels
                page_pixels += pixels

            def recognize(rect, psm, full_page=False, word_sink=None, table=False, callout=False,
                          glyph=False, parse_candidates=True, pending=None):
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
                zoom=(budget.dpi if full_page else budget.callout_dpi if callout else budget.region_dpi)/72
                if glyph:zoom=min(5.,zoom*1.25)
                _, pixels = render_geometry(rect, max_pixels, zoom)
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
                                         max_zoom=zoom))
                    if len(ocr) > budget.max_words:
                        raise ValueError('OCR word budget exceeded')
                    if table and psm==11:
                        # Re-read uncertain printed IDs in isolation. Only an
                        # exact repeat can strengthen confidence; no digit repair.
                        from abp_mechanical import TAG
                        targets=[w for w in ocr if re.fullmatch(TAG,w['text'],re.I)
                                 and (w.get('confidence') or 0)<80][:2]
                        for original in targets:
                            refined=[]
                            recognize(pymupdf.Rect(original['box'])+(-1,-1,1,1),7,word_sink=refined)
                            if len(refined)==1 and refined[0]['text'].upper()==original['text'].upper() and (refined[0].get('confidence') or 0)>=80:
                                original['original_confidence']=original.get('confidence')
                                original['confidence']=refined[0]['confidence']
                                original['confidence_method']='exact_token_reread'
                    if retain_words:
                        entry['ocr_words'].extend(ocr)
                    if word_sink is not None:word_sink.extend(ocr)
                    parser_limited = information_parser_limited(ocr)
                    if parser_limited:
                        report['warnings'].append(f'Page {number}: hood header-complexity budget exceeded; manual review required.')
                    candidates = (hood_candidates(ocr, source, number, 'ocr') + equipment_candidates(ocr,source,number,'ocr')) if parse_candidates else []
                    if parse_candidates and (full_page or plan_tiles):
                        candidates = diffuser_candidates(ocr, source, number, plan_confirmed=plan_page) + candidates
                    for candidate in candidates:
                        candidate['region'] = list(rect)
                        candidate['region_coordinate_space'] = 'displayed_pdf_points'
                    for candidate in candidates:
                        # Overlapping plan tiles must not create duplicate physical outlets.
                        if merge_diffuser_candidate(report['review_candidates'],candidate):continue
                        if candidate.get('kind')=='equipment' and any(
                            old.get('kind')=='equipment' and old.get('page')==number and old.get('source')==source
                            and old.get('tag')==candidate.get('tag') and old.get('region')==candidate.get('region')
                            and old.get('review_values')==candidate.get('review_values')
                            for old in report['review_candidates']):continue
                        report['review_candidates'].append(candidate)
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
                    if pending is not None:pending['status']=r['status']
                    # A wide schedule may outlast the source allowance. Save
                    # each completed region atomically rather than losing its
                    # candidates while waiting for the whole page to finish.
                    if page_attempted:
                        coverage['status'] = 'partial_review_required'
                        if checkpoint:checkpoint(report)

            def read_small_crops(pending_jobs,psm,*,word_sink=None,glyph=False,parse=True):
                """Checkpoint bounded groups; preserve earlier groups on failure."""
                nonlocal attempted,regions_attempted,page_regions,page_attempted
                if batch_engine is None:
                    for pending in pending_jobs:
                        _,r=recognize(pymupdf.Rect(pending.get('crop',pending['box'])),psm,callout=True,
                                      glyph=glyph,word_sink=word_sink,parse_candidates=parse,pending=pending)
                        pending['status']=r['status'];statuses.append(r['status'])
                    return
                zoom=budget.callout_dpi/72*(1.25 if glyph else 1)
                for start in range(0,len(pending_jobs),8):
                    jobs=[];reserved=[]
                    for pending in pending_jobs[start:start+8]:
                        rect=pymupdf.Rect(pending.get('crop',pending['box']))
                        allowance=min(budget.max_pixels,budget.max_region_pixels,
                                      budget.max_total_pixels-total_pixels,budget.max_page_pixels-page_pixels)
                        pixels=render_geometry(rect,allowance,zoom)[1] if allowance>=10000 else 0
                        r={'box':list(rect),'method':f'ocr_batch_psm{psm}','status':'budget_skipped','pixels':pixels}
                        record_region(coverage,r)
                        if not pixels or not available(pixels) or regions_attempted>=budget.max_regions or page_regions>=budget.max_regions_per_page:
                            r['reason']='Pixel, region or time budget exhausted; manual review required.'
                            pending['status']=r['status'];statuses.append(r['status']);continue
                        consume(pixels);regions_attempted+=1;page_regions+=1
                        if not page_attempted:page_attempted=True;attempted+=1
                        jobs.append({'box':list(rect),'pixels':pixels});reserved.append((pending,r))
                    if not jobs:continue
                    batch_started=time.monotonic()
                    try:
                        outputs=batch_engine(page,jobs,max(.001,page_deadline-time.monotonic()),psm=psm,
                                             max_zoom=zoom,max_total_pixels=sum(j['pixels'] for j in jobs))
                        if len(outputs)!=len(jobs):raise ValueError('OCR batch lost crop identities')
                        if sum(len(words) for words in outputs)>budget.max_words:raise ValueError('OCR batch word budget exceeded')
                        for (pending,r),words in zip(reserved,outputs):
                            if retain_words:entry['ocr_words'].extend(words)
                            if word_sink is not None:
                                if len(word_sink)+len(words)>budget.max_words:raise ValueError('OCR evidence word budget exceeded')
                                word_sink.extend(words)
                            candidates=diffuser_candidates(words,source,number,plan_confirmed=True) if parse else []
                            for candidate in candidates:
                                candidate['region']=r['box'];candidate['region_coordinate_space']='displayed_pdf_points'
                                if not merge_diffuser_candidate(report['review_candidates'],candidate):report['review_candidates'].append(candidate)
                            r['status']='review_candidate' if candidates else ('no_supported_table_recognized' if words else 'no_text')
                            r['candidate_count']=len(candidates);pending['status']=r['status'];statuses.append(r['status'])
                    except (OSError,ValueError,RuntimeError,MemoryError,subprocess.SubprocessError) as exc:
                        report['warnings'].append(f'Page {number}: OCR batch failed ({type(exc).__name__}); unfinished crops require review.')
                        for pending,r in reserved:
                            if pending['status']=='not_examined':
                                r['status']=pending['status']='failed';r['reason']=type(exc).__name__
                                statuses.append('failed')
                    finally:
                        coverage['status']='partial_review_required'
                        coverage.setdefault('batches',[]).append({'regions':len(jobs),'psm':psm,
                            'elapsed_seconds':round(time.monotonic()-batch_started,3)})
                        if checkpoint:checkpoint(report)

            if raster_pages >= budget.max_pages or not available(1):
                entry['ocr_status'] = coverage['status'] = 'budget_skipped'
                coverage['unexamined_content'] = 'Raster content not examined; manual review required.'
                report['warnings'].append(f'Page {number}: OCR budget exhausted; manual review required.')
                continue
            raster_pages += 1
            boxes = []
            preview_failed = False
            try:
                # Plan tiles do not use table selection; neither render nor
                # charge a full-page table preview for this path.
                preview_pixels = 0
                if not plan_tiles:
                    _, preview_pixels = render_geometry(page.rect, min(budget.max_preview_pixels, budget.max_pixels), 1.)
                if not available(preview_pixels):
                    entry['ocr_status'] = coverage['status'] = 'budget_skipped'
                    report['warnings'].append(f'Page {number}: preview pixel/time budget exhausted; manual review required.')
                    coverage['unexamined_content'] = 'Raster content not examined; manual review required.'
                    continue
                consume(preview_pixels)
                boxes, _, truncated = ([], 0, False) if plan_tiles else selector(page, max_pixels=min(budget.max_preview_pixels, budget.max_pixels),
                                               max_regions=budget.max_detected_regions, deadline=page_deadline)
                boxes=complete_raster_tables(boxes,images,page.rect)
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
            if plan_tiles:
                # Small paired CAD text crops retain readable glyphs at high
                # resolution without rasterizing most of an engineering sheet.
                # Geometry selects crops only; the existing literal readers and
                # confidence checks still determine candidate values.
                try:
                    callouts,limited=paired_text_regions(page,deadline=page_deadline)
                except (OSError,ValueError,RuntimeError,MemoryError) as exc:
                    callouts,limited=[],True
                    coverage['callout_selection_failed']=type(exc).__name__
                coverage['callout_selection_truncated']=limited
                coverage['planned_callout_regions']=[{'box':box,'status':'not_examined'} for box in callouts]
                coverage['unexamined_content']='Plan crops may omit symbols, rooms and duct connections; review every source page.'
                coverage['selection']='plan_tiles'
                rect=page.rect; nx,ny=(3,2) if rect.width>=rect.height else (2,3)
                tiles=[]
                for x in range(nx):
                    for y in range(ny):
                        tile=pymupdf.Rect(max(rect.x0,rect.x0+x*rect.width/nx-24),max(rect.y0,rect.y0+y*rect.height/ny-24),
                                          min(rect.x1,rect.x0+(x+1)*rect.width/nx+24),min(rect.y1,rect.y0+(y+1)*rect.height/ny+24))
                        tiles.append({'box':list(tile),'status':'not_examined'})
                coverage['planned_tiles']=tiles
                try:
                    markers,notes,key_limited=keynote_regions(page,deadline=page_deadline)
                except (OSError,ValueError,RuntimeError,MemoryError) as exc:
                    markers,notes,key_limited=[],[],True
                    coverage['keynote_selection_failed']=type(exc).__name__
                coverage['keynote_selection_truncated']=key_limited
                coverage['planned_keynote_regions']=[{'box':b,'status':'not_examined'} for b in notes]
                coverage['planned_keynote_markers']=[{'box':b,'status':'not_examined'} for b in markers] if notes else []
                # Save the whole pending queue before recognition: a worker
                # timeout must not make the unvisited bottom of a plan vanish.
                if checkpoint:checkpoint(report)
                read_small_crops(coverage['planned_callout_regions'],6)
                note_words=[]
                read_small_crops(coverage['planned_keynote_regions'],6,word_sink=note_words,parse=False)
                # An identical isolated reread can confirm a low-confidence
                # literal airflow. Never replace misread characters or digits.
                for original in [w for w in note_words if re.fullmatch(r'\d{1,4}CFM',w['text'],re.I)
                                 and (w.get('confidence') or 0)<80][:4]:
                    refined=[]
                    _,r=recognize(pymupdf.Rect(original['box'])+(-1,-1,1,1),7,callout=True,
                                  word_sink=refined,parse_candidates=False)
                    statuses.append(r['status'])
                    if len(refined)==1 and refined[0]['text'].upper()==original['text'].upper() and (refined[0].get('confidence') or 0)>=80:
                        original['original_confidence']=original.get('confidence')
                        original['confidence']=refined[0]['confidence']
                        original['confidence_method']='exact_token_reread'
                for pending in coverage['planned_keynote_markers']:
                    b=pymupdf.Rect(pending['box']);w,h=b.width,b.height
                    pending['crop']=[b.x0+w*.25,b.y0+h*.2,b.x1-w*.25,b.y1-h*.08]
                read_small_crops(coverage['planned_keynote_markers'],10,word_sink=note_words,glyph=True,parse=False)
                for candidate in keynote_candidates(note_words,markers,notes,source,number,plan_confirmed=True):
                    if not merge_diffuser_candidate(report['review_candidates'],candidate):report['review_candidates'].append(candidate)
                if checkpoint:checkpoint(report)
                # Read the plan before optional circle refinement. Region-count
                # reservations alone do not reserve wall time: decorative
                # circles can otherwise exhaust the deadline before any tile.
                for pending in tiles:
                    _,r=recognize(pymupdf.Rect(pending['box']),11,pending=pending)
                    pending['status']=r['status'];statuses.append(r['status'])
                # Read the inside of a printed circle separately from its flow.
                # Large plan tiles often turn circled A/B marks into @ or omit
                # them. Every recognition still uses the same shared budgets.
                try:
                    circles,limited=circle_regions(page,page_deadline)
                except (OSError, ValueError, RuntimeError, MemoryError) as exc:
                    circles,limited=[],True
                    coverage['circle_selection_failed']=type(exc).__name__
                if limited:
                    coverage['circle_selection_truncated']=True
                    report['warnings'].append(f'Page {number}: symbol selection incomplete; review remaining callouts.')
                for box in circles:
                    rect=pymupdf.Rect(box);inset=rect.width*.20
                    letters=[]
                    _,r=recognize(rect+(inset,inset,-inset,-inset),10,word_sink=letters)
                    statuses.append(r['status'])
                    if len(letters)!=1 or not re.fullmatch(r'[A-Z]',letters[0]['text']) or (letters[0].get('confidence') or 0)<80:continue
                    cx=(rect.x0+rect.x1)/2;flows=[]
                    flow_rect=pymupdf.Rect(cx-rect.width*.70,rect.y1+rect.height*.03,
                                          cx+rect.width*.70,rect.y1+rect.height*.72)&page.rect
                    _,r=recognize(flow_rect,7,word_sink=flows);statuses.append(r['status'])
                    candidate=circle_outlet(letters,flows,source,number,box)
                    if candidate:
                        candidate['region']=list(rect | flow_rect)
                        if not merge_diffuser_candidate(report['review_candidates'],candidate):
                            report['review_candidates'].append(candidate)
                        r['status']='review_candidate';r['candidate_count']=1
            elif boxes:
                coverage['unexamined_content'] = 'All content outside selected table crops; manual review required.'
                retries = []
                # Short tables (often fan/unit schedules) should not wait for
                # a large table to consume the whole page allowance. Every
                # selected crop remains queued and skipped areas stay visible.
                for box in sorted(boxes,key=lambda b:(pymupdf.Rect(b).get_area(),b[1],b[0])):
                    candidates, r = recognize(pymupdf.Rect(box), 11,table=True)
                    statuses.append(r['status'])
                    # Different segmentation only when no supported candidate was
                    # found. Never replace/suppress a low-confidence candidate.
                    if candidates is not None and not any(c.get('review_values') for c in candidates):retries.append((0 if candidates else 1,box))
                # Give every distinct table a first pass before spending the
                # same bounded page budget on alternate segmentation.
                if retries and page_offset+1<len(ordered_pages):
                    coverage['alternate_segmentation_deferred']=True
                    report['warnings'].append(f'Page {number}: optional alternate table reading deferred to give unread source pages a first pass; retry this page if needed.')
                else:
                    for _,box in sorted(retries,key=lambda item:item[0])[:2]:
                        _, fallback = recognize(pymupdf.Rect(box), 6,table=True)
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
            coverage['elapsed_seconds']=round(time.monotonic()-page_started,3)
            if len(report['review_candidates']) > 500:
                raise ValueError('Too many OCR review candidates; split source documents')
    report.update(ocr_attempted_pages=attempted, ocr_regions_attempted=regions_attempted,
                  pixels_processed=total_pixels, raster_pages_attempted=raster_pages)
    if checkpoint:checkpoint(report)
    if len(report['review_candidates']) > 500:
        raise ValueError('Too many OCR review candidates; split source documents')
    return report


def circle_outlet(letters, flows, source, page, box):
    """Unverified source-linked candidate; ambiguous digits remain blank."""
    if len(letters)!=1 or len(flows)!=1:return None
    letter,flow=letters[0],flows[0]
    if not re.fullmatch(r'[A-Z]',letter['text']) or (letter.get('confidence') or 0)<80:return None
    raw=flow['text']
    match=re.fullmatch(r'[|iIjJ{(]?(\d{2,4}|\d{1,2},\d{3})[|})]?',raw)
    if not match or not 10<=int(match[1].replace(',',''))<=10000:return None
    values={}
    if raw==match[1] and (flow.get('confidence') or 0)>=80:values['design_cfm']=int(raw.replace(',',''))
    return {'kind':'diffuser','tag':'','values':{},'review_values':values,
            'status':'UNVERIFIED','include':False,'source':source,'page':page,'method':'ocr',
            'type':letter['text'],'type_confidence':letter.get('confidence'),'size':'',
            'position':[round(letter['box'][0],2),round(letter['box'][1],2)],
            'region':list(box),'region_coordinate_space':'displayed_pdf_points',
            'evidence_text':letter['text']+' / '+raw+'; printed circle and adjacent airflow; confirm in source',
            'review_reasons':['Confirm supply service, design airflow, neck size, room, system and revision.']}


def diffuser_candidates(words, source, page, *, plan_confirmed=False):
    """Use existing conservative geometry readers, without guessing associations."""
    from abp_schedule import parse_supply_outlets
    from abp_mechanical import keyed_outlets
    from abp_outlets import centered_outlets, necked_outlets, coded_outlets, sized_registers, distinct_outlets
    if not words:
        return []
    tuples = [(*w['box'], w['text']) for w in words]
    found = distinct_outlets(parse_supply_outlets(tuples, page, source) + keyed_outlets(tuples, page, source, {})
                            + centered_outlets(tuples,page,source,plan_confirmed=plan_confirmed)
                            + necked_outlets(tuples,page,source,plan_confirmed=plan_confirmed)
                            + coded_outlets(tuples,page,source,plan_confirmed=plan_confirmed)
                            + sized_registers(tuples,page,source,plan_confirmed=plan_confirmed))
    result = []
    for item in found:
        values = {'design_cfm': item['design_cfm']} if item.get('design_cfm') is not None else {}
        # Only a geometrically linked callout can use local confidence. Other
        # readers retain the conservative whole-crop rule until linked evidence exists.
        box=item.get('evidence_box')
        relevant=[w for w in words if not box or (w['box'][0]>=box[0]-.1 and w['box'][1]>=box[1]-.1 and w['box'][2]<=box[2]+.1 and w['box'][3]<=box[3]+.1)]
        if not relevant or any(w['confidence'] is None or w['confidence'] < 80 for w in relevant):
            values = {}
        type_scores=[w.get('confidence') for w in relevant if w['text'].upper()==item.get('type','').upper()]
        result.append({'kind': 'diffuser', 'tag': '', 'values': {}, 'review_values': values,
                       'status': 'UNVERIFIED', 'include': False, 'source': source, 'page': page,
                       'method': 'ocr', 'type': item.get('type', ''), 'size': item.get('size', ''),
                       'type_confidence':min(type_scores) if type_scores and all(v is not None for v in type_scores) else None,
                       'evidence_text': item.get('evidence', '') + ('; page position (points): ' + str(item['position']) if item.get('position') else ''),
                       'position': item.get('position'), 'position_coordinate_space': 'displayed_pdf_points',
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
            (root/'request.json').write_text(json.dumps({'timeout':max(1,timeout-2),'page_numbers':page_numbers,
                                                       'source':str(source)[:255]}),encoding='utf-8')
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
                    report['warnings'].append('Image time budget reached; completed image-region results preserved. Unfinished regions and pages require retry or manual review.')
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
    report = extract_local((root / 'source.pdf').read_bytes(), source=request.get('source','uploaded PDF'), retain_words=False,
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
