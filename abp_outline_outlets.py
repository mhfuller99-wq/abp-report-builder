"""Review-only reading of stroked CAD airflow digits below native S labels.

Geometry never supplies a digit's identity. Two OCR renderings must agree before
a shape can teach another occurrence on this same page. Ambiguous shape labels,
missing glyphs and conflicting confident readings leave the proposed flow blank.
This is a recognition aid, not independent verification of design or coverage.
"""
import math
import re
import time


def prepare(page, native, deadline, *, max_anchors=24, max_paths=20_000):
    """Return bounded native anchors with adjacent line glyphs, in display space."""
    import pymupdf
    if not 1 <= max_anchors <= 24 or not 1 <= max_paths <= 20_000:
        raise ValueError('Invalid outlined-callout limits')
    anchors = [w for w in native if re.fullmatch(r'S\d{1,2}', w['text'])]
    limited = len(anchors) > max_anchors
    anchors = anchors[:max_anchors]
    if not anchors or time.monotonic() >= deadline:
        return [], bool(anchors) or limited
    paths = page.get_cdrawings()
    if len(paths) > max_paths:
        return [], True
    matrix = page.rotation_matrix
    strokes = []
    for index, path in enumerate(paths):
        if index % 128 == 0 and time.monotonic() >= deadline:
            return [], True
        items = path.get('items', [])
        if (path.get('type') == 's' and 1 <= len(items) <= 80
                and all(item[0] == 'l' for item in items)):
            box = pymupdf.Rect(path['rect']) * matrix
            if all(math.isfinite(v) for v in box):
                strokes.append((box, path))
    plans = []
    for anchor in anchors:
        if time.monotonic() >= deadline:
            return plans, True
        box = pymupdf.Rect(anchor['box'])
        h = box.height
        if not 3 <= h <= 20 or not 0 < box.width <= 5*h:
            continue
        clip = pymupdf.Rect(box.x0-h, box.y1-.3*h, box.x1+h, box.y1+1.15*h)
        if not page.rect.contains(clip):
            continue
        # Do not treat extractable native numbers as missing outline text.
        if any(re.search(r'\d', w['text']) and clip.contains(pymupdf.Rect(w['box']))
               for w in native if w is not anchor):
            continue
        selected = [(r, p) for r, p in strokes if clip.contains(r)
                    and 0 <= r.height <= 1.3*h and r.width <= 2*h
                    and .08*h <= p.get('width', 0) <= .2*h]
        if not selected or len(selected) > 40:
            continue
        groups = []
        for rect, path in sorted(selected, key=lambda pair: pair[0].x0):
            if groups and rect.x0 <= groups[-1]['box'].x1+.06*h:
                groups[-1]['box'] |= rect
                groups[-1]['paths'].append(path)
            else:
                groups.append({'box': pymupdf.Rect(rect), 'paths': [path]})
        groups = [g for g in groups if .5*h <= g['box'].height <= 1.3*h]
        if not 2 <= len(groups) <= 4 or any(sum(len(p['items']) for p in g['paths']) > 80 for g in groups):
            continue
        # All digits must share a baseline; nearby dimensions are not a flow.
        if (max(g['box'].y1 for g in groups)-min(g['box'].y1 for g in groups) > .2*h
                or any(b['box'].x0-a['box'].x1 > .5*h for a, b in zip(groups, groups[1:]))):
            continue
        for group in groups:
            rect = group['box']
            segments = []
            for path in group['paths']:
                for _, start, end in path['items']:
                    points = []
                    for point in (start, end):
                        point = pymupdf.Point(point)*matrix
                        points.append(((point.x-rect.x0)/rect.height, (point.y-rect.y0)/rect.height))
                    segments.append(tuple(sorted(points)))
            group['signature'] = sorted(segments)
        # Render only small strokes near the native label. Retain slashes and
        # separate half-height strokes (e.g. the two halves of a printed 3).
        crop = pymupdf.Rect(box.x0-.5*h, box.y1-.3*h, box.x1+.6*h, box.y1+1.2*h)
        render_paths = [p for r, p in strokes if crop.contains(r)
                        and .15*h <= r.height <= 1.3*h and r.width <= 3*h]
        if len(render_paths) > 60 or not render_paths:
            continue
        plans.append({'type': anchor['text'], 'anchor': list(box), 'crop': list(crop),
                      'glyphs': [g['signature'] for g in groups], 'paths': render_paths})
    # Two native labels sharing a numeric region cannot establish ownership.
    ambiguous = set()
    for i, first in enumerate(plans):
        for j in range(i):
            if (pymupdf.Rect(first['crop']) & pymupdf.Rect(plans[j]['crop'])).get_area() > 0:
                ambiguous.update((i, j))
    return [p for i, p in enumerate(plans) if i not in ambiguous], limited or bool(ambiguous)


def atlas(page, plans):
    """Temporary vector-only views; the original document is never changed.

Each number is rendered at original and half stroke widths. These correlated
views improve segmentation but never constitute independent source validation.
"""
    import pymupdf
    if not 0 < len(plans) <= 24:
        raise ValueError('Invalid outline atlas size')
    doc = pymupdf.open()
    try:
        target = doc.new_page(width=160, height=80*len(plans)*2)
        jobs = []
        for index, plan in enumerate(plans):
            crop = pymupdf.Rect(plan['crop'])
            if not 0 < crop.width <= 120 or not 0 < crop.height <= 55:
                raise ValueError('Invalid outline crop')
            for view, factor in enumerate((1., .5)):
                top = (index*2+view)*80
                def point(value):
                    transformed = pymupdf.Point(value)*page.rotation_matrix
                    return pymupdf.Point(transformed.x-crop.x0+10, transformed.y-crop.y0+top+10)
                for path in plan['paths']:
                    shape = target.new_shape()
                    for _, start, end in path['items']:
                        shape.draw_line(point(start), point(end))
                    shape.finish(color=(0, 0, 0), width=path.get('width', 1)*factor,
                                 closePath=False, lineCap=1, lineJoin=1)
                    shape.commit()
                jobs.append({'box': [0, top, crop.width+20, top+crop.height+20],
                             'source_box': plan['crop'], 'anchor_index': index,
                             'view': view, 'status': 'not_examined'})
        return doc, jobs
    except BaseException:
        doc.close()
        raise


def distance(first, second):
    if not first or len(first) != len(second):
        return math.inf
    return max(abs(x-y) for a, b in zip(first, second)
               for p, q in zip(a, b) for x, y in zip(p, q))


def context_jobs(plans, jobs, limit=6):
    """Reread a few single-view literals in their original drawing context."""
    import pymupdf
    choices = []
    for index, plan in enumerate(plans):
        strong = [(j['view'], w['text'], w['confidence']) for j in jobs if j['anchor_index'] == index
                  for w in j.get('words', []) if (w.get('confidence') or 0) >= 90
                  and re.fullmatch(r'\d{2,4}', w['text']) and len(w['text']) == len(plan['glyphs'])]
        if len({s[1] for s in strong}) == 1 and len({s[0] for s in strong}) == 1:
            box = pymupdf.Rect(plan['anchor']); h = box.height
            choices.append((max(s[2] for s in strong), {
                'box': [box.x0-.5*h, box.y0-.3*h, box.x1+1.2*h, box.y1+2.1*h],
                'anchor_index': index, 'view': 2, 'status': 'not_examined'}))
    return [job for _, job in sorted(choices, key=lambda pair: -pair[0])[:max(0, min(limit, 6))]]


def candidates(plans, jobs, source, page, deadline):
    """Retain literal observations and shape provenance; never approve a value."""
    if len(plans) > 24 or len(jobs) > 54:
        raise ValueError('Outlined candidate limit exceeded')
    observations = [[] for _ in plans]
    for job in jobs:
        index = job['anchor_index']
        if not 0 <= index < len(plans) or job['view'] not in (0, 1, 2):
            raise ValueError('Invalid outline crop identity')
        for word in job.get('words', [])[:100]:
            confidence = word.get('confidence')
            if isinstance(confidence, (int, float)) and math.isfinite(confidence):
                observations[index].append({'text': str(word['text'])[:40],
                                            'confidence': confidence, 'view': job['view']})
    training = []
    for index, (plan, reads) in enumerate(zip(plans, observations)):
        strong = [r for r in reads if r['confidence'] >= 90 and re.fullmatch(r'\d{2,4}', r['text'])
                  and len(r['text']) == len(plan['glyphs'])]
        labels = {r['text'] for r in strong}
        if len(labels) == 1 and len({r['view'] for r in strong}) >= 2:
            for digit, signature in zip(next(iter(labels)), plan['glyphs']):
                training.append((digit, signature, index))
    found = []
    for index, (plan, reads) in enumerate(zip(plans, observations)):
        if time.monotonic() >= deadline:
            break
        decoded = []; support = []
        for signature in plan['glyphs']:
            matches = [(digit, origin) for digit, trained, origin in training
                       if distance(signature, trained) < .06]
            labels = {digit for digit, _ in matches}
            decoded.append(next(iter(labels)) if len(labels) == 1 else '?')
            support.append(sorted({origin+1 for _, origin in matches}))
        reading = ''.join(decoded)
        # An alternative confidently read on this outlet is never silently
        # discarded in favor of a learned shape. Every observation is retained.
        conflict = any(r['confidence'] >= 90 and re.fullmatch(r'\d{2,4}', r['text'])
                       and r['text'] != reading for r in reads)
        value = int(reading) if reading.isdigit() and not reading.startswith('0') else None
        values = {'design_cfm': value} if value is not None and 10 <= value <= 9999 and not conflict else {}
        found.append({'kind': 'diffuser', 'tag': '', 'source': source, 'page': page,
                      'method': 'native_anchor_outline_ocr', 'status': 'UNVERIFIED', 'include': False,
                      'values': {}, 'review_values': values, 'type': plan['type'], 'type_confidence': 100,
                      'size': '', 'position': plan['anchor'][:2],
                      'position_coordinate_space': 'displayed_pdf_points',
                      'region': plan['crop'], 'region_coordinate_space': 'displayed_pdf_points',
                      'evidence_text': plan['type']+' / '+(str(value) if values else 'UNRESOLVED')+
                          '; native label with adjacent outlined digits; compare original source',
                      'outline_readings': reads, 'outline_shape_reading': reading,
                      'outline_support_anchors': support,
                      'review_reasons': ['Unverified outlined-digit recognition. Two renderings of the same source are not independent verification. Confirm supply service, airflow, room, system, neck size and revision.'
                          + (' Conflicting confident readings; airflow left blank.' if conflict else '')]})
    return found
