"""Spatial plan-callout candidates. No duct/system or room association is inferred."""
import math
import re
from collections import defaultdict

MARK = re.compile(r'(?:[A-Z]|S[A-Z]|SD\d?)$')
FLOW = re.compile(r'(?:\d{1,4}|\d{1,2},\d{3})$')
# These ambiguous equipment families cannot be used as unclassified outlets.
EQUIPMENT_MARKS = {'SF', 'EF', 'RF', 'PF', 'FS', 'UH', 'CU', 'AHU', 'RTU', 'FCU', 'MAU', 'MUA', 'DOAS'}
NECK = re.compile(r'(\d{1,2}(?:\.\d+)?)"[Øø⌀]|(\d{1,2}(?:\.\d+)?)[xX](\d{1,2}(?:\.\d+)?)"?')

def plan_context(words):
    # Require a title, not a prose reference such as "SEE HVAC FLOOR PLAN".
    # Local segments keep unrelated notes on the same horizontal band apart.
    rows = []
    for w in sorted(words, key=lambda w:(w[1],w[0])):
        if not rows or abs(w[1]-rows[-1][0][1])>3:rows.append([])
        rows[-1].append(w)
    lines=[]
    for row in rows:
        segment=[]
        for w in sorted(row,key=lambda w:w[0]):
            if segment and w[0]-segment[-1][2]>max(28,4*(w[3]-w[1])):
                lines.append(' '.join(v[4] for v in segment));segment=[]
            segment.append(w)
        if segment:lines.append(' '.join(v[4] for v in segment))
    level=r'(?:(?:\d+(?:ST|ND|RD|TH)?|FIRST|SECOND|THIRD|GROUND|LOWER|UPPER)\s+)?'
    title=rf'(?:{level}(?:MECHANICAL|HVAC)(?:\s+(?:FLOOR|CEILING|NEW WORK))*\s+PLAN|{level}(?:FLOOR|CEILING)\s+PLAN\s*[-:]?\s*(?:MECHANICAL|HVAC)|(?:FLOOR\s+)?PLAN\s*[-:]\s*HVAC)'
    for line in lines:
        line=re.sub(r'\bH\s*\.\s*V\s*\.\s*A\s*\.\s*C\s*\.', 'HVAC',line,flags=re.I).strip()
        if re.fullmatch(rf'(?:\d+\s+)?{title}(?:\s+\d+)?',line,re.I):return True
    return False

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
        if not MARK.fullmatch(w[4]) or w[4] in EQUIPMENT_MARKS:continue
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

def necked_outlets(words, page_number, source, *, plan_confirmed=False):
    """Three centered lines: diffuser mark / explicit neck / design airflow.

    This grammar has a neck-size witness rather than a nearby bare number.
    It does not assign supply service, room, equipment, or include a candidate.
    """
    if not plan_confirmed and not plan_context(words):return []
    grid=defaultdict(list)
    for i,w in enumerate(words):grid[(int(w[0]//48),int(w[1]//48))].append(i)
    def near(w):
        x,y=int(w[0]//48),int(w[1]//48)
        return [i for dx in (-1,0,1) for dy in (-1,0,1) for i in grid.get((x+dx,y+dy),[])]
    def below(a,b):
        h=a[3]-a[1]
        return (.65*h <= b[3]-b[1] <= 1.5*h and .65*h < b[1]-a[1] < 1.8*h
                and abs((a[0]+a[2]-b[0]-b[2])/2)<.45*h)
    pairs=[];used=defaultdict(int)
    for i,w in enumerate(words):
        if not re.fullmatch(r'(?:CSD\d+|SD\d*|S[A-Z]|[A-Z])',w[4]) or w[4] in EQUIPMENT_MARKS:continue
        if not 3<=w[3]-w[1]<=30:continue
        neighbors=near(w)
        if any(re.search(r'\b(?:INDICATES|TYPICAL|SYMBOL|LEGEND)\b',words[k][4],re.I)
               and abs(words[k][1]-w[1])<20 and abs(words[k][0]-w[0])<140 for k in neighbors):continue
        necks=[j for j in neighbors if NECK.fullmatch(words[j][4]) and below(w,words[j])]
        if len(necks)!=1:continue
        j=necks[0];n=words[j]
        flows=[k for k in near(n) if FLOW.fullmatch(words[k][4]) and below(n,words[k])
               and 10<=int(words[k][4].replace(',',''))<=10000]
        if len(flows)!=1:continue
        k=flows[0];pairs.append((i,j,k));used[j]+=1;used[k]+=1
    result=[]
    for i,j,k in pairs:
        if used[j]!=1 or used[k]!=1:continue
        w,n,f=words[i],words[j],words[k];neck=NECK.fullmatch(n[4]);round_neck=neck[1] is not None
        item={'include':False,'type':w[4],'size':n[4],'shape':'round' if round_neck else 'rectangular',
              'system':'','location':'','design_cfm':int(f[4].replace(',','')),'source':source,
              'reference':f'page {page_number}','position':[round(w[0],2),round(w[1],2)],
              'evidence_box':[min(v[0] for v in (w,n,f)),w[1],max(v[2] for v in (w,n,f)),f[3]],
              'evidence':f'{w[4]} / {n[4]} / {f[4]}; centered mark/neck/airflow callout; confirm supply duct, room, system and revision'}
        if round_neck:item['neck_in']=float(neck[1])
        result.append(item)
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
