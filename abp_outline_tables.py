"""Bounded line-glyph schedule rendering anchored to native table headings.

Keep vector letters/digits, omit long table rules, and combine OCR data cells
with their original native headers. No source PDF is modified. Unsupported
graphics, unknown titles and image-backed tables use the ordinary OCR path.
"""
import math
import re
import time


def split_flow_cells(words):
    """Locate split thousands under the explicit furnace TOTAL column.

This only requests a reread. Concatenated fragments never become a value here.
"""
    from abp_mechanical import phrases
    tuples=[(*w['box'],w['text']) for w in words]
    if not phrases(tuples,r'NATURAL GAS FURNACE') or not phrases(tuples,r'O\.A\. CFM'):
        return []
    marks=sorted((w for w in words if w['text']=='MARK'),key=lambda w:w['box'][0])
    if len(marks)!=3:return []
    headers=[w for w in words if w['text']=='TOTAL' and marks[0]['box'][0]<w['box'][0]<marks[1]['box'][0]
             and abs(w['box'][1]-marks[0]['box'][1])<3]
    if len(headers)!=1:return []
    anchor=headers[0];x=(anchor['box'][0]+anchor['box'][2])/2
    found=[]
    for tag in words:
        if not re.fullmatch(r'AHU-\d+',tag['text']) or abs(tag['box'][0]-marks[0]['box'][0])>25:continue
        if not 0<tag['box'][1]-anchor['box'][1]<100:continue
        parts=sorted((w for w in words if abs(w['box'][1]-tag['box'][1])<3
                      and abs((w['box'][0]+w['box'][2])/2-x)<25
                      and re.fullmatch(r'\d{1,3}',w['text'])),key=lambda w:w['box'][0])
        # Low-confidence fragments are exactly why a source-cell reread is
        # needed. Selection supplies no value: the caller still requires one
        # >=90-confidence literal matching every digit before accepting it.
        if (len(parts)!=2 or len(parts[1]['text'])!=3
                or not 0<parts[1]['box'][0]-parts[0]['box'][2]<8):
            continue
        found.append(parts)
    return found[:4]


def read(page, box, native, pixels, timeout, engine):
    import pymupdf
    started = time.monotonic()
    rect = pymupdf.Rect(box)
    headers = [w for w in native if rect.contains(pymupdf.Rect(w['box']))]
    title = ' '.join(w['text'].upper() for w in headers)
    # These bounded schemas have native marks and airflow/pressure headers.
    # A register range table or generic catalog page is not an equipment table.
    furnace = all(token in title for token in ('SPLIT', 'SCHEDULE', 'FURNACE', 'MARK', 'E.S.P.', 'CFM'))
    fan = all(token in title for token in ('EXHAUST', 'FAN', 'SCHEDULE', 'ID', 'E.S.P.', 'CFM'))
    if not (furnace or fan) or len(headers)>500 or pixels<10_000:
        return None
    if any(re.fullmatch(r'ACTUAL|MEASURED|INITIAL|FINAL', w['text'], re.I) for w in headers):
        return None
    for image in page.get_image_info():
        if (pymupdf.Rect(image['bbox'])*page.rotation_matrix & rect).get_area()>100:
            return None
    render_rect = pymupdf.Rect(rect)
    if furnace:
        marks = sorted((w for w in headers if w['text'].upper()=='MARK'), key=lambda w:w['box'][0])
        if len(marks)!=3 or max(w['box'][1] for w in marks)-min(w['box'][1] for w in marks)>3:
            return None
        # Read the furnace section separately; condenser/coil marks and ratings
        # are associated components and never independent air-moving units.
        render_rect.x1=marks[1]['box'][0]-4
    paths=page.get_cdrawings()
    if len(paths)>20_000:
        return None
    selected=[];operations=0
    matrix=page.rotation_matrix
    for index,path in enumerate(paths):
        if index%128==0 and time.monotonic()-started>=timeout:
            raise TimeoutError('Outlined schedule selection deadline')
        bounds=pymupdf.Rect(path['rect'])*matrix
        items=path.get('items',[])
        if (render_rect.contains(bounds) and 0<=bounds.height<=20 and 0<=bounds.width<=25
                and path.get('type')=='s' and 1<=len(items)<=80
                and all(item[0] in ('l','c') for item in items)
                and all(math.isfinite(v) for v in bounds)):
            selected.append(path);operations+=len(items)
            if len(selected)>3000 or operations>50_000:
                return None
    if len(selected)<20:
        return None
    with pymupdf.open() as doc:
        target=doc.new_page(width=render_rect.width+20,height=render_rect.height+20)
        def point(value):
            p=pymupdf.Point(value)*matrix
            return pymupdf.Point(p.x-render_rect.x0+10,p.y-render_rect.y0+10)
        for index,path in enumerate(selected):
            if index%128==0 and time.monotonic()-started>=timeout:
                raise TimeoutError('Outlined schedule rendering deadline')
            shape=target.new_shape()
            for item in path['items']:
                if item[0]=='l':shape.draw_line(point(item[1]),point(item[2]))
                else:shape.draw_bezier(*[point(p) for p in item[1:]])
            shape.finish(color=(0,0,0),width=path.get('width',1),closePath=False)
            shape.commit()
        remaining=timeout-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('Outlined schedule rendering deadline')
        words=engine(target,pixels,remaining,clip=list(target.rect),psm=11,max_zoom=5)
    for w in words:
        w['box']=[v+(render_rect.x0-10 if i%2==0 else render_rect.y0-10) for i,v in enumerate(w['box'])]
        w['recognition_method']='outlined_schedule'
    # Values already present as native text keep their exact text and identity.
    # Native text is source evidence, not a confidence upgrade to unrelated OCR.
    words.extend({**w,'confidence':100,'recognition_method':'native_schedule_text'} for w in headers)
    return words
