"""Bounded raster-region selection and conservative, review-only hood tables.

The selector is geometric, not a completeness check. It uses only the standard
library and PyMuPDF so it fits the existing isolated worker's address-space cap.
"""
import math
import re
import statistics
import time


def render_geometry(rect, max_pixels, max_zoom):
    """Conservative pixel estimate, including fractional clip raster rounding."""
    if rect.is_empty or rect.is_infinite or rect.get_area() <= 0:
        raise ValueError('Invalid raster rectangle')
    scale = min(max_zoom, math.sqrt(max_pixels / rect.get_area()))
    for _ in range(8):
        pixels = (math.ceil(rect.width * scale) + 2) * (math.ceil(rect.height * scale) + 2)
        if pixels <= max_pixels:
            return scale, pixels
        scale *= math.sqrt(max_pixels / pixels) * .999
    raise ValueError('Raster budget too small')


def raster_regions(page, native_count, limit=48):
    """Only skip small top/bottom marginal images on native-rich pages.

    Skipping is a visible heuristic, not a declaration that an image is a logo.
    All other raster content remains eligible, including mixed-content pages.
    """
    import pymupdf
    out = []
    images = page.get_image_info()
    for item in images[:limit]:
        box = (pymupdf.Rect(item['bbox']) * page.rotation_matrix) & page.rect
        if box.is_empty or box.is_infinite:
            continue
        fraction = box.get_area() / page.rect.get_area()
        marginal = box.y1 < page.rect.y0 + page.rect.height * .12 or box.y0 > page.rect.y0 + page.rect.height * .9
        skipped = native_count >= 50 and marginal and fraction < .015
        out.append({'box': list(box), 'status': 'small_marginal_image_skipped' if skipped else 'raster_unexamined',
                    'reason': 'Small marginal image on native-rich page; verify manually.' if skipped else 'Raster content requires review.'})
    return out, len(images) > limit


def ruled_regions(page, max_pixels=6_000_000, max_regions=12, deadline=None):
    """Find bounded ruled rectangles from a grayscale preview in displayed points.

    Returns (boxes, estimated pixels, truncated). A truncated preview never
    claims there were no tables. Line, edge, region and time budgets bound work.
    """
    import pymupdf
    scale, cost = render_geometry(page.rect, max_pixels, 1.)
    pix = None
    try:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, alpha=False)
        width, height, ox, oy = pix.width, pix.height, pix.x, pix.y
        if width * height > cost:
            raise ValueError('Preview raster budget exceeded')
        # bytes.translate and regex scan in C; no NumPy import or page-sized lists.
        pixels = pix.samples.translate(bytes([1 if x < 150 else 0 for x in range(256)]))
    finally:
        pix = None
        pymupdf.TOOLS.store_shrink(100)
    pattern = re.compile(b'\x01{' + str(max(1, math.ceil(max(250 * scale, width * .1)))).encode() + b',}')
    horizontal = []
    truncated = False
    for y in range(height):
        if y % 32 == 0 and deadline is not None and time.monotonic() >= deadline:
            return [], cost, True
        for match in pattern.finditer(pixels[y * width:(y + 1) * width]):
            horizontal.append((y, match.start(), match.end()))
            if len(horizontal) >= 2048:
                truncated = True
                break
        if truncated:
            break
    columns = {}
    boxes = []
    for y, x, z in horizontal:
        if deadline is not None and time.monotonic() >= deadline:
            truncated = True
            break
        spans = []
        for edge in (x, z - 1):
            if edge not in columns:
                if len(columns) >= 256:
                    truncated = True
                    break
                stripes = [pixels[c::width] for c in range(max(0, edge - 2), min(width, edge + 3))]
                column = bytearray(any(bits) for bits in zip(*stripes))
                # Close only one/two-pixel interior gaps, as for thin scan rules.
                for match in re.finditer(b'\x00{1,2}', column):
                    lo, hi = match.span()
                    if lo > 0 and hi < height and column[lo - 1] and column[hi]:
                        column[lo:hi] = b'\x01' * (hi - lo)
                columns[edge] = [m.span() for m in re.finditer(b'\x01+', column)]
            spans.append(next((s for s in columns[edge] if s[0] <= y < s[1]), (y, y)))
        if len(spans) != 2:
            break
        top, bottom = max(s[0] for s in spans), min(s[1] for s in spans)
        if not 35 * scale <= bottom - top <= 500 * scale:
            continue
        if abs(spans[0][0] - spans[1][0]) > 6 * scale or abs(spans[0][1] - spans[1][1]) > 6 * scale:
            continue
        # Include a heading above the ruled border. Use actual pixmap origin.
        box = [max(page.rect.x0, (ox + x - 6) / scale),
               max(page.rect.y0, (oy + top - 28 * scale) / scale),
               min(page.rect.x1, (ox + z + 6) / scale),
               min(page.rect.y1, (oy + bottom + 6) / scale)]
        if any(all(abs(v - w) < 10 for v, w in zip(box, other)) for other in boxes):
            continue
        if len(boxes) >= max_regions:
            truncated = True
            break
        boxes.append(box)
    # Interior header cells and column groups share the table's ruled edges.
    # OCR the enclosing table once, preserving its tag column and heading,
    # rather than spending the region budget on the same schedule repeatedly.
    outer = [b for b in boxes if not any(b != other and
             other[0] <= b[0] + 2 and other[1] <= b[1] + 2 and
             other[2] >= b[2] - 2 and other[3] >= b[3] - 2 and
             (other[2]-other[0])*(other[3]-other[1]) > (b[2]-b[0])*(b[3]-b[1])*1.05
             for other in boxes)]
    return sorted(outer, key=lambda b: (b[1], b[0])), cost, truncated


def _clean(w):
    return w['text'].upper().strip('|{}[] ')


def _cx(w):
    return (w['box'][0] + w['box'][2]) / 2


def _cy(w):
    return (w['box'][1] + w['box'][3]) / 2


def information_parser_limited(words):
    """Bound header combinatorics before geometric matching on hostile pages."""
    from collections import Counter
    counts = Counter(_clean(w) for w in words)
    if not counts['INFORMATION']:
        return False
    return (counts['INFORMATION'] > 20 or counts['HOOD'] > 100 or counts['TOTAL'] > 64 or
            counts['CFM'] > 64 or counts['SUPPLY'] > 64 or counts['EXH'] + counts['EXHAUST'] > 64)


def hood_information_candidates(words, source, page, method):
    """Recognize explicit multirow TOTAL EXH/SUPPLY CFM, never computed flow.

    Each field needs unique header and value geometry. Confidence is evaluated
    separately for each field, including the title and identity. Unsupported or
    uncertain values remain blank with their printed evidence available.
    """
    words = [w for w in words if w['text'].strip() and w['box'][3] > w['box'][1]]
    if not words or information_parser_limited(words):
        return []
    scale = statistics.median(w['box'][3] - w['box'][1] for w in words)
    headings = []
    hood_words = [w for w in words if _clean(w) == 'HOOD']
    for info in (w for w in words if _clean(w) == 'INFORMATION'):
        hoods = [h for h in hood_words if abs(_cy(h) - _cy(info)) < scale
                 and 0 <= info['box'][0] - h['box'][2] < scale * 4]
        if len(hoods) == 1:
            headings.append([hoods[0], info])
    results = []
    number_pattern = r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?'
    for heading in headings[:20]:
        top = max(w['box'][3] for w in heading)
        bottom = min((w['box'][1] for w in words if w['box'][1] > top + scale and
                      _clean(w) in {'SCHEDULE', 'INFORMATION'}), default=top + min(600, scale * 80))
        block = [w for w in words if top < _cy(w) < bottom]
        if any(_clean(w) in {'ACTUAL', 'MEASURED', 'INITIAL', 'FINAL'} for w in block):
            continue
        tags = [w for w in block if re.fullmatch(r'(?:HD|KH|KEH|HOOD|H)-\d+(?:\.\d+)*[A-Z]?', _clean(w))]
        totals = [w for w in block if _clean(w) == 'TOTAL']
        cfms = [w for w in block if _clean(w) == 'CFM']
        fields = {}
        for name, labels in [('exhaust_cfm', {'EXH', 'EXHAUST'}), ('supply_cfm', {'SUPPLY'})]:
            anchors = []
            for label in block:
                if _clean(label) not in labels:
                    continue
                for total in totals:
                    if not (0 < _cy(label) - _cy(total) < scale * 4 and abs(_cx(total) - _cx(label)) < scale * 3):
                        continue
                    for cfm in cfms:
                        same_line = abs(_cy(cfm) - _cy(label)) < scale and 0 <= cfm['box'][0] - label['box'][2] < scale * 2
                        below = 0 < _cy(cfm) - _cy(label) < scale * 3 and abs(_cx(cfm) - _cx(label)) < scale * 2
                        if same_line or below:
                            anchors.append((_cx(total), [total, label, cfm]))
            if len(anchors) == 1:
                fields[name] = anchors[0]
        for tag in tags[:100]:
            values, field_evidence, evidence = {}, {}, heading + [tag]
            reasons = ['Confirm hood identity and each design airflow against source.']
            for name in ('exhaust_cfm', 'supply_cfm'):
                if name not in fields:
                    reasons.append(name + ': missing or ambiguous TOTAL/CFM header; left blank.')
                    continue
                x, anchors = fields[name]
                if max(w['box'][3] for w in anchors) >= _cy(tag) or x <= _cx(tag):
                    reasons.append(name + ': misaligned header or row; left blank.')
                    continue
                choices = [w for w in block if re.fullmatch(number_pattern, _clean(w)) and
                           abs(_cx(w) - x) < scale * 2 and abs(_cy(w) - _cy(tag)) < scale]
                evidence.extend(anchors)
                if len(choices) != 1:
                    reasons.append(name + ': ambiguous or missing value; left blank.')
                    continue
                value = choices[0]
                relevant = heading + [tag] + anchors + [value]
                known = [w['confidence'] for w in relevant if w.get('confidence') is not None]
                confidence = min(known) if known else None
                evidence.append(value)
                field_evidence[name] = {'printed_text': value['text'][:50], 'confidence_min': confidence,
                                        'boxes': [w['box'] for w in relevant]}
                number = float(_clean(value).replace(',', ''))
                if not math.isfinite(number) or not 0 <= number <= 1_000_000:
                    reasons.append(name + ': value outside review limits; left blank.')
                elif (confidence is not None and confidence < 80) or (method == 'ocr' and len(known) != len(relevant)):
                    reasons.append(name + ': low or unavailable confidence in title, tag, header or value; numeric field withheld.')
                else:
                    values[name] = number
            confidence = [w['confidence'] for w in evidence if w.get('confidence') is not None]
            results.append({'tag': _clean(tag), 'kind': 'kitchen_hood', 'values': {}, 'review_values': values,
                            'status': 'UNVERIFIED', 'include': False, 'source': source, 'page': page,
                            'method': method, 'coordinate_space': 'displayed_pdf_points',
                            'confidence_min': min(confidence) if confidence else None,
                            'evidence': evidence, 'field_evidence': field_evidence, 'review_reasons': reasons})
    return results
