"""Recognize a printed exhaust-grille symbol as a review hint, scoped to one legend."""
from collections import defaultdict
import math
import re

def exhaust_sample(words):
    """Locate the explicitly described grille symbol beside a single same-page legend."""
    blocks = defaultdict(list)
    for word in words:
        if len(word) >= 8:
            blocks[word[5]].append(word)
    samples = []
    headings = []
    for block in blocks.values():
        if len(block) > 100:
            continue
        ordered = sorted(block, key=lambda word: (word[6], word[7]))
        text = ' '.join(word[4].upper() for word in ordered)
        if re.fullmatch(r'(?:\d+ )?(?:(?:MECHANICAL|HVAC) )?SYMBOLS? (?:SCHEDULE|LEGEND)', text):
            headings.append((ordered[0][0], max(w[3] for w in ordered)))
        match = re.fullmatch(
            r'TYPE ["“]?([A-Z][A-Z0-9-]{0,5})["”]?,? (?:EXH|EXHAUST)(?: AIR)? (?:GR|GRILLE),? '
            r'BALANCE TO CFM INDICATED,? SEE EQUIPMENT SCHEDULE,? OTHERS SIMILAR\.? '
            r'\1 (\d{2,4})', text)
        if not match:
            continue
        mark, flow = ordered[-2:]
        prose = ordered[:-2]
        h = mark[3] - mark[1]
        if (3 <= h <= 25 and 0 < min(w[0] for w in prose) - mark[2] <= 15*h
                and min(w[1] for w in prose) <= mark[1] <= max(w[3] for w in prose)
                and 0 <= flow[1] - mark[3] <= 2*h
                and abs(mark[0]+mark[2]-flow[0]-flow[2]) <= h):
            samples.append((mark, flow, prose[0], h))
    if len(samples) != 1 or len(headings) != 1:
        return None
    mark, flow, prose, h = samples[0]
    if not any(0 <= prose[1]-y <= 60*h and -2*h <= prose[0]-x <= 24*h for x,y in headings):
        return None
    return mark, flow


def boxed_mark(display, word):
    """Find four complete straight edges enclosing the identifier at the printed scale."""
    import pymupdf
    w = word
    h = w[3] - w[1]
    if not 3 <= h <= 25:
        return False
    cx, cy = (w[0]+w[2])/2, (w[1]+w[3])/2
    scale = 32/h
    clip = pymupdf.Rect(cx-h, cy-h, cx+h, cy+h)
    pix = display.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY,
                             clip=clip, alpha=False)
    if not (63 <= pix.width <= 66 and 63 <= pix.height <= 66):
        return False
    data = pix.samples
    width = pix.width
    mx, my = round(cx*scale-pix.x), round(cy*scale-pix.y)
    # Straight lines can be thin or antialiased. Opposite edges must straddle
    # the whole glyph, including its vertical extent and most of the text box.
    left = range(mx-24, mx-max(7, math.ceil((w[2]-w[0])*scale*.41))+1)
    right = range(mx+max(7, math.ceil((w[2]-w[0])*scale*.41)), mx+25)
    top, bottom = range(my-26, my-11), range(my+12, my+27)
    def vertical(x):
        return all(data[y*width+x] < 200 for y in range(my-9, my+10))
    def horizontal(y):
        return all(data[y*width+x] < 200 for x in range(mx-6, mx+7))
    left = [x for x in left if vertical(x)]
    right = [x for x in right if vertical(x)]
    top = [y for y in top if horizontal(y)]
    bottom = [y for y in bottom if horizontal(y)]
    if max(map(len, (left,right,top,bottom))) > 6:
        return False
    for x0 in left:
        for x1 in right:
            for y0 in top:
                for y1 in bottom:
                    if (abs(x0+x1-2*mx)>7 or abs(y0+y1-2*my)>7
                            or not .45 <= (x1-x0)/(y1-y0) <= 1.7):
                        continue
                    if not all(data[y*width+x] < 200 for y in (y0,y1) for x in range(x0+2,x1-1)):
                        continue
                    if not all(data[y*width+x] < 200 for x in (x0,x1) for y in range(y0+2,y1-1)):
                        continue
                    # A line crossing the label as part of a table or duct is
                    # insufficient. Each of the four edges terminates at the box.
                    if any(data[y*width+x] < 200 for y in (y0,y1) for x in (x0-3,x1+3)):
                        continue
                    if any(data[y*width+x] < 200 for x in (x0,x1) for y in (y0-3,y1+3)):
                        continue
                    return True
    return False


def grille_hints(page, words, outlets, examples):
    """Add evidence to unchecked centered observations. Never infer an exhaust fan or room."""
    if not examples or not outlets or len(outlets)>100:
        return
    sample = exhaust_sample(words)
    if sample is None:
        return
    by_location = defaultdict(list)
    for word in words:
        by_location[(round(word[0],2),round(word[1],2),word[4])].append(word)
    mark, flow = sample
    other_boxes = [bounds for tag, _, bounds in examples if tag==mark[4]
                   and not (bounds[0]<=mark[0]<=bounds[2] and bounds[1]<=mark[1]<=bounds[3])]
    if len(other_boxes)!=1:
        return
    x0,y0,x1,y1 = other_boxes[0]
    other_marks = [w for w in words if w[4]==mark[4] and x0<=w[0] and w[2]<=x1 and y0<=w[1] and w[3]<=y1]
    if len(other_marks)!=1:
        return
    display = page.get_displaylist()
    if not boxed_mark(display, mark) or boxed_mark(display, other_marks[0]):
        return
    for outlet in outlets:
        pos = outlet.get('position')
        if (outlet.get('include') is not False or not pos or len(pos)!=2
                or 'centered type-over-airflow' not in outlet.get('evidence','')):
            continue
        marks = by_location[(*pos, outlet.get('type'))]
        if len(marks)!=1 or marks[0]==mark or not boxed_mark(display, marks[0]):
            continue
        outlet['service_hint']='possible_exhaust'
        outlet['review_notice']=(f'This boxed identifier matches the exhaust grille symbol in the page legend '
                                 f'({mark[4]} / {flow[4]} CFM). Trace the duct to confirm its service and fan.')
        # The same type letter can have an entirely different supply neck.
        outlet['size']=''
        outlet['shape']='unknown'
        outlet.pop('neck_in', None)
