#!/usr/bin/env python3
"""ABP local report builder. Uses original workbook templates; no cloud upload."""
import io,json,re,sys,zipfile,html,datetime,hashlib,hmac,time,math,csv,os,secrets,base64,ipaddress,socket,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import unquote,parse_qs,urlsplit
from openpyxl import Workbook,load_workbook
from openpyxl.workbook.properties import CalcProperties
from openpyxl.styles import Font,PatternFill
from openpyxl.utils import get_column_letter
from abp_reference import inspect_reference, build_reference

ROOT=Path(__file__).resolve().parent
TEMPLATES=ROOT/'03_Workbooks_and_Master_Templates'
FILES=[p for p in sorted(TEMPLATES.glob('*.xlsx')) if p.name not in {'Blue Mountain - TAB Report.xlsx','CAFB Egress Shop - TAB Report.xlsx','CALEDONIA FEILDHOUSE TAB REPORT.xlsx','Cadence  Bank- Starkville MS .xlsx','New Hope Fieldhouse.xlsx','WEST LOWNDES FIELDHOUSE .xlsx'}]
LOOKUP={p.name:p for p in FILES}
TAGS=re.compile(r'\b(?:(?:BCU|BC|CH|CHWP|HWP|CWP|P)[-\s]+|(?:AHU|RTU|OAU|DOAS|CRU|MAU|ERV|HRV|FCU|VAV|IU|AC|DSS|DCU|KEF|TEF|KH|EF|SF|RF|EUH|EWH|CUH|UH|FFU|LF)[-\s]?)\d+(?:-[A-Z0-9]+)*\b',re.I)
MAX_RECORDS=500
MAX_UPLOAD=40_000_000
MAX_OUTPUT_ROWS=30000
# Only propose values from explicitly labeled nearby text. Never silently verify.
VALUE_PATTERNS={
 'design_cfm': re.compile(r'(?<![A-Z])(?:DESIGN\s+|SUPPLY\s+|TOTAL\s+)?(?:AIRFLOW|CFM)\s*[:=]\s*([\d,]+(?:\.\d+)?)|\b([\d,]+(?:\.\d+)?)\s*CFM\b',re.I),
 'osa_cfm':re.compile(r'\b(?:OSA|OA|OUTSIDE\s+AIR)\s*(?:CFM|AIRFLOW)?\s*[:=]\s*([\d,]+(?:\.\d+)?)',re.I),
 'esp':re.compile(r'\b(?:ESP|EXTERNAL\s+STATIC(?:\s+PRESSURE)?)\s*[:=]\s*([\d.]+)',re.I),
 'motor_hp':re.compile(r'\b(?:MOTOR\s+)?HP\s*[:=]\s*([\d.]+)',re.I)}
def candidate_values(text):
    result={}
    for key,pattern in VALUE_PATTERNS.items():
        m=pattern.search(text)
        if m:
            val=next((x for x in m.groups() if x),None)
            if val:
                try:result[key]=float(val.replace(',',''))
                except ValueError:pass
    return result


def excel_safe(value):
    value=str(value)
    return '\''+value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def read_sources(blobs):
    """Collect every occurrence and provenance. Do not invent values from surrounding text."""
    warnings=[];records={};sources=[];total_chars=0;preview=[];signals=set()
    if sum(len(data) for _,data in blobs)>MAX_UPLOAD:raise ValueError('Total source size exceeds 40 MB')
    for name,data in blobs:
        name=Path(name).name[:160];ext=Path(name).suffix.lower();chunks=[]
        try:
            if ext=='.pdf':
                import fitz
                with fitz.open(stream=data,filetype='pdf') as doc:
                    if doc.page_count>300:raise ValueError('PDF has more than 300 pages')
                    for i,page in enumerate(doc):
                        txt=page.get_text(sort=True)
                        chunks.append((f'page {i+1}',txt))
                    if not any(t.strip() for _,t in chunks):warnings.append(name+': image-only PDF; manual takeoff required')
            elif ext=='.csv':
                decoded=data.decode('utf-8-sig')
                for i,row in enumerate(csv.reader(io.StringIO(decoded)),1):
                    if any(row):chunks.append((f'CSV row {i}',' | '.join(row)[:4000]))
                    if i>MAX_OUTPUT_ROWS:raise ValueError('CSV has too many rows')
            elif ext=='.xlsx':
                wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
                for ws in wb:
                    ws.reset_dimensions()
                    for i,row in enumerate(ws.iter_rows(),1):
                        vals=[str(c.value)[:150] if c.value is not None else '' for c in row]
                        if any(vals):chunks.append((f'{ws.title} row {i}',' | '.join(vals)[:4000]))
                        if len(chunks)>MAX_OUTPUT_ROWS:raise ValueError('Workbook has too many nonempty rows')
                wb.close()
            else:warnings.append(name+': unsupported source type');continue
            sources.append({'name':name,'sections':len(chunks),'sha256':hashlib.sha256(data).hexdigest()})
            for place,chunk in chunks:
                total_chars+=len(chunk)
                # Heading evidence is only a recommendation, never verified TAB data.
                for signal,pattern in SCHEDULE_SIGNALS.items():
                    if pattern.search(chunk[:6000]):signals.add(signal)
                if len(preview)<12:preview.append(chunk[:200])
                for line in chunk.splitlines():
                    for m in TAGS.finditer(line):
                        if re.search(r'\b(?:IAS|ICC|ANSI|ASTM)\s*$',line[:m.start()],re.I):continue
                        tag=m.group().upper().replace(' ','-')
                        next_tag=TAGS.search(line,m.end())
                        stop=min(m.end()+140,next_tag.start() if next_tag else len(line))
                        local=line[m.end():stop]
                        context=line[max(0,m.start()-55):stop]
                        evidence={'source':name,'reference':place,'evidence':context[:190]}
                        vals=candidate_values(local)
                        if tag not in records:
                            records[tag]={'tag':tag,**evidence,'occurrences':[evidence],'design_cfm':None,'osa_cfm':None,'esp':None,'motor_hp':None,'status':'UNVERIFIED','candidates':[]}
                        elif len(records[tag]['occurrences'])<30:records[tag]['occurrences'].append(evidence)
                        # Candidates are suggestions, not approved inputs. Restrict to the tag's local context.
                        if vals and len(records[tag]['candidates'])<30:
                            records[tag]['candidates'].append({'values':vals,**evidence})
            if len(records)>MAX_RECORDS:warnings.append('More than 500 unique tags found; only first 500 will be shown')
        except Exception as e:warnings.append(name+': could not parse ('+str(e)[:120]+')')
    return {'tags':list(records)[:MAX_RECORDS],'records':list(records.values())[:MAX_RECORDS],'warnings':warnings,'characters':total_chars,'sources':sources,'preview':'\n'.join(preview)[:1800],'signals':sorted(signals)}

# These labels only suggest which original ABP workbook to include.
# They do not verify equipment quantities, schedules, or field measurements.
SCHEDULE_SIGNALS={
 'diffusers':re.compile(r'\b(?:SUPPLY|RETURN|EXHAUST)\s+(?:AIR\s+)?(?:DIFFUSER|GRILLE|REGISTER)\s+SCHEDULE\b|\bAIR\s+DEVICE\s+SCHEDULE\b',re.I),
 'exhaust_grilles':re.compile(r'\bEXHAUST\s+(?:AIR\s+)?GRILLE\s+SCHEDULE\b',re.I),
 'erv':re.compile(r'\b(?:ENERGY\s+RECOVERY\s+VENTILATOR|ERV)\s+SCHEDULE\b',re.I),
 'fan_coil':re.compile(r'\bFAN\s+COIL\s+(?:UNIT\s+)?SCHEDULE\b',re.I),
 'water_coil':re.compile(r'\b(?:HOT\s+WATER|CHILLED\s+WATER|HYDRONIC)\s+COIL\s+SCHEDULE\b',re.I),
 'cooling_tower':re.compile(r'\bCOOLING\s+TOWER\s+SCHEDULE\b',re.I),
 'boiler':re.compile(r'\bBOILER\s+SCHEDULE\b',re.I),
 'chiller':re.compile(r'\bCHILLER\s+SCHEDULE\b',re.I),
 'kitchen_hood':re.compile(r'\bKITCHEN\s+(?:EXHAUST\s+)?HOOD\s+SCHEDULE\b',re.I),
 'heat_exchanger':re.compile(r'\bHEAT\s+EXCHANGER\s+SCHEDULE\b',re.I),
 'filter_unit':re.compile(r'\bFAN\s+FILTER\s+UNIT\s+SCHEDULE\b',re.I),
 'hydronic':re.compile(r'\b(?:BALANCING\s+VALVE|AUTO[- ]FLOW)\s+SCHEDULE\b',re.I),
 'dehumidifier':re.compile(r'\bDEHUMIDIFIER\s+SCHEDULE\b',re.I),
 'air_moving':re.compile(r'\b(?:AIR\s+HANDLING\s+UNIT|ROOFTOP\s+UNIT|SUPPLY\s+FAN|MAKEUP\s+AIR\s+UNIT)\s+SCHEDULE\b',re.I),
 'exhaust_fan':re.compile(r'\bEXHAUST\s+FAN\s+SCHEDULE\b',re.I),
}
def suggested_templates(tags,signals=None):
    """Return explained recommendations; always allow manual override in UI."""
    tags=[str(x).upper()[:80] for x in tags[:MAX_RECORDS] if isinstance(x,str)] if isinstance(tags,list) else []
    signals=set(x for x in (signals or []) if isinstance(x,str)) if isinstance(signals,list) else set()
    result=[]
    def add(filename,reason,review=False):
        if filename in LOOKUP and not any(x['name']==filename for x in result):
            result.append({'name':filename,'reason':reason,'review':review})
    for name in ('Project Information.xlsx','Notes.xlsx','PRE-TAB Checklist.xlsx'):
        add(name,'Core project documentation')
    def tagged(prefixes):
        return any(re.match(r'^(?:'+prefixes+r')[- ]?\d',tag) for tag in tags)
    if tagged('AHU|RTU|OAU|DOAS|MAU|AC|SF|RF|CRU') or 'air_moving' in signals:
        add('Air Moving Equipment.xlsx','Air-moving equipment tags or schedule heading')
    if tagged('EF|KEF|TEF') or 'exhaust_fan' in signals:
        add('Exhaust Fans _Std._.xlsx','Exhaust fan tags or schedule heading')
    if tagged('FCU|IU|BCU|BC') or 'fan_coil' in signals:
        water=tagged('BCU|BC') or 'water_coil' in signals
        add('Fan Coil Units WTR.xlsx' if water else 'Fan Coil Units DX.xlsx','Fan-coil equipment; confirm water or DX type against the schedule',True)
    if tagged('CH'):
        add('Chiller - Air Cooled.xlsx','Chiller tag detected; confirm air or water cooling',True)
    if tagged('ERV|HRV') or 'erv' in signals:
        add('ERV.xlsx','Energy-recovery equipment or schedule; confirm model type',True)
    if tagged('FFU') or 'filter_unit' in signals:
        add('Fan Filter Units.xlsx','Fan-filter unit tags or schedule')
    if 'exhaust_grilles' in signals or 'diffusers' in signals:
        add('Exhaust Grilles.xlsx.xlsx','Air-device/grille schedule detected; review device types',True)
    if 'water_coil' in signals:
        add('Coil WTR CLG WTR HT.xlsx','Water-coil schedule heading detected',True)
    if 'cooling_tower' in signals:add('Cooling Tower.xlsx','Cooling tower schedule heading')
    if 'boiler' in signals:add('Boiler.xlsx','Boiler schedule heading')
    if 'chiller' in signals:
        add('Chiller - Air Cooled.xlsx','Chiller schedule; confirm air or water cooling',True)
    if tagged('KH') or 'kitchen_hood' in signals:add('Kitchen Hood.xlsx','Kitchen exhaust hood tag or schedule heading')
    if 'heat_exchanger' in signals:add('Heat Exchanger.xlsx','Heat exchanger schedule heading')
    if 'hydronic' in signals:add('Hydronic BV - Auto-flow.xlsx','Hydronic balancing valve schedule',True)
    if 'dehumidifier' in signals:add('Dehumidifier.xlsx','Dehumidifier schedule heading')
    return {'recommended':result,'review_note':'Recommendations use equipment tags and readable schedule headings only. Verify all sheets against the latest mechanical schedules; scanned/image-only PDFs require manual review.'}


def sheet_name(wb,name):
    s=name[:31];i=2
    while s in wb.sheetnames:
        suffix=f' ({i})';s=name[:31-len(suffix)]+suffix;i+=1
    return s

def add_template(wb,path):
    source=load_workbook(path)
    for ws in source:
        dst=wb.create_sheet(sheet_name(wb,ws.title))
        for row in ws:
            for c in row:
                target=dst[c.coordinate]
                target.value=c.value
                if c.has_style:
                    from copy import copy
                    target.font=copy(c.font);target.fill=copy(c.fill);target.border=copy(c.border);target.alignment=copy(c.alignment);target.protection=copy(c.protection);target.number_format=c.number_format
                if c.hyperlink:target._hyperlink=__import__('copy').copy(c.hyperlink)
                if c.comment:target.comment=__import__('copy').copy(c.comment)
        for merged in ws.merged_cells.ranges:dst.merge_cells(str(merged))
        for k,d in ws.column_dimensions.items():dst.column_dimensions[k].width=d.width;dst.column_dimensions[k].hidden=d.hidden
        for k,d in ws.row_dimensions.items():dst.row_dimensions[k].height=d.height;dst.row_dimensions[k].hidden=d.hidden
        dst.sheet_format=__import__('copy').copy(ws.sheet_format)
        dst.sheet_properties=__import__('copy').copy(ws.sheet_properties)
        dst.print_options=__import__('copy').copy(ws.print_options)
        dst.page_margins=__import__('copy').copy(ws.page_margins)
        dst.page_setup=__import__('copy').copy(ws.page_setup)
        dst.freeze_panes=ws.freeze_panes
    source.close()

def validate_payload(payload):
    if not isinstance(payload,dict):raise ValueError('Invalid request')
    if not str(payload.get('project','')).strip():raise ValueError('Project name is required')
    if len(str(payload.get('project','')))>180:raise ValueError('Project name too long')
    if len(str(payload.get('location','')))>180:raise ValueError('Location too long')
    if payload.get('standard','Commercial') not in ('Commercial','USACE'):raise ValueError('Unknown project standard')
    selected=payload.get('templates',[])
    if not isinstance(selected,list) or not selected or len(selected)!=len(set(selected)) or any(t not in LOOKUP for t in selected):raise ValueError('Choose valid, unique templates')
    records=payload.get('records',[])
    if not isinstance(records,list) or len(records)>MAX_RECORDS:raise ValueError('Invalid review records')
    seen=set()
    for r in records:
        if not isinstance(r,dict):raise ValueError('Invalid equipment record')
        tag=str(r.get('tag','')).upper().strip()
        if not TAGS.fullmatch(tag) or tag in seen:raise ValueError('Invalid or duplicate equipment tag: '+tag)
        seen.add(tag)
        if str(r.get('status','UNVERIFIED')) not in ('UNVERIFIED','VERIFIED','EXCLUDED'):raise ValueError('Invalid review status')
        if r.get('status')=='VERIFIED' and all(r.get(k) in (None,'') for k in ('design_cfm','osa_cfm','esp','motor_hp')):raise ValueError(f'{tag}: verified equipment requires at least one reviewed design value')
        for field in ('design_cfm','osa_cfm','esp','motor_hp'):
            v=r.get(field)
            if v is None or v=='':continue
            try:n=float(v)
            except (ValueError,TypeError):raise ValueError(f'{tag}: invalid {field}')
            if not math.isfinite(n) or n<0 or n>1_000_000:raise ValueError(f'{tag}: out-of-range {field}')
        if r.get('design_cfm') not in (None,'') and r.get('osa_cfm') not in (None,'') and float(r['osa_cfm'])>float(r['design_cfm']):raise ValueError(f'{tag}: outside-air CFM exceeds total design CFM')

def populate_equipment(wb,records,selected):
    """Only verified records get populated. Original worksheet cells are mapped by their actual labels."""
    mapping={'Air Moving Equipment.xlsx':('G3','G17','G18','G21','T4'),
             'Exhaust Fans _Std._.xlsx':('H3','H17',None,'H21','U4')}
    count=0
    for rec in records:
        if rec.get('status')!='VERIFIED':continue
        tag=str(rec.get('tag','')).strip().upper()
        kind='Exhaust Fans _Std._.xlsx' if tag.startswith('EF-') else 'Air Moving Equipment.xlsx' if re.match(r'^(AHU|RTU|OAU|DOAS|AC)-',tag) else None
        if not kind or kind not in selected:continue
        before=set(wb.sheetnames);add_template(wb,LOOKUP[kind]);created=[n for n in wb.sheetnames if n not in before]
        if not created:continue
        ws=wb[created[0]];ws.title=sheet_name(wb,tag) if tag != ws.title else tag
        cells=mapping[kind];ws[cells[0]]=tag
        for key,addr in [('design_cfm',cells[1]),('osa_cfm',cells[2]),('esp',cells[3]),('motor_hp',cells[4])]:
            if addr and rec.get(key) not in (None,''):ws[addr]=float(rec[key])
        count+=1
    return count

def build(payload):
    validate_payload(payload)
    project=str(payload.get('project','')).strip()
    if not project:raise ValueError('Project name is required')
    selected=payload.get('templates',[])
    if not isinstance(selected,list) or not selected:raise ValueError('Choose at least one template')
    if any(t not in LOOKUP for t in selected):raise ValueError('Unknown template selection')
    wb=Workbook();wb.remove(wb.active)
    records=payload.get('records',[])
    if not isinstance(records,list):raise ValueError('Invalid review records')
    for name in selected:
        if name in ('Air Moving Equipment.xlsx','Exhaust Fans _Std._.xlsx') and any(
            isinstance(r,dict) and r.get('status')=='VERIFIED' and ((name=='Exhaust Fans _Std._.xlsx' and str(r.get('tag','')).upper().startswith('EF-')) or
            (name=='Air Moving Equipment.xlsx' and re.match(r'^(AHU|RTU|OAU|DOAS|AC)-',str(r.get('tag','')).upper()))) for r in records):
            continue
        add_template(wb,LOOKUP[name])
    populated=populate_equipment(wb,records,selected)
    if not wb.sheetnames:
        raise ValueError('No worksheets were generated')
    meta=wb.create_sheet('ABP BUILD INFO',0)
    fields=[('PROJECT',project),('LOCATION',str(payload.get('location',''))),('PROJECT STANDARD',str(payload.get('standard','Commercial'))),('AIRFLOW TOLERANCE',0.05 if payload.get('standard')=='USACE' else 0.10),('REPORT STATUS','PRE-FIELD DRAFT / NOT CERTIFIED'),('POPULATED VERIFIED UNIT SHEETS',populated),('UNVERIFIED EQUIPMENT COUNT',sum(r.get('status')=='UNVERIFIED' for r in records)),('EXCLUDED EQUIPMENT COUNT',sum(r.get('status')=='EXCLUDED' for r in records)),('SOURCE DOCUMENTS','Review all takeoffs against latest mechanical revision'),('MOTOR FLA','Leave blank until field nameplate verification'),('MAKE / MODEL','Leave blank unless approved submittal exception is verified'),('USACE DALT','Verify approved DALT before TAB' if payload.get('standard')=='USACE' else 'Not automatically required'),('ABP','Air Balance Professionals LLC • Macon, MS • NEBB #3861'),('APPROVAL','Andrew J. Fultz — approval not implied by this draft'),('VERIFIED RECORDS',sum(r.get('status')=='VERIFIED' for r in records)),('SOURCE REVISION STATUS','NOT AUTOMATICALLY VERIFIED — CHECK LATEST M-SHEETS'),('AUTOMATIC EXTRACTION LIMIT','Only labeled text suggestions; not a complete mechanical takeoff')]
    for i,(k,v) in enumerate(fields,1):meta.cell(i,1,k).font=Font(bold=True,color='FFFFFF');meta.cell(i,1).fill=PatternFill('solid',fgColor='17345B');meta.cell(i,2,excel_safe(v) if isinstance(v,str) else v)
    meta.column_dimensions['A'].width=26;meta.column_dimensions['B'].width=86
    tags=payload.get('tags',[])
    if records:tags=[str(r.get('tag','')) for r in records]
    if tags:
        s=wb.create_sheet('TAKEOFF REVIEW',1)
        for col,h in enumerate(['EQUIPMENT TAG','DESIGN CFM','OSA CFM','ESP (in.w.c.)','MOTOR HP','SOURCE SHEET / REVISION','REVIEW STATUS','OCCURRENCES'],1):s.cell(1,col,h).font=Font(bold=True,color='FFFFFF');s.cell(1,col).fill=PatternFill('solid',fgColor='17345B')
        for row,tag in enumerate(tags[:500],2):
            rec=records[row-2] if row-2<len(records) else {}
            s.cell(row,1,excel_safe(str(tag)[:80]))
            for col,key in [(2,'design_cfm'),(3,'osa_cfm'),(4,'esp'),(5,'motor_hp')]:
                value=rec.get(key)
                if value not in (None,''):
                    try:s.cell(row,col,float(value))
                    except (ValueError,TypeError):pass
            s.cell(row,6,excel_safe((str(rec.get('source',''))+' · '+str(rec.get('reference','')))[:180]))
            s.cell(row,7,excel_safe(str(rec.get('status','UNVERIFIED'))[:100]));s.cell(row,8,len(rec.get('occurrences',[])))
        s.auto_filter.ref=f'A1:H{len(tags[:500])+1}'
        s.freeze_panes='B2'
        if records:
            e=wb.create_sheet('SOURCE EVIDENCE',2)
            for c,h in enumerate(['TAG','SOURCE FILE','LOCATION','EXTRACTED CONTEXT'],1):e.cell(1,c,h).font=Font(bold=True,color='FFFFFF');e.cell(1,c).fill=PatternFill('solid',fgColor='17345B')
            i=2
            for rec in records[:500]:
                for occurrence in rec.get('occurrences',[rec]):
                    for c,val in enumerate([rec.get('tag',''),occurrence.get('source',''),occurrence.get('reference',''),occurrence.get('evidence','')],1):e.cell(i,c,excel_safe(str(val)[:1000]))
                    i+=1
            for col,width in [('A',22),('B',44),('C',26),('D',100)]:e.column_dimensions[col].width=width
            e.freeze_panes='A2' 
        for c,w in zip('ABCDEFG',[25,18,18,22,16,34,36]):s.column_dimensions[c].width=w
    if records:
        suggestions=wb.create_sheet('EXTRACTION CANDIDATES')
        headers=['TAG','SUGGESTED FIELD','CANDIDATE VALUE','SOURCE FILE','LOCATION','EXCERPT','STATUS']
        for j,h in enumerate(headers,1):suggestions.cell(1,j,h).font=Font(bold=True,color='FFFFFF');suggestions.cell(1,j).fill=PatternFill('solid',fgColor='17345B')
        k=2
        for rec in records:
            for item in rec.get('candidates',[]):
                for field,value in item.get('values',{}).items():
                    for j,v in enumerate([rec.get('tag',''),field,value,item.get('source',''),item.get('reference',''),item.get('evidence',''),'UNVERIFIED - REVIEW SOURCE'],1):suggestions.cell(k,j,excel_safe(v) if isinstance(v,str) else v)
                    k+=1
        for col,width in zip('ABCDEFG',[24,24,20,38,24,85,32]):suggestions.column_dimensions[col].width=width
        suggestions.freeze_panes='A2'
        checks=wb.create_sheet('AIRFLOW CHECK',3)
        for col,label in enumerate(['EQUIPMENT TAG','DESIGN CFM','MEASURED CFM','% DESIGN','TOLERANCE','RESULT'],1):
            c=checks.cell(1,col,label);c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='17345B')
        for i,rec in enumerate(records[:500],2):
            checks.cell(i,1,excel_safe(str(rec.get('tag',''))))
            if rec.get('status')=='VERIFIED' and rec.get('design_cfm') not in (None,''):
                try:checks.cell(i,2,float(rec['design_cfm']))
                except (TypeError,ValueError):pass
            checks.cell(i,4,f'=IF(OR(B{i}="",C{i}="",B{i}=0),"",C{i}/B{i})').number_format='0.0%'
            checks.cell(i,5,0.05 if payload.get('standard')=='USACE' else 0.10).number_format='0.0%'
            checks.cell(i,6,f'=IF(D{i}="","NOT TESTED",IF(ABS(D{i}-1)<=E{i},"WITHIN TARGET","REVIEW"))')
        for col,width in zip('ABCDEF',[25,18,18,18,18,22]):checks.column_dimensions[col].width=width
        checks.freeze_panes='B2'
    wb.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True)
    out=io.BytesIO();wb.save(out);return out.getvalue()

PAGE='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ABP TAB Report Builder</title><style>
:root{color-scheme:dark;--bg:#0b1422;--panel:#131f30;--line:#304259;--ink:#edf3fc;--muted:#a9bad0;--accent:#67d4c3;--blue:#77b8f8;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:90px}body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6}button,input,select{font:inherit}button,a,input,select{touch-action:manipulation}[hidden]{display:none!important}a{color:var(--blue)}header{display:flex;align-items:center;gap:20px;max-width:1200px;margin:auto;padding:22px 28px;border-bottom:1px solid var(--line)}header img{width:180px;height:60px;object-fit:contain;background:#fff;padding:8px;border-radius:8px}.brand-name{font-weight:750;font-size:13px}.brand-sub{color:var(--muted);font-size:12px}.wrap{max-width:1200px;margin:auto;padding:32px 28px 48px}.hero{padding:8px 0 30px}.hero-row{display:flex;justify-content:space-between;align-items:end;gap:24px}.eyebrow{color:var(--accent);font-size:11px;font-weight:750;letter-spacing:1.8px;text-transform:uppercase}h1{font-size:clamp(28px,4vw,42px);letter-spacing:-1.4px;line-height:1.15;margin:12px 0}p{margin:10px 0 18px}.hero p{max-width:630px;color:var(--muted);font-size:15px}.draft-pill{border:1px solid #395566;background:#172d36;color:#a5e5da;padding:7px 12px;border-radius:6px;font-size:11px;white-space:nowrap}.workspace-nav{position:sticky;top:0;z-index:5;display:flex;gap:6px;background:#0b1422f5;border-block:1px solid var(--line);padding:10px 0;margin:0 0 24px;backdrop-filter:blur(12px)}.workspace-nav a{color:var(--muted);text-decoration:none;padding:8px 14px;border-radius:6px;font-size:12px;font-weight:650}.workspace-nav a:hover,.workspace-nav a:focus{background:#22354b;color:#fff}.workspace-layout{display:grid;grid-template-columns:minmax(0,1fr) 252px;gap:24px;align-items:start}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:26px;margin-bottom:20px}.card h2{display:flex;align-items:center;gap:12px;font-size:18px;letter-spacing:-.3px;margin:0 0 18px}.step{display:inline-grid;place-items:center;width:30px;height:30px;flex-shrink:0;border:1px solid #3b536e;border-radius:7px;color:var(--blue);font-size:11px;letter-spacing:.5px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}label{display:block;margin:10px 0 16px;font-size:12px;font-weight:650;color:#ccdaec}input[type=text],input[type=search],select,.review-table input{display:block;margin-top:7px;width:100%;min-height:44px;padding:10px 12px;border:1px solid #455973;border-radius:7px;background:#0d1828;color:var(--ink)}input::placeholder{color:#899db7}input[type=checkbox]{accent-color:var(--accent);width:16px;height:16px;vertical-align:middle}input[type=file]{display:block;width:100%;margin:9px 0;padding:22px 16px;background:#101e30;border:1px dashed #567594;border-radius:9px;color:var(--muted);font-size:12px}input[type=file]::file-selector-button{background:#263b53;color:#edf5ff;padding:9px 12px;border:1px solid #4b637e;border-radius:6px;margin-right:12px;cursor:pointer}button{background:#3b88d4;color:#fff;padding:10px 16px;min-height:42px;font-weight:650;font-size:12px;border:1px solid #65a8e6;border-radius:7px;cursor:pointer;transition:background .15s}button:hover{background:#4c9be4}button:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #79bfff;outline-offset:3px}#selectall,#clear,#saveproject{background:#1b2d43;border-color:#415772;color:#dce9fa}#selectall:hover,#clear:hover,#saveproject:hover{background:#2a415b}#generate{background:#68d3bd;border-color:#68d3bd;color:#092e2c;font-size:14px;min-width:235px;min-height:48px}#generate:hover{background:#88e5d1}small,.muted{color:var(--muted);font-weight:400}.card>p.muted{font-size:13px}.template-toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px}.template-toolbar input{margin:0;min-width:0;flex:1}.templates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:330px;overflow:auto;padding:3px}.template{display:flex;align-items:center;gap:9px;padding:12px;margin:0;min-height:48px;background:#101d2d;border:1px solid #354960;border-radius:7px;font-size:12px;font-weight:500;cursor:pointer;line-height:1.4}.template input{flex-shrink:0}.template:has(input:checked){background:#173b40;border-color:#4c9189;color:#d4fff3}.template:hover{border-color:#7ea5c9}.recommend-summary{font-size:12px;background:#11273a;border:1px solid #345773;padding:16px;border-radius:8px;margin:16px 0}.recommend-summary p{margin:8px 0}.recommend-item{padding:9px 0;border-top:1px solid #344b61;display:flex;gap:12px;justify-content:space-between}.recommend-item small{text-align:right;max-width:50%}.recommend-item em{display:inline-block;color:#f7cb88;font-size:10px;font-style:normal;margin-left:5px}.review-scroll{overflow:auto;max-height:420px;border:1px solid var(--line);border-radius:8px}.review-table{width:100%;border-collapse:collapse;font-size:12px}.review-table th{position:sticky;top:0;background:#25364b;text-align:left;z-index:1}.review-table td,.review-table th{padding:10px;border-bottom:1px solid var(--line)}.review-table input{min-width:82px;margin:0}.review-table select{min-width:120px;margin:0}.review-table tr:hover{background:#1b2c41}.tag{display:inline-block;background:#23415b;padding:3px 8px;border-radius:5px;margin:3px}.warn{color:#ffd18c}.success{color:#97e4c3}#scanstatus,#status,#reference-summary{font-size:13px;overflow-wrap:anywhere}#status:not(:empty),#reference-summary:not(:empty){border-left:3px solid var(--blue);background:#10263a;padding:14px;margin-top:18px;border-radius:0 6px 6px 0}.summary{position:sticky;top:88px;padding:22px;background:#101e2e;border:1px solid var(--line);border-radius:12px}.summary h2{font-size:12px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted);margin:0 0 18px}.summary-project{font-size:20px;font-weight:700;line-height:1.3;overflow-wrap:anywhere;margin-bottom:5px}.summary-location{color:var(--muted);font-size:12px}.summary dl{margin:24px 0}.summary dl div{display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding:12px 0;font-size:12px}.summary dt{color:var(--muted)}.summary dd{margin:0;font-weight:650;text-align:right}.summary-note{border-top:1px solid var(--line);padding-top:16px;font-size:12px;color:var(--muted)}.summary-note strong{display:block;color:var(--accent);margin-bottom:6px}.footer-note{font-size:12px;color:var(--muted);margin:22px 2px;max-width:800px}.restore-review{margin:18px 0;border-top:1px solid var(--line);padding-top:16px}.restore-review summary{cursor:pointer;color:var(--muted);font-size:12px}.skip-link{position:absolute;top:-60px;left:16px;z-index:20;background:#fff;color:#123;padding:10px}.skip-link:focus{top:10px}#template-count{font-size:12px;color:var(--accent);margin:8px 0}#reference-panel>p{color:var(--muted);font-size:13px}
@media(max-width:950px){.workspace-layout{grid-template-columns:minmax(0,1fr)}.summary{position:static;display:none}.hero-row{align-items:start}.draft-pill{white-space:normal;max-width:170px}.brand-sub{max-width:190px}.review-table{min-width:720px}}
@media(max-width:600px){header{padding:16px;gap:12px;flex-wrap:wrap}header img{width:150px;height:52px}.brand-name{font-size:11px}.brand-sub{font-size:10px;max-width:150px}header form{margin-left:0!important}header form button{min-height:36px}.wrap{padding:24px 16px}.hero-row{display:block}.draft-pill{display:inline-block;max-width:none;margin-top:8px}.hero p{font-size:13px}.workspace-nav{overflow:auto;white-space:nowrap;gap:0}.workspace-nav a{padding:8px 10px}.card{padding:20px 16px}.grid{grid-template-columns:1fr;gap:0}.templates{grid-template-columns:1fr}.template-toolbar{flex-wrap:wrap}.template-toolbar input{flex-basis:100%}.recommend-item{display:block}.recommend-item small{display:block;text-align:left;max-width:none}#generate{width:100%}.review-scroll{max-height:500px}.review-table{min-width:760px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
</style><body><a class="skip-link" href="#project-card">Skip to report builder</a><header><img src="/logo.png" alt="Air Balance Professionals company logo"><div><div class="brand-name">Air Balance Professionals</div><div class="brand-sub">Technical reporting workspace &nbsp;·&nbsp; NEBB #3861</div></div><form action="/logout" method="post" style="margin-left:auto"><button type="submit" style="background:#eff6ff;color:#16508c;border:1px solid #c8daef;min-height:38px;padding:8px 12px;white-space:nowrap">Sign out</button></form></header><main class="wrap"><section class="hero" aria-label="Report builder introduction"><div class="hero-row"><div><div class="eyebrow">ABP / Field engineering tools</div><h1>TAB Report Builder</h1><p>From project documents to a field-ready draft. Review the design, choose your worksheets, and build your Excel report.</p></div><span class="draft-pill">PRE-FIELD WORKSPACE</span></div></section><nav class="workspace-nav" aria-label="Report sections"><a href="#project-card">01 Project</a><a href="#basis-card">02 Report basis</a><a href="#template-panel" id="templates-nav">03 Worksheets</a><a href="#build-card">04 Export</a></nav><div class="workspace-layout"><div><div class="card" id="project-card"><h2><span class="step">01</span> Project details</h2><div class="grid"><label>Project name<input id="project" type="text" placeholder="Project / facility name"></label><label>Location<input id="location" type="text" placeholder="City, State"></label></div><label>Standard<select id="standard"><option value="Commercial">Commercial · ±10% target</option><option value="USACE">USACE · ±5% target (DALT prerequisite)</option></select></label></div><div class="card" id="basis-card"><h2><span class="step">02</span> Choose your starting point</h2><label>Build method<select id="buildmethod"><option value="sources">Build from source documents and master templates</option><option value="reference">Use an approved report as the design and layout reference</option></select></label><div id="reference-panel" hidden><p>Use a report for this same project whose design values and equipment list you have approved. This keeps its report pages, grouped Design/Actual columns, formulas and branding. Field measurements, serial numbers and signoffs are cleared. Source scans do not overwrite this report.</p><label>Approved reference workbook<input id="reference-file" type="file" accept=".xlsx"></label><button id="inspect-reference" type="button">Review reference report</button><div id="reference-summary" role="status" aria-live="polite"></div><label><input id="reference-approved" type="checkbox"> Use this reference’s equipment list and design values for this project, including differences from drawings.</label></div></div><div class="card" id="source-panel"><h2>Upload source documents</h2><input id="files" type="file" accept=".pdf,.xlsx,.csv" multiple><p class="muted">PDF mechanical sheets, approved submittals, Excel and CSV schedules. Text-based extraction only; always review the M-sheet takeoff and latest revision.</p><button id="scan">Scan uploaded files</button><p id="scanstatus" role="status" aria-live="polite"></p><div id="tags"></div><div id="review"></div></div><div class="card" id="template-panel"><h2><span class="step">03</span> Choose report templates</h2><p class="muted">Select the actual ABP worksheets to include. Formatting and formulas are copied from the supplied masters.</p><div class="template-toolbar"><input id="template-search" type="search" aria-label="Search report templates" placeholder="Find a worksheet…"><button id="selectall" type="button">Select all</button> <button id="clear" type="button">Clear</button></div><div id="template-recommendations" class="recommend-summary" aria-live="polite">Scan source documents to get automatic template recommendations. You can always change the selections below.</div><p id="template-count" aria-live="polite"></p><div class="templates" id="templates"></div></div><div class="card" id="build-card"><h2><span class="step">04</span> Export your draft</h2><p class="muted" id="build-description">Creates a draft workbook with original template sheets and individual air-moving/exhaust-fan sheets for detected units. Only records explicitly marked Verified populate equipment sheets. All detected tags remain in the review log; no field measurements or approvals are fabricated.</p><details class="restore-review" id="review-tools"><summary>Save or restore project progress</summary><p class="muted">Keep your reviewed tags and worksheet selections for next time.</p><button id="saveproject" type="button">Save project review (.json)</button> <label>Restore saved review<input id="loadproject" type="file" accept=".json,application/json"></label></details><button id="generate">Download Excel draft ↓</button><p id="status" role="status" aria-live="polite"></p></div></div><aside class="summary" aria-label="Report summary"><h2>Your report</h2><div id="summary-project" class="summary-project">Untitled project</div><div id="summary-location" class="summary-location">Add a location to get started</div><dl><div><dt>Report basis</dt><dd id="summary-basis">Source documents</dd></div><div><dt id="summary-count-label">Worksheets</dt><dd id="summary-count">—</dd></div><div><dt>Equipment entries</dt><dd id="summary-equipment">0</dd></div><div><dt>Output</dt><dd>Excel · .xlsx</dd></div></dl><div class="summary-note"><strong>Ready for field work</strong>Your draft keeps design information separate from measurements. Field readings and approvals are completed after testing.</div></aside></div><p class="footer-note"><span aria-hidden="true">ⓘ</span> Pre-field draft only. All extracted values require review; final TAB reports require engineering verification and field signoff.</p></main><script>

let inspectedReference=null;
function referenceForm(){const f=$('reference-file').files[0];if(!f)throw Error('Choose an approved reference workbook');if(f.size>8000000)throw Error('Reference workbook exceeds 8 MB');const form=new FormData();form.append('reference',f);return form}
function resetReference(){inspectedReference=null;$('reference-approved').checked=false;$('reference-summary').textContent='Review the selected reference before building.'}
async function generateReference(){try{if(!inspectedReference||inspectedReference!==$('reference-file').files[0])throw Error('Review the selected reference first');if(!$('reference-approved').checked)throw Error('Confirm the reference equipment list and design values');if(!$('project').value.trim())throw Error('Enter the project name');$('generate').disabled=true;$('status').textContent='Building report from approved reference...';const form=referenceForm();form.append('project',$('project').value);form.append('location',$('location').value);form.append('approved','true');const r=await fetch('/api/reference/build',{method:'POST',body:form});if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=($('project').value.replace(/[^a-z0-9_-]+/gi,'_')||'ABP')+'_PreField_TAB.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent='Report built from your approved reference. Design values and report layout retained; field measurements and signoffs cleared.'}catch(e){$('status').textContent=e.message}finally{$('generate').disabled=false}}
window.addEventListener('DOMContentLoaded',()=>{
 const sourceDescription=$('build-description').textContent; $('buildmethod').onchange=()=>{const ref=$('buildmethod').value==='reference';$('source-panel').hidden=ref;$('template-panel').hidden=ref;$('build-description').textContent=ref?'Build the approved reference report with its design data and page layout. Actual field readings and signoffs will be blank.':sourceDescription;$('reference-panel').hidden=$('buildmethod').value!=='reference';$('scan').disabled=$('buildmethod').value==='reference';$('saveproject').disabled=$('buildmethod').value==='reference';$('loadproject').disabled=$('buildmethod').value==='reference';$('template-recommendations').textContent=$('buildmethod').value==='reference'?'Reference mode uses the approved workbook’s sheets. Template selections below are ignored.':'Scan source documents to get template recommendations.'};
 $('reference-file').onchange=resetReference;
 $('inspect-reference').onclick=async()=>{resetReference();$('inspect-reference').disabled=true;$('reference-summary').textContent='Checking workbook layouts and equipment…';try{const file=$('reference-file').files[0],form=referenceForm();const r=await fetch('/api/reference/inspect',{method:'POST',body:form});const info=await r.json();if(!r.ok)throw Error(info.error);if(file!==$('reference-file').files[0])return;inspectedReference=file;referenceEntryCount=info.units.length;$('reference-summary').textContent=info.sheets.length+' report sheets: '+info.sheets.join(', ')+'. '+info.units.length+' equipment entries: '+info.units.map(x=>x.tag).join(', ')+'. '+info.note}catch(e){$('reference-summary').textContent=e.message}finally{$('inspect-reference').disabled=false;updateWorkspace()}};
});

let tags=[],records=[];const $=id=>document.getElementById(id);async function init(){let t=await(await fetch('/api/templates')).json();$('templates').innerHTML=t.map(x=>`<label class="template"><input type="checkbox" value="${x.replaceAll('&','&amp;').replaceAll('"','&quot;')}">${x.replaceAll('&','&amp;').replaceAll('<','&lt;')}</label>`).join('');for(const box of document.querySelectorAll('.template input')){if(/project information|notes|air moving equipment|supply diffusers/i.test(box.value))box.checked=true}}init().catch(()=>{$('template-count').textContent='Templates could not load. Refresh the page to try again.'});$('selectall').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=true);$('clear').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=false);
$('scan').onclick=async()=>{let files=$('files').files;if(!files.length){$('scanstatus').textContent='Choose files first';return}let form=new FormData();for(let f of files)form.append('files',f);$('scan').disabled=true;$('scanstatus').textContent='Reading files...';try{let r=await fetch('/api/scan',{method:'POST',body:form});let data=await r.json();if(!r.ok)throw Error(data.error);tags=data.tags||[];records=data.records||[];$('scanstatus').textContent=`Found ${tags.length} unique equipment tags in ${data.characters.toLocaleString()} extracted characters. Candidate measurements are recorded separately and must be verified.`+(data.warnings.length?' Warnings: '+data.warnings.join(' | '):'');$('tags').innerHTML='';renderReview();let recommendation=await(await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags,signals:data.signals||[]})})).json();if(!Array.isArray(recommendation.recommended))throw Error('Template recommendations unavailable');let chosen=new Set(recommendation.recommended.map(x=>x.name));document.querySelectorAll('.template input').forEach(x=>x.checked=chosen.has(x.value));let safe=x=>String(x||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');$('template-recommendations').innerHTML='<strong>Recommended '+recommendation.recommended.length+' ABP templates</strong><p>Selected automatically based on the uploaded documents. Review and change any checked boxes before building your report.</p>'+recommendation.recommended.map(x=>'<div class="recommend-item"><span>'+safe(x.name)+(x.review?' <em>Review type</em>':'')+'</span><small>'+safe(x.reason)+'</small></div>').join('')+'<p class="muted">'+safe(recommendation.review_note)+'</p>'}catch(e){$('scanstatus').textContent=e.message}finally{$('scan').disabled=false}};
function renderReview(){let safe=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');$('review').innerHTML='<p>Review detected tags and manually enter verified design values. No CFM or ESP is inferred from unverified text.</p><div class="review-scroll"><table class="review-table"><thead><tr><th>Tag</th><th>Design CFM</th><th>OSA CFM</th><th>ESP</th><th>HP</th><th>Review</th><th>Occurrences</th><th>Suggestions</th><th>Source</th></tr></thead><tbody>'+records.map((r,i)=>`<tr><td>${safe(r.tag)}</td>${['design_cfm','osa_cfm','esp','motor_hp'].map(k=>`<td><input type="number" step="any" data-row="${i}" data-field="${k}" value="${safe(r[k])}"></td>`).join('')}<td><select data-status="${i}"><option value="UNVERIFIED">Unverified</option><option value="VERIFIED">Verified</option><option value="EXCLUDED">Excluded</option></select></td><td>${r.occurrences?.length||1}</td><td title="Unverified extracted suggestions">${safe((r.candidates||[]).map(c=>Object.entries(c.values).map(([k,v])=>k+': '+v).join(', ')).join(' | '))}</td><td title="${safe(r.evidence)}">${safe(r.source)} · ${safe(r.reference)}</td></tr>`).join('')+'</tbody></table></div>';document.querySelectorAll('[data-row]').forEach(el=>el.oninput=()=>{records[+el.dataset.row][el.dataset.field]=el.value});document.querySelectorAll('[data-status]').forEach(el=>{el.value=records[+el.dataset.status].status||'UNVERIFIED';el.onchange=()=>{records[+el.dataset.status].status=el.value}})}
function projectPayload(){return {project:$('project').value,location:$('location').value,standard:$('standard').value,tags,records,templates:[...document.querySelectorAll('.template input:checked')].map(x=>x.value)}}
$('saveproject').onclick=()=>{const data=JSON.stringify({format:'ABP-PREFIELD-REVIEW',version:1,...projectPayload()},null,2);const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ABP_Project_Review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)};
$('loadproject').onchange=async ev=>{try{const f=ev.target.files[0];if(!f)return;if(f.size>2000000)throw Error('Project review file exceeds 2 MB');const data=JSON.parse(await f.text());if(data.format!=='ABP-PREFIELD-REVIEW'||data.version!==1||!Array.isArray(data.records)||data.records.length>500||!Array.isArray(data.templates))throw Error('Invalid ABP project review');$('project').value=String(data.project||'');$('location').value=String(data.location||'');$('standard').value=data.standard==='USACE'?'USACE':'Commercial';records=data.records;tags=records.map(r=>r.tag);document.querySelectorAll('.template input').forEach(x=>x.checked=data.templates.includes(x.value));renderReview();$('status').textContent='Saved review restored. Recheck verification and source revisions before building your report.'}catch(e){$('status').textContent=e.message}};
$('generate').onclick=async()=>{if($('buildmethod').value==='reference'){await generateReference();return}let payload=projectPayload();if(!payload.project.trim()){$('status').textContent='Add a project name before building your draft.';$('project').focus();return}if(!payload.templates.length){$('status').textContent='Select at least one report worksheet.';$('template-panel').scrollIntoView();return}$('generate').disabled=true;$('status').textContent='Building your report...';try{let r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){let e=await r.json();throw Error(e.error)}let blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(payload.project.replace(/[^a-z0-9_-]+/gi,'_')||'ABP')+'_PreField_TAB.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent='Report built successfully (draft). Review source revisions, flagged records, and formulas before field use.'}catch(e){$('status').textContent=e.message}finally{$('generate').disabled=false}};

function updateWorkspace(){
 const reference=$('buildmethod').value==='reference';
 $('summary-project').textContent=$('project').value.trim()||'Untitled project';
 $('summary-location').textContent=$('location').value.trim()||'Add a location to get started';
 $('summary-basis').textContent=reference?'Approved reference':'Source documents';
 $('summary-count-label').textContent=reference?'Reference':'Worksheets';
 const selected=document.querySelectorAll('.template input:checked').length;
 $('summary-count').textContent=reference?(inspectedReference?'Reviewed':'Needs review'):selected;
 $('summary-equipment').textContent=reference?(inspectedReference?String(referenceEntryCount):'—'):String(records.length);
 const query=$('template-search').value.trim().toLowerCase();const matching=[...document.querySelectorAll('.template')].filter(el=>el.textContent.toLowerCase().includes(query)).length;
 $('template-count').textContent=query?matching+' matching worksheets · '+selected+' selected':selected+' worksheets selected';
 $('review-tools').hidden=reference;$('templates-nav').hidden=reference;
 $('standard').closest('label').hidden=reference;
}
let referenceEntryCount=0;
document.addEventListener('input',updateWorkspace);document.addEventListener('change',updateWorkspace);
document.addEventListener('click',()=>queueMicrotask(updateWorkspace));
new MutationObserver(updateWorkspace).observe($('templates'),{childList:true});
new MutationObserver(updateWorkspace).observe($('reference-summary'),{childList:true});
new MutationObserver(updateWorkspace).observe($('review'),{childList:true});
$('template-search').addEventListener('input',ev=>{
 const query=ev.target.value.trim().toLowerCase();let visible=0;
 document.querySelectorAll('.template').forEach(el=>{el.hidden=!el.textContent.toLowerCase().includes(query);if(!el.hidden)visible++});
 $('template-count').textContent=visible+' matching worksheets · '+document.querySelectorAll('.template input:checked').length+' selected';
});
updateWorkspace();
</script></body></html>'''
# These resources are immutable during a running deployment; encode once per process.
PAGE_BYTES=PAGE.encode('utf-8')
TEMPLATE_LIST_BYTES=json.dumps(list(LOOKUP)).encode('utf-8')
# LAN mode is explicitly opt-in. Authenticated session cookies protect the app and API routes.
LAN_MODE = '--lan' in sys.argv
ACCESS_PASSWORD = os.environ.get('ABP_ACCESS_PASSWORD', '').strip()
# Do not log passwords or password-derived fingerprints.
print('ABP auth configuration: '+('password loaded' if ACCESS_PASSWORD else 'PASSWORD MISSING'), flush=True)

# Stateless HMAC-signed session cookies; changing ABP_ACCESS_PASSWORD revokes existing sessions.
SESSION_LIFETIME=8*60*60
FAILED_LOGINS={}
LOGIN_LOCK=threading.Lock()
LOGIN_HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · ABP Report Builder</title><style>:root{color-scheme:dark;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#f2f6ff;background:#071326}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:22px 15px;background:radial-gradient(ellipse at 10% 20%,#133e78,transparent 45%),radial-gradient(ellipse at 95% 85%,#174c94,transparent 38%),#080f22}.panel{max-width:460px;width:100%;background:linear-gradient(145deg,#1b2a46,#101a30);padding:36px;border:1px solid #506b8c;border-radius:20px;box-shadow:0 25px 80px #0008}.logo{display:block;width:250px;max-width:100%;height:92px;object-fit:contain;padding:10px 16px;background:#fff;border-radius:12px;margin:0 auto 27px}.tag{font-size:11px;font-weight:800;letter-spacing:1.8px;text-transform:uppercase;color:#68c7ff;margin:0 0 10px}h1{margin:0 0 9px;font-size:32px;letter-spacing:-.8px;color:#f5f8ff}p{color:#c1d0e4;font-size:14px;line-height:1.6;margin:0 0 23px}label{display:block;font-weight:700;font-size:13px;color:#edf4ff;margin:16px 0 8px}input{width:100%;min-height:51px;border:1px solid #5d7394;border-radius:10px;font:inherit;padding:12px 14px;background:#182640;color:#fff}input::placeholder{color:#a5b5cf}input:focus{outline:3px solid #248aff50;border-color:#56bdff}button[type=submit]{width:100%;border:1px solid #53aaff;background:linear-gradient(#258cff,#095fca);color:white;border-radius:10px;font-size:15px;font-weight:800;min-height:52px;cursor:pointer;margin-top:25px;box-shadow:0 7px 19px #0757be55}button[type=submit]:hover{background:#258cff}.error{padding:13px;background:#61313d;border:1px solid #bd6a77;color:#ffe3e7;border-radius:9px;font-size:13px;margin:0 0 20px}.note{color:#afc1db;font-size:12px;border-top:1px solid #50617e;margin-top:27px;padding-top:21px;line-height:1.6;text-align:center}@media(max-width:480px){.panel{padding:26px 22px}.logo{width:215px}}</style></head><body><main class="panel"><img class="logo" src="/logo.png" alt="Air Balance Professionals logo"><div class="tag">Secure reporting workspace</div>
<h1>Welcome back</h1><p>Sign in to access the Air Balance Professionals TAB Report Builder.</p>
{{ERROR}}<form action="/login" method="post"><input type="hidden" name="csrf" value="{{CSRF}}"><label for="user">Username</label><input id="user" name="username" autocomplete="username" required autofocus placeholder="Enter your username">
<label for="pass">Password</label><input id="pass" name="password" type="password" autocomplete="current-password" required placeholder="Enter your password">
<button type="submit">Sign in to Report Builder →</button></form><div class="note">Access is limited to authorized ABP team members. Contact your administrator for your credentials.</div></main></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def secure_request(self):
        return self.headers.get('X-Forwarded-Proto','').split(',')[0].strip().lower()=='https'
    def session_cookie(self,token,max_age=SESSION_LIFETIME):
        secure='; Secure' if self.secure_request() else ''
        return 'abp_session='+token+'; HttpOnly; SameSite=Lax; Path=/; Max-Age='+str(max_age)+secure
    def session_signature(self,stamp):
        secret=hashlib.sha256(('abp-session-v1:'+ACCESS_PASSWORD).encode()).digest()
        return hmac.new(secret,stamp.encode(),hashlib.sha256).hexdigest()
    def authorized(self):
        if not LAN_MODE:return True
        cookie=self.headers.get('Cookie','')
        match=re.search(r'(?:^|;\s*)abp_session=(\d{1,12})\.([a-f0-9]{64})(?:;|$)',cookie)
        if not match or not ACCESS_PASSWORD:return False
        stamp,signature=match.groups()
        try:
            age=time.time()-int(stamp)
            return 0<=age<SESSION_LIFETIME and secrets.compare_digest(signature,self.session_signature(stamp))
        except (ValueError,OverflowError):return False
    def redirect(self,url,extra_headers=None):
        self.send_response(303)
        self.send_header('Location',url)
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length','0')
        if extra_headers:
            for k,v in extra_headers:self.send_header(k,v)
        self.end_headers()
    def login_page(self,error=False):
        notice=('<div class="error" role="alert">Login form expired or blocked by your browser. Open a fresh sign-in tab and try again.</div>' if error=='session' else '<div class="error" role="alert">Too many attempts. Wait five minutes before trying again.</div>' if error=='limited' else '<div class="error" role="alert">Username or password not accepted. Username is abp; check the current password in Render.</div>') if error else ''
        # Signed, short-lived form token avoids cookies being overwritten by another tab.
        stamp=str(int(time.time()))
        nonce=secrets.token_hex(16)
        payload=stamp+'.'+nonce
        key=hashlib.sha256(('abp-login-csrf-v2:'+ACCESS_PASSWORD).encode()).digest()
        signature=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
        csrf=payload+'.'+signature
        html_page=LOGIN_HTML.replace('{{ERROR}}',notice).replace('{{CSRF}}',csrf)
        self.respond(html_page.encode(),'text/html; charset=utf-8')
    def valid_login_csrf(self,value):
        if not isinstance(value,str):return False
        match=re.fullmatch(r'(\d{10})\.([a-f0-9]{32})\.([a-f0-9]{64})',value)
        if not match:return False
        stamp,nonce,signature=match.groups()
        age=time.time()-int(stamp)
        if not 0<=age<3600:return False
        key=hashlib.sha256(('abp-login-csrf-v2:'+ACCESS_PASSWORD).encode()).digest()
        expected=hmac.new(key,(stamp+'.'+nonce).encode(),hashlib.sha256).hexdigest()
        return secrets.compare_digest(signature,expected)
    def same_origin(self):
        origin=self.headers.get('Origin')
        if not origin:return True
        try:
            parsed=urlsplit(origin)
            if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:return False
            # Render terminates HTTPS before forwarding requests to the container.
            # Trust the known public site URL rather than the proxy's internal Host.
            public_origin=os.environ.get('ABP_PUBLIC_ORIGIN','https://abp-report-builder-hie0.onrender.com').rstrip('/')
            if origin.lower()==public_origin.lower():return True
            # Preserve the previous behavior for the optional private LAN mode.
            return parsed.scheme in ('http','https') and parsed.netloc.lower()==self.headers.get('Host','').lower()
        except ValueError:return False
    def gate(self):
        if self.authorized():return False
        path=urlsplit(self.path).path
        if path.startswith('/api/'):
            self.respond(b'{"error":"Your session has expired. Please sign in again."}',code=401)
        else:self.redirect('/login')
        return True

    def respond(self,data,typ='application/json',code=200,filename=None,extra_headers=None):
        self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY');
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        if extra_headers:
            for key,value in extra_headers:self.send_header(key,value)
        self.end_headers();self.wfile.write(data)
    def do_HEAD(self):
        path=urlsplit(self.path).path
        if path=='/healthz':
            self.send_response(200)
        elif path in ('/','/login'):
            self.send_response(200 if self.authorized() else 303)
            if not self.authorized():self.send_header('Location','/login')
        else:
            self.send_response(404)
        self.send_header('Content-Length','0')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/healthz':
            self.respond(b'ok','text/plain; charset=utf-8');return
        if path=='/favicon.ico':
            self.send_response(204)
            self.send_header('Content-Length','0')
            self.end_headers()
            return
        if path=='/logo.png':
            logo=ROOT/'04_Company_Branding/ABP_Company_Logo.png'
            if logo.is_file():self.respond(logo.read_bytes(),'image/png')
            else:self.respond(b'Logo not installed','text/plain',404)
            return
        if path=='/login':
            if self.authorized():self.redirect('/')
            else:self.login_page()
            return
        if self.gate():return
        if path=='/':self.respond(PAGE_BYTES,'text/html; charset=utf-8')
        elif path=='/api/templates':self.respond(TEMPLATE_LIST_BYTES)
        else:self.respond(b'Not found','text/plain',404)
    def do_POST(self):
        path=urlsplit(self.path).path
        # Login uses a same-site double-submit token instead of a proxy-sensitive Origin check.
        # Browser origin headers can be altered by proxy/browser navigation.
        # Prevent cross-site logout via Fetch Metadata; session cookie is SameSite=Lax.
        if path=='/logout':
            if self.headers.get('Sec-Fetch-Site','').lower()=='cross-site':
                self.respond(b'{"error":"Cross-site logout not permitted"}',code=403);return
            self.redirect('/login',[('Set-Cookie',self.session_cookie('',0))]);return
        if path!='/login' and not self.same_origin():
            self.respond(b'{"error":"Request origin not allowed"}',code=403);return
        if path=='/login':
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<1 or n>4096:raise ValueError('Invalid login request')
                data=parse_qs(self.rfile.read(n).decode('utf-8','replace'),keep_blank_values=True)
                user=data.get('username',[''])[0].strip()
                password=data.get('password',[''])[0].strip()
                if not self.valid_login_csrf(data.get('csrf',[''])[0]):
                    self.login_page(error='session');return
                remote=self.client_address[0]
                now=time.time()
                with LOGIN_LOCK:
                    attempts=[t for t in FAILED_LOGINS.get(remote,[]) if now-t<300]
                    FAILED_LOGINS[remote]=attempts
                    limited=len(attempts)>=12
                valid=not limited and secrets.compare_digest(user,'abp') and bool(ACCESS_PASSWORD) and secrets.compare_digest(password,ACCESS_PASSWORD)
                if valid:
                    with LOGIN_LOCK:FAILED_LOGINS.pop(remote,None)
                    stamp=str(int(now))
                    token=stamp+'.'+self.session_signature(stamp)
                    self.redirect('/',[('Set-Cookie',self.session_cookie(token))])
                else:
                    with LOGIN_LOCK:FAILED_LOGINS.setdefault(remote,[]).append(now)
                    self.login_page(error='limited' if limited else 'credentials')
                return
            except (ValueError,IndexError):
                self.login_page(error='session');return
        if self.gate():return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>MAX_UPLOAD:raise ValueError('Upload limit is 40 MB')
            data=self.rfile.read(n)
            if path=='/api/suggest':
                if n>2_000_000:raise ValueError('Template suggestion request too large')
                request=json.loads(data)
                self.respond(json.dumps(suggested_templates(request.get('tags',[]),request.get('signals',[]))).encode());return
            if path=='/api/build':
                if n>8_000_000:raise ValueError('Build request exceeds 8 MB')
                payload=json.loads(data);out=build(payload);self.respond(out,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='ABP_PreField_TAB.xlsx');return
            if path in ('/api/reference/inspect','/api/reference/build'):
                from email.parser import BytesParser
                from email.policy import default
                ct=self.headers.get('Content-Type','')
                msg=BytesParser(policy=default).parsebytes(('Content-Type: '+ct+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+data)
                fields={p.get_param('name',header='content-disposition'):p.get_payload(decode=True) or b'' for p in msg.iter_parts()}
                reference=fields.get('reference',b'')
                if path.endswith('/inspect'):
                    self.respond(json.dumps(inspect_reference(reference)).encode());return
                if fields.get('approved')!=b'true':raise ValueError('Confirm that the reference design is authoritative for this project')
                out=build_reference(reference,fields.get('project',b'').decode(),fields.get('location',b'').decode())
                self.respond(out,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='ABP_PreField_TAB.xlsx');return
            if path=='/api/scan':
                from email.parser import BytesParser
                from email.policy import default
                ct=self.headers.get('Content-Type','')
                msg=BytesParser(policy=default).parsebytes(('Content-Type: '+ct+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+data)
                blobs=[(p.get_filename() or 'unnamed',p.get_payload(decode=True) or b'') for p in msg.iter_parts() if p.get_filename()]
                self.respond(json.dumps(read_sources(blobs)).encode());return
            self.respond(b'Not found','text/plain',404)
        except Exception as e:self.respond(json.dumps({'error':str(e)}).encode(),code=400)
if __name__=='__main__':
    args=[x for x in sys.argv[1:] if x!='--lan']
    port=int(args[0]) if args else 8765
    if LAN_MODE and (len(ACCESS_PASSWORD)<12 or ACCESS_PASSWORD.lower() in ('password12345','changeme12345')):
        sys.exit('Set ABP_ACCESS_PASSWORD to a strong password of at least 12 characters before --lan mode.')
    host='0.0.0.0' if LAN_MODE else '127.0.0.1'
    print('ABP Report Builder: '+('PRIVATE WI-FI MODE' if LAN_MODE else 'LOCAL MODE'))
    print(f'Computer: http://127.0.0.1:{port}')
    if LAN_MODE:
        print('Android: use http://YOUR_WINDOWS_WIFI_IP:'+str(port))
        print('Username: abp | Password: the ABP_ACCESS_PASSWORD you set')
        print('WARNING: On local Wi-Fi, HTTP is not encrypted. Use HTTPS for any internet deployment.')
    ThreadingHTTPServer((host,port),Handler).serve_forever()
