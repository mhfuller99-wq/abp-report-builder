"""Bounded, review-only joins between pentagon markers and linear-grille notes.

Coordinates are displayed PDF points. Geometry locates evidence, never a room,
system, neck size, or an approved outlet. The caller owns OCR and all raster,
time and process budgets; this module performs no rendering or OCR itself.
"""
import math
import re
import time


def _center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _inside(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def keynote_regions(page, *, deadline=None, max_paths=20000, max_markers=64,
                    max_note_regions=4):
    """Return (pentagon boxes, candidate note-column boxes, truncated).

    Only compact, closed, convex five-sided vector paths qualify. At least three
    aligned markers are needed to propose a note-column OCR crop; the parser
    separately requires a literal keyed-notes heading and unambiguous note text.
    """
    import pymupdf
    paths = page.get_cdrawings()
    if len(paths) > max_paths:
        return [], [], True
    markers = []
    truncated = False
    for path in paths:
        if deadline is not None and time.monotonic() >= deadline:
            return markers, [], True
        items = path.get('items', [])
        if path.get('fill') is not None or len(items) not in (4, 5) or any(i[0] != 'l' for i in items):
            continue
        points = [tuple(i[1]) for i in items]
        if any(math.dist(items[i][2], items[i + 1][1]) > .25 for i in range(len(items) - 1)):
            continue
        if len(items) == 4:
            if not path.get('closePath'):
                continue
            points.append(tuple(items[-1][2]))
        elif math.dist(items[-1][2], items[0][1]) > .25:
            continue
        lengths = [math.dist(points[i], points[(i + 1) % 5]) for i in range(5)]
        if min(lengths) < 3 or min(lengths) < .65 * max(lengths):
            continue
        crosses = []
        for i in range(5):
            a, b, c = points[i], points[(i + 1) % 5], points[(i + 2) % 5]
            crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
        if not (all(v > .1 for v in crosses) or all(v < -.1 for v in crosses)):
            continue
        # Equal-sided star paths can have same-sign turns, but are not simple
        # pentagons. A convex polygon visits its hull in angular order.
        center = (sum(p[0] for p in points) / 5, sum(p[1] for p in points) / 5)
        order = sorted(range(5), key=lambda i: math.atan2(points[i][1] - center[1], points[i][0] - center[0]))
        steps = {(order[(i + 1) % 5] - order[i]) % 5 for i in range(5)}
        if steps not in ({1}, {4}):
            continue
        box = list(pymupdf.Rect(path['rect']) * page.rotation_matrix)
        width, height = box[2] - box[0], box[3] - box[1]
        if not (7 <= width <= 32 and 7 <= height <= 32 and .75 <= width / height <= 1.35):
            continue
        if any(max(abs(a - b) for a, b in zip(box, old)) < .7 for old in markers):
            continue
        if len(markers) >= max_markers:
            truncated = True
            break
        markers.append(box)
    markers.sort(key=lambda b: (b[1], b[0]))
    regions = []
    used = set()
    for index, box in enumerate(markers):
        if index in used:
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        column = [(j, b) for j, b in enumerate(markers) if j not in used
                  and abs(_center(b)[0] - _center(box)[0]) < width * .2
                  and .8 <= (b[2] - b[0]) / width <= 1.25]
        column.sort(key=lambda item: item[1][1])
        runs = [[]]
        for item in column:
            if runs[-1] and item[1][1] - runs[-1][-1][1][3] > 5 * height:
                runs.append([])
            runs[-1].append(item)
        for run in runs:
            if len(run) < 3:
                continue
            if len(regions) >= max_note_regions:
                return markers, regions, True
            first, last = run[0][1], run[-1][1]
            regions.append([max(page.rect.x0, first[0] - width),
                            max(page.rect.y0, first[1] - 3 * height),
                            min(page.rect.x1, first[2] + 28 * width),
                            min(page.rect.y1, last[3] + 2 * height)])
            used.update(j for j, _ in run)
    return markers, regions, truncated


def _text(word):
    # Strip punctuation only. Never replace OCR letters with digits.
    return word['text'].upper().strip(' \t.,;:()[]{}\"')


def _confident(words, threshold):
    return bool(words) and all(isinstance(w.get('confidence'), (int, float))
                               and math.isfinite(w['confidence'])
                               and w['confidence'] >= threshold for w in words)


def _marker_number(words, box, threshold):
    inside = [w for w in words if _inside(_center(w['box']), box)]
    numbers = [w for w in inside if re.fullmatch(r'[1-9]\d?', _text(w))]
    # Conflicting OCR readings are not resolved by picking the highest score.
    if len({_text(w) for w in numbers}) != 1 or not numbers:
        return None
    if any(re.search(r'\d', _text(w)) and w not in numbers for w in inside):
        return None
    confident = [w for w in numbers if _confident([w], threshold)]
    if not confident:
        return None
    # A tighter crop can confirm the identical token from a coarse crop. A
    # different number was already rejected above, regardless of confidence.
    return _text(numbers[0]), confident


def _lines(words):
    rows = []
    for word in sorted(words, key=lambda w: (w['box'][1], w['box'][0])):
        h = word['box'][3] - word['box'][1]
        if not rows or abs(_center(word['box'])[1] - _center(rows[-1][0]['box'])[1]) > max(2, h * .45):
            rows.append([])
        rows[-1].append(word)
    return [sorted(row, key=lambda w: w['box'][0]) for row in rows]


def _note_details(words):
    rows = _lines(words)
    phrases = []
    for row in rows:
        texts = [_text(w) for w in row]
        for i in range(1, len(texts) - 2):
            if texts[i:i + 3] == ['LINEAR', 'SLOT', 'GRILLE']:
                model = texts[i - 1]
                if re.fullmatch(r'[A-Z0-9][A-Z0-9-]{1,15}', model) and re.search(r'\d', model):
                    phrases.append((model, row[i - 1:i + 3]))
    if len(phrases) != 1:
        return None
    model, phrase_words = phrases[0]
    texts = [_text(w) for row in rows for w in row]
    if model.endswith('R') or any(t in {'RETURN', 'RETURN-AIR', 'RA', 'EXHAUST', 'TRANSFER'} for t in texts):
        return None
    flows = []
    for row in rows:
        for i, word in enumerate(row):
            match = re.fullmatch(r'(\d{1,4}|\d{1,2},\d{3})CFM', _text(word))
            witnesses = [word]
            if match is None and i + 1 < len(row) and _text(row[i + 1]) == 'CFM':
                match = re.fullmatch(r'(\d{1,4}|\d{1,2},\d{3})', _text(word))
                if match and row[i + 1]['box'][0] - word['box'][2] <= 2 * (word['box'][3] - word['box'][1]):
                    witnesses.append(row[i + 1])
                else:
                    match = None
            if match:
                value = int(match[1].replace(',', ''))
                if 1 <= value <= 10000:
                    flows.append((value, witnesses))
    if len(flows) != 1:
        return None
    return model, flows[0][0], phrase_words + flows[0][1]


def keynote_candidates(words, marker_boxes, note_regions, source, page, *,
                       plan_confirmed=False, min_confidence=80,
                       max_words=10000, max_markers=64):
    """Map exact, unique same-page definitions to physical marker candidates.

    `words` contains text/box/confidence mappings from caller-controlled OCR.
    Unknown or conflicting numbers are never joined. Low-confidence model or
    airflow evidence leaves `review_values` blank. Every candidate stays excluded
    and unverified; note-box markers are not counted as physical outlets.
    """
    if not plan_confirmed or len(words) > max_words or len(marker_boxes) > max_markers:
        return []
    words = [w for w in words if w.get('text', '').strip() and len(w.get('box', [])) == 4]
    definitions = {}
    for region in note_regions[:4]:
        markers = sorted((b for b in marker_boxes if _inside(_center(b), region)), key=lambda b: b[1])
        if len(markers) < 3:
            continue
        header = [w for w in words if _inside(_center(w['box']), region)
                  and w['box'][3] <= markers[0][1] + 1]
        header_rows = _lines(header)
        heading_words = next((row for row in header_rows
                              if 'KEYNOTES' in [_text(w) for w in row]
                              or re.search(r'\bKEYED NOTES\b', ' '.join(_text(w) for w in row))), None)
        if heading_words is None or not _confident(heading_words, min_confidence):
            continue
        for i, box in enumerate(markers):
            identity = _marker_number(words, box, min_confidence)
            if identity is None:
                continue
            number, number_words = identity
            bottom = markers[i + 1][1] - 1 if i + 1 < len(markers) else region[3]
            body = [w for w in words if w['box'][0] >= box[2] + .5 and w['box'][2] <= region[2]
                    and box[1] - 2 <= _center(w['box'])[1] < bottom]
            details = _note_details(body)
            # Duplicate definitions invalidate the number even if only one parses.
            definitions.setdefault(number, []).append((box, body, details, number_words))
    result = []
    for box in marker_boxes:
        if any(_inside(_center(box), region) for region in note_regions):
            continue
        identity = _marker_number(words, box, min_confidence)
        if identity is None:
            continue
        number, marker_words = identity
        options = definitions.get(number, [])
        if len(options) != 1 or options[0][2] is None:
            continue
        note_box, body, details, number_words = options[0]
        model, flow, witnesses = details
        confidence_words = marker_words + number_words + witnesses
        values = {'design_cfm': flow} if _confident(confidence_words, min_confidence) else {}
        evidence = ' '.join(_text(w) for row in _lines(body) for w in row)
        result.append({'kind': 'diffuser', 'tag': '', 'type': model, 'size': '', 'system': '', 'location': '',
                       'status': 'UNVERIFIED', 'include': False, 'values': {}, 'review_values': values,
                       'source': source, 'page': page, 'method': 'ocr_keynote', 'keynote': number,
                       'position': [round(v, 2) for v in _center(box)],
                       'region': list(box), 'region_coordinate_space': 'displayed_pdf_points',
                       'confidence_min': min(w['confidence'] if isinstance(w.get('confidence'), (int, float))
                                             and math.isfinite(w['confidence']) else 0 for w in confidence_words),
                       'note_position': [round(v, 2) for v in _center(note_box)],
                       'evidence_text': f'KEYNOTE {number}: {evidence}; separate physical marker at {_center(box)}',
                       'review_reasons': ['Confirm the physical marker identifies a supply grille, and verify airflow, neck, room and duct connection against the original. Note duct sizes are not assigned as diffuser neck sizes.']})
    return result
