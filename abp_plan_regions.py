"""Bounded geometric crops for small, outlined CAD callout text.

These rectangles are OCR hints, not recognized text or evidence of complete
coverage. No layer name, project vocabulary, device identity or value is used.
Raster drawings and unsupported geometry still need the ordinary plan reader.
"""
import math
import time
from collections import defaultdict
from itertools import chain


def paired_text_regions(page, deadline=None, max_paths=20000, max_regions=32,
                        max_glyphs=6000, max_lines=2000, max_pair_checks=20000):
    """Return (display-coordinate rectangles, truncated) for paired short lines.

    CAD exports often stroke each letter instead of storing PDF text. Group
    similarly sized small strokes into isolated horizontal lines, then select
    aligned line pairs. Prose, symbols and details can also fit this geometry;
    only the later OCR/parser may decide whether a crop contains a callout.
    """
    import pymupdf

    def expired():
        return deadline is not None and time.monotonic() >= deadline

    if expired() or min(max_paths, max_regions, max_glyphs, max_lines, max_pair_checks) <= 0:
        return [], True
    paths = page.get_cdrawings()
    if len(paths) > max_paths or expired():
        return [], True
    glyphs = []
    seen = set()
    for index, path in enumerate(paths):
        if index % 128 == 0 and expired():
            return [], True
        if path.get('fill') is not None or not 1 <= len(path.get('items', ())) <= 80:
            continue
        box = pymupdf.Rect(path['rect']) * page.rotation_matrix
        if not all(math.isfinite(v) for v in box):
            continue
        if not (2.9 <= box.height <= 16 and .07 * box.height <= box.width <= 1.4 * box.height):
            continue
        if not page.rect.contains(box):
            continue
        key = tuple(round(v, 2) for v in box)
        if key in seen:
            continue
        seen.add(key)
        glyphs.append(box)
        if len(glyphs) > max_glyphs:
            return [], True
    paths = None

    # Bounded neighboring buckets avoid an all-pairs pass over glyph paths.
    rows = []
    buckets = defaultdict(list)
    for box in sorted(glyphs, key=lambda b: (b.y0, b.x0)):
        if expired():
            return [], True
        y, h = round(box.y0 * 2), round(box.height * 2)
        choices = [row for dy in (-1, 0, 1) for dh in (-2, -1, 0, 1, 2)
                   for row in buckets.get((y + dy, h + dh), ())
                   if abs(row[0].y0 - box.y0) < .45 and abs(row[0].height - box.height) < .6]
        if choices:
            min(choices, key=lambda row: abs(row[0].y0 - box.y0)).append(box)
        else:
            row = [box]
            rows.append(row)
            buckets[(y, h)].append(row)

    lines = []
    for row in rows:
        if expired():
            return [], True
        chunks = []
        for box in sorted(row, key=lambda b: b.x0):
            # Include spaces within nearby prose so it is not mistaken for
            # several isolated short callout labels on the same baseline.
            if not chunks or box.x0 - chunks[-1][-1].x1 > box.height * 1.5:
                chunks.append([])
            chunks[-1].append(box)
        for chunk in chunks:
            if not 3 <= len(chunk) <= 14:
                continue
            box = pymupdf.Rect(chunk[0])
            for glyph in chunk[1:]:
                box |= glyph
            if 1.8 <= box.width / box.height <= 14:
                lines.append(box)
                if len(lines) > max_lines:
                    return [], True

    lines.sort(key=lambda b: (b.y0, b.x0))
    line_buckets = defaultdict(list)
    for box in lines:
        line_buckets[int(box.y0 // 40)].append(box)
    pairs = []
    comparisons = 0
    for first in lines:
        if expired():
            return pairs[:max_regions], True
        bucket = int(first.y0 // 40)
        for second in chain(line_buckets[bucket], line_buckets.get(bucket + 1, ())):
            # A dense band can put thousands of short lines in one bucket.
            # Bound comparisons and check time inside that band, not only
            # when moving to the next first line.
            if comparisons >= max_pair_checks or expired():
                return pairs[:max_regions], True
            comparisons += 1
            if not (.6 <= second.height / first.height <= 1.5
                    and 1.1 <= (second.y0 - first.y0) / first.height <= 2.3
                    and abs((first.x0 + first.x1 - second.x0 - second.x1) / 2) < first.height * .8
                    and .5 <= second.width / first.width <= 1.7):
                continue
            combined = first | second
            # A small margin keeps strokes clear of the raster border while
            # avoiding the connected duct/symbol below the text.
            margin = max(1.5, min(first.height, second.height) * .3)
            crop = (combined + (-margin, -margin, margin, margin)) & page.rect
            if not any(all(abs(a - b) < 1 for a, b in zip(crop, old)) for old in pairs):
                pairs.append(list(crop))
                # Do not accumulate every pair and then slice. The extra
                # candidate witnesses truncation while keeping dedup bounded.
                if len(pairs) > max_regions:
                    return pairs[:max_regions], True

    pairs.sort(key=lambda b: (b[1], b[0]))
    return pairs[:max_regions], len(pairs) > max_regions
