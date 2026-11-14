"""Review-only label/value product tables; no totals or equipment-ID inference."""
import re

def uncertain_rows(words):
    """Request bounded rereads; this supplies neither values nor confidence."""
    if len(words)>30000:return []
    anchors=[w for w in words if w['text'].lower() in ('airflow','design')]
    if len(anchors)>32:return []
    requests=[]
    for anchor in anchors:
        x,y,_,bottom=anchor['box'];h=bottom-y
        row=sorted([w for w in words if abs(w['box'][1]-y)<2.5 and x<=w['box'][0]<x+110],key=lambda w:w['box'][0])
        stop=next((i for i,w in enumerate(row) if re.fullmatch(r'cfm|H[2₂][O0]',w['text'],re.I)),None)
        if stop is None:continue
        row=row[:stop+1];text=' '.join(w['text'] for w in row)
        if not re.fullmatch(r'Airflow\s+[\d,]+\s+cfm|Design\s+ESP\s+\d+(?:\.\d+)?\s+in\s+H[2₂][O0]',text,re.I):continue
        if any((w.get('confidence') or 0)<80 for w in row):requests.append(row)
    return requests[:3]

def same_row(before,after):
    def normalize(words):
        return re.sub(r'\bH[2₂][O0]\b','H2O',' '.join(w['text'] for w in words).upper())
    return bool(after) and normalize(before)==normalize(after) and all((w.get('confidence') or 0)>=80 for w in after)

def product_tag(native):
    text=' '.join(w['text'] for w in native)
    if len(native)>30000 or not re.search(r'\bProduct Report\b',text,re.I):return None
    tags=re.findall(r'\bTag\(s\):\s*(RTU-\d+[A-Z]?)\b',text,re.I)
    if len(set(tags))!=1:return None
    # A multi-unit selection cannot be attached to just the first mark.
    all_tags=set(re.findall(r'\bRTU-\d+[A-Z]?\b',text,re.I))
    return tags[0].upper() if len(all_tags)==1 else None

def candidates(words,native,source,page):
    tag=product_tag(native)
    if not tag or len(words)>30000:return []
    if re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|AS FOUND|TEST REPORT|FINAL READING)\b',' '.join(w['text'] for w in words),re.I):return []
    rows=[]
    for w in sorted(words,key=lambda w:(w['box'][1],w['box'][0])):
        if not rows or abs(w['box'][1]-rows[-1][0]['box'][1])>2.5:rows.append([])
        rows[-1].append(w)
    patterns={
        'design_cfm':(r'Airflow\s+(\d{2,5}(?:,\d{3})?)\s+cfm',10,100000),
        'esp':(r'Design\s+ESP\s+(\d+(?:\.\d+)?)\s+in\s+H[2₂][O0]',0,10),
        'motor_hp':(r'Supply\s+Motor\s+Horsepower\s+(\d+(?:\.\d+)?)\s+hp',0,100),
    }
    found={};evidence=[]
    for row in rows:
        row.sort(key=lambda w:w['box'][0])
        text=' '.join(w['text'] for w in row)
        for field,(pattern,low,high) in patterns.items():
            for match in re.finditer(r'\b'+pattern+r'\b',text,re.I):
                offset=0;relevant=[]
                for w in row:
                    end=offset+len(w['text'])
                    if offset<match.end() and end>match.start():relevant.append(w)
                    offset=end+1
                value=float(match[1].replace(',',''))
                adjacent=all(0<=b['box'][0]-a['box'][2]<=max(12,2*(a['box'][3]-a['box'][1])) for a,b in zip(relevant,relevant[1:]))
                if relevant and adjacent and all((w.get('confidence') or 0)>=80 for w in relevant) and low<=value<=high:
                    found.setdefault(field,[]).append(value);evidence.extend(relevant)
    values={k:v[0] for k,v in found.items() if len(set(v))==1}
    if not values:return []
    return [{'kind':'equipment','tag':tag,'source':source,'page':page,'method':'ocr_product_table',
        'status':'UNVERIFIED','include':False,'values':{},'review_values':values,
        'template':'Air Moving Equipment.xlsx','evidence':evidence,'identity_evidence':native[:100],
        'review_reasons':['Product selection candidate: verify each label, value, equipment ID and revision. Design ESP excludes total static pressure; horsepower excludes operating power.']}]
