"""Spatial plan-callout candidates. No duct/system or room association is inferred."""
import math
import re
from collections import defaultdict

MARK = re.compile(r'(?:[A-Z]|S[A-Z]|SD\d?)$')
FLOW = re.compile(r'(?:\d{1,4}|\d{1,2},\d{3})$')

def plan_context(words):
    # Local title rows, not arbitrary concatenation across a drawing.
    rows = defaultdict(list)
    for w in words:
        rows[round(w[1] / 4)].append(w)
    lines = [' '.join(w[4] for w in sorted(row, key=lambda w:w[0])) for row in rows.values()]
    pattern = r'(?:MECHANICAL|HVAC)(?:\s+(?:FLOOR|CEILING|NEW WORK))*\s+PLAN|(?:FLOOR|CEILING)\s+PLAN\s*[-:]?\s*(?:MECHANICAL|HVAC)|PLAN\s*[-:]\s*HVAC'
    return any(re.search(pattern, line, re.I) for line in lines)

def centered_outlets(words, page_number, source, legend=None, *, plan_confirmed=False):
    """Read centered type-over-flow bubbles, including comma-formatted CFM.

    A single near number is insufficient. Require an isolated two-word native
    text block or a repeated, isolated callout grammar. Mutual uniqueness prevents
    assigning one flow to adjacent type marks. Coordinates remain PDF points.
    """
    if not plan_confirmed and not plan_context(words):return []
    legend = legend or {}
    blocks = defaultdict(list); grid = defaultdict(list)
    for i,w in enumerate(words):
        if len(w)>5:blocks[w[5]].append(i)
        grid[(int(w[0]//48),int(w[1]//48))].append(i)
    def nearby(w):
        x,y=int(w[0]//48),int(w[1]//48)
        return [i for dx in (-1,0,1) for dy in (-1,0,1) for i in grid.get((x+dx,y+dy),[])]
    pairs=[]; use=defaultdict(list)
    for i,w in enumerate(words):
        if not MARK.fullmatch(w[4]):continue
        h=w[3]-w[1]
        if not 3<=h<=30:continue
        options=[]
        for j in nearby(w):
            n=words[j]
            if not FLOW.fullmatch(n[4]):continue
            if abs((w[0]+w[2]-n[0]-n[2])/2)>.40*h:continue
            if not .15*h <= n[1]-w[3] <= 1.6*h:continue
            if not .65*h <= n[3]-n[1] <= 1.5*h:continue
            value=int(n[4].replace(',',''))
            if 10<=value<=10000:options.append(j)
        if len(options)!=1:continue
        j=options[0];n=words[j]
        # A prose paragraph containing letter/number tokens is not a callout.
        prose=any(k not in (i,j) and re.search('[A-Za-z]{3}',words[k][4])
                  and abs(words[k][1]-w[1])<h and abs(words[k][0]-w[0])<2*h for k in nearby(w))
        if prose:continue
        isolated=len(w)>5 and len(n)>5 and w[5]==n[5] and set(blocks[w[5]])=={i,j}
        pairs.append((i,j,isolated));use[j].append(i)
    result=[]
    for i,j,isolated in pairs:
        if len(use[j])!=1 or not (isolated or len(pairs)>=3):continue
        w,n=words[i],words[j];size=legend.get(w[4],'')
        result.append({'include':False,'type':w[4],'size':size,'system':'','location':'',
                       'design_cfm':int(n[4].replace(',','')),'source':source,'reference':f'page {page_number}',
                       'position':[round(w[0],2),round(w[1],2)],
                       'evidence_box':[min(w[0],n[0]),w[1],max(w[2],n[2]),n[3]],
                       'evidence':f'{w[4]} / {n[4]}; centered type-over-airflow plan callout; confirm supply service, neck size, room, system and revision',
                       'shape':('rectangular' if 'x' in size.lower() else 'round') if size else 'unknown'})
    return result

def distinct_outlets(items):
    """Collapse overlapping parser readings, never distinct equal-flow devices."""
    result=[]
    for item in items:
        p=item.get('position')
        duplicate=next((old for old in result if p and old.get('position') and
                       all(item.get(k)==old.get(k) for k in ('source','reference','type','design_cfm')) and
                       math.dist(p,old['position'])<4),None)
        if duplicate is None:result.append(item)
        elif not duplicate.get('size') and item.get('size'):duplicate['size']=item['size'];duplicate['shape']=item['shape']
    return result
