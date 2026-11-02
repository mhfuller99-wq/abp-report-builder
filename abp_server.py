#!/usr/bin/env python3
"""ABP local report builder. Uses original workbook templates; no cloud upload."""
import io,json,re,sys,zipfile,html,datetime,hashlib,math,csv,os,secrets,base64,ipaddress,socket
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import unquote
from openpyxl import Workbook,load_workbook
from openpyxl.workbook.properties import CalcProperties
from openpyxl.styles import Font,PatternFill
from openpyxl.utils import get_column_letter

ROOT=Path(__file__).resolve().parent
TEMPLATES=ROOT/'03_Workbooks_and_Master_Templates'
FILES=[p for p in sorted(TEMPLATES.glob('*.xlsx')) if p.name not in {'Blue Mountain - TAB Report.xlsx','CAFB Egress Shop - TAB Report.xlsx','CALEDONIA FEILDHOUSE TAB REPORT.xlsx','Cadence  Bank- Starkville MS .xlsx','New Hope Fieldhouse.xlsx','WEST LOWNDES FIELDHOUSE .xlsx'}]
LOOKUP={p.name:p for p in FILES}
TAGS=re.compile(r'\b(?:AHU|RTU|OAU|DOAS|CRU|MAU|ERV|HRV|FCU|VAV|IU|AC|DSS|DCU|EF|SF|RF|EUH|EWH|CUH|UH|FFU|LF)[-\s]?\d+(?:-[A-Z0-9]+)*\b',re.I)
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
 'diffusers':re.compile(r'\\b(?:SUPPLY|RETURN|EXHAUST)\\s+(?:AIR\\s+)?(?:DIFFUSER|GRILLE|REGISTER)\\s+SCHEDULE\\b|\\bAIR\\s+DEVICE\\s+SCHEDULE\\b',re.I),
 'exhaust_grilles':re.compile(r'\\bEXHAUST\\s+(?:AIR\\s+)?GRILLE\\s+SCHEDULE\\b',re.I),
 'erv':re.compile(r'\\b(?:ENERGY\\s+RECOVERY\\s+VENTILATOR|ERV)\\s+SCHEDULE\\b',re.I),
 'fan_coil':re.compile(r'\\bFAN\\s+COIL\\s+(?:UNIT\\s+)?SCHEDULE\\b',re.I),
 'water_coil':re.compile(r'\\b(?:HOT\\s+WATER|CHILLED\\s+WATER|HYDRONIC)\\s+COIL\\s+SCHEDULE\\b',re.I),
 'cooling_tower':re.compile(r'\\bCOOLING\\s+TOWER\\s+SCHEDULE\\b',re.I),
 'boiler':re.compile(r'\\bBOILER\\s+SCHEDULE\\b',re.I),
 'chiller':re.compile(r'\\bCHILLER\\s+SCHEDULE\\b',re.I),
 'kitchen_hood':re.compile(r'\\bKITCHEN\\s+(?:EXHAUST\\s+)?HOOD\\s+SCHEDULE\\b',re.I),
 'heat_exchanger':re.compile(r'\\bHEAT\\s+EXCHANGER\\s+SCHEDULE\\b',re.I),
 'filter_unit':re.compile(r'\\bFAN\\s+FILTER\\s+UNIT\\s+SCHEDULE\\b',re.I),
 'hydronic':re.compile(r'\\b(?:BALANCING\\s+VALVE|AUTO[- ]FLOW)\\s+SCHEDULE\\b',re.I),
 'dehumidifier':re.compile(r'\\bDEHUMIDIFIER\\s+SCHEDULE\\b',re.I),
 'air_moving':re.compile(r'\\b(?:AIR\\s+HANDLING\\s+UNIT|ROOFTOP\\s+UNIT|SUPPLY\\s+FAN|MAKEUP\\s+AIR\\s+UNIT)\\s+SCHEDULE\\b',re.I),
 'exhaust_fan':re.compile(r'\\bEXHAUST\\s+FAN\\s+SCHEDULE\\b',re.I),
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
        return any(re.match(r'^(?:'+prefixes+r')[- ]?\\d',tag) for tag in tags)
    if tagged('AHU|RTU|OAU|DOAS|MAU|AC|SF|RF|CRU') or 'air_moving' in signals:
        add('Air Moving Equipment.xlsx','Air-moving equipment tags or schedule heading')
    if tagged('EF') or 'exhaust_fan' in signals:
        add('Exhaust Fans _Std._.xlsx','Exhaust fan tags or schedule heading')
    if tagged('FCU|IU') or 'fan_coil' in signals:
        add('Fan Coil Units DX.xlsx','Fan-coil tags or schedule; confirm heating/cooling type',True)
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
    if 'kitchen_hood' in signals:add('Kitchen Hood.xlsx','Kitchen exhaust hood schedule heading')
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

PAGE='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ABP TAB Report Builder</title><style>body{margin:0;background:#0c1727;color:#e9f0fa;font:15px system-ui,Arial}header{background:#142743;border-bottom:1px solid #345075;padding:18px 5%;display:flex;align-items:center;gap:20px}header img{width:90px;background:white;border-radius:8px;padding:5px}.wrap{max-width:1080px;margin:28px auto;padding:0 18px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card{background:#16283f;border:1px solid #334b69;border-radius:14px;padding:22px;margin-bottom:18px}h1{font-size:24px;margin:0}h2{font-size:18px;margin:0 0 16px}label{display:block;margin:10px 0;color:#c7d7ed}input[type=text],select{box-sizing:border-box;width:100%;padding:12px;background:#0b1b30;border:1px solid #45617d;border-radius:8px;color:white;font:inherit}input[type=file]{width:100%;padding:18px;border:2px dashed #507ca9;border-radius:10px;box-sizing:border-box}button{background:#2578d3;color:white;border:0;border-radius:9px;padding:13px 20px;font:inherit;font-weight:700;cursor:pointer}button:disabled{opacity:.5}small,.muted{color:#a6b9d2}.templates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;max-height:310px;overflow:auto}.template{padding:9px;border:1px solid #38516c;border-radius:8px;font-size:12px;cursor:pointer}.template input{margin-right:8px}.review-table{width:100%;border-collapse:collapse;font-size:12px}.review-table td,.review-table th{padding:6px;border-bottom:1px solid #38516c;text-align:left}.review-table input{width:100%;box-sizing:border-box;background:#0b1b30;color:white;border:1px solid #45617d;border-radius:4px;padding:7px}.review-scroll{overflow:auto;max-height:380px}.tag{display:inline-block;margin:4px;padding:5px 9px;border-radius:20px;background:#24486b}.warn{color:#ffd48b}.success{color:#9fe0bc}a{color:#9ac8ff}@media(max-width:700px){.grid,.templates{grid-template-columns:1fr}header img{width:58px}header{padding:12px;gap:10px}h1{font-size:19px}.wrap{padding:0 10px;margin:12px auto}.card{padding:14px}.review-scroll{max-height:none;overflow:visible}.review-table,.review-table tbody{display:block}.review-table thead{display:none}.review-table tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;background:#0d2037;border:1px solid #38516c;border-radius:12px;padding:12px;margin-bottom:12px}.review-table td{display:block;min-width:0;overflow-wrap:anywhere;border:0;padding:2px}.review-table td:first-child{grid-column:1/-1;font-weight:800;font-size:17px;color:#fff}.review-table td:nth-child(n+7){grid-column:1/-1}.review-table td:nth-child(2):before{content:"Design CFM"}.review-table td:nth-child(3):before{content:"OSA CFM"}.review-table td:nth-child(4):before{content:"ESP"}.review-table td:nth-child(5):before{content:"Motor HP"}.review-table td:nth-child(6):before{content:"Verification"}.review-table td:nth-child(7):before{content:"Occurrences"}.review-table td:nth-child(8):before{content:"Suggestions"}.review-table td:nth-child(9):before{content:"Source"}.review-table td:before{display:block;color:#a6b9d2;font-size:11px;margin-bottom:5px}.review-table input,.review-table select{min-height:42px;width:100%}button{min-height:46px;margin:3px 0}}
/* ABP professional responsive design refresh */
.recommend-summary{border:1px solid #bfd6ed;background:#f0f7ff;color:#21466e;padding:16px;border-radius:11px;margin:12px 0 17px;font-size:13px}.recommend-summary strong{font-size:15px}.recommend-summary p{margin:8px 0 13px}.recommend-summary .recommend-item{display:flex;justify-content:space-between;align-items:baseline;gap:12px;border-top:1px solid #d5e6f6;padding:9px 0}.recommend-item span{font-weight:650}.recommend-item small{color:#526f8d;text-align:right}.recommend-item em{font-style:normal;border:1px solid #e3c898;color:#8c5515;background:#fff7e6;border-radius:8px;padding:2px 6px;font-size:10px;white-space:nowrap}@media(max-width:700px){.recommend-summary .recommend-item{display:block}.recommend-item small{display:block;text-align:left;margin-top:3px}}

:root{color-scheme:light;--navy:#102b4e;--blue:#145aaf;--blue2:#0c448c;--ink:#14263f;--muted:#61748b;--line:#dbe5f1;--paper:#fff;--pale:#f2f6fb;--teal:#0b7d90}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{background:var(--pale);color:var(--ink);font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;line-height:1.55;font-size:15px}
header{background:#fff;color:var(--ink);border:0;border-bottom:1px solid var(--line);padding:18px max(24px,calc((100vw - 1140px)/2));box-shadow:0 2px 12px #142c4410;gap:18px;display:flex;align-items:center}
header img{width:min(260px,45vw);height:78px;object-fit:contain;object-position:left center;padding:3px;background:transparent;border-radius:0}
.brand-name{font-size:12px;color:#4b6483;text-transform:uppercase;letter-spacing:1.3px;font-weight:750}.brand-sub{color:#546b85;font-size:13px;margin-top:3px}
.wrap{max-width:1140px;margin:0 auto;padding:26px 24px 50px}.hero{background:linear-gradient(110deg,#112e53 0%,#154579 70%,#17618e 100%);color:#fff;padding:33px 36px;margin-bottom:24px;border-radius:18px;box-shadow:0 12px 32px #173e7020;position:relative;overflow:hidden}.hero:after{content:'';position:absolute;width:280px;height:280px;border-radius:50%;right:-75px;top:-140px;border:54px solid #ffffff0c;pointer-events:none}.eyebrow{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:800;color:#a5d8f4}.hero h1{font-size:clamp(25px,3vw,36px);line-height:1.18;margin:9px 0}.hero p{color:#d8e7f9;margin:0;max-width:650px;font-size:14px}.hero-row{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.draft-pill{white-space:nowrap;border:1px solid #ffffff60;background:#ffffff13;padding:8px 12px;border-radius:999px;font-size:12px;color:#e5f4ff}
.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:28px 30px;margin-bottom:20px;box-shadow:0 5px 18px #192f4e0b}.card h2{display:flex;align-items:center;gap:12px;color:#142d4a;font-size:19px;margin:0 0 20px;font-weight:750}.step{display:inline-grid;place-items:center;flex:0 0 34px;height:34px;background:#e8f2fd;color:#1457a5;border-radius:10px;font-size:14px;font-weight:800}.card > p.muted{margin-top:-6px;margin-bottom:20px}.grid{gap:18px}
label{color:#304763;font-weight:650;margin:12px 0;font-size:13px}input[type=text],select,.review-table input,.review-table select{background:#fff;border:1px solid #c6d4e5;color:var(--ink);border-radius:9px;padding:12px 13px;font:inherit;min-height:46px;box-shadow:0 1px 2px #172e4705}input[type=text]::placeholder{color:#91a0b2}input:focus,select:focus,button:focus-visible{outline:3px solid #65aaf36b;outline-offset:1px;border-color:#2379ca}input[type=file]{color:#34516d;background:#f7fbff;border:2px dashed #93b6dd;border-radius:12px;padding:24px;min-height:90px;font:inherit}input[type=file]::file-selector-button{border:1px solid #b6cae1;background:white;color:#164b86;padding:10px 14px;border-radius:8px;font-weight:700;margin-right:12px}button{background:var(--blue);border:1px solid var(--blue);border-radius:9px;min-height:44px;box-shadow:0 3px 8px #145aaf1d;transition:background .15s,transform .15s}button:hover{background:var(--blue2)}button:active{transform:translateY(1px)}button:disabled{cursor:wait}#selectall,#clear,#saveproject{color:#16508c;background:#eff6ff;border-color:#c8daef;box-shadow:none}#selectall:hover,#clear:hover,#saveproject:hover{background:#e0efff}#generate{background:#0b7180;border-color:#0b7180;min-width:220px}#generate:hover{background:#075969}small,.muted{color:var(--muted);font-weight:400}.templates{grid-template-columns:repeat(3,minmax(0,1fr));max-height:380px;padding:3px;gap:10px}.template{color:#304760;background:#f9fbfe;border:1px solid #d9e5f0;border-radius:10px;padding:11px 12px;font-size:13px;display:flex;align-items:center;line-height:1.35;margin:0;min-height:47px;font-weight:550}.template:hover{border-color:#7cadde;background:#eff7ff}.template:has(input:checked){background:#eaf4ff;border-color:#80b1df;color:#0d467d}.template input{accent-color:#145aaf;flex-shrink:0;width:16px;height:16px;margin-right:9px}.review-table{color:var(--ink)}.review-table td,.review-table th{border-bottom:1px solid var(--line);padding:10px}.review-table th{background:#f3f7fc;color:#244365}.review-table input{padding:8px}.review-scroll{border:1px solid var(--line);border-radius:11px}.tag{background:#e9f2fc;color:#1c5288}.warn{color:#9c5d09}.success{color:#197252}a{color:#145aaf}#scanstatus,#status{font-size:13px;font-weight:600;overflow-wrap:anywhere}.footer-note{font-size:12px;color:#647991;display:flex;align-items:center;gap:8px;margin:20px 5px}
@media(max-width:700px){header{padding:13px 18px;gap:10px;align-items:center}header img{width:44vw;max-width:190px;height:60px}.brand-name{font-size:10px;letter-spacing:.8px}.brand-sub{font-size:11px;line-height:1.3}.wrap{padding:15px 12px 34px}.hero{padding:24px 22px;margin-bottom:16px;border-radius:14px}.hero-row{display:block}.hero h1{font-size:26px}.hero p{font-size:13px}.draft-pill{display:inline-block;margin-top:18px}.grid,.templates{grid-template-columns:1fr}.card{padding:20px 16px;margin-bottom:14px;border-radius:13px}.card h2{font-size:17px;margin-bottom:16px}.step{height:30px;flex-basis:30px}input[type=file]{padding:15px}.review-scroll{overflow:visible;border:0}.review-table,.review-table tbody{display:block}.review-table thead{display:none}.review-table tr{background:#f7faff;border-color:#d5e2ef}.review-table td{color:#1b344e}.review-table td:first-child{color:#102e50}.review-table td:before{color:#59748f}button{min-height:46px}#generate{width:100%}.footer-note{line-height:1.5}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style><header><img src="/logo.png" alt="Air Balance Professionals company logo"><div><div class="brand-name">Air Balance Professionals</div><div class="brand-sub">Technical reporting workspace &nbsp;·&nbsp; NEBB #3861</div></div></header><main class="wrap"><section class="hero" aria-label="Report builder introduction"><div class="hero-row"><div><div class="eyebrow">ABP / Field engineering tools</div><h1>TAB Report Builder</h1><p>Prepare organized, reviewable pre-field testing and balancing reports using original ABP Excel templates.</p></div><span class="draft-pill">Pre-field draft workspace</span></div></section><div class="card"><h2><span class="step">01</span> Project details</h2><div class="grid"><label>Project name<input id="project" type="text" placeholder="Project / facility name"></label><label>Location<input id="location" type="text" placeholder="City, State"></label></div><label>Standard<select id="standard"><option value="Commercial">Commercial · ±10% target</option><option value="USACE">USACE · ±5% target (DALT prerequisite)</option></select></label></div><div class="card"><h2><span class="step">02</span> Upload source documents</h2><input id="files" type="file" accept=".pdf,.xlsx,.csv" multiple><p class="muted">PDF mechanical sheets, approved submittals, Excel and CSV schedules. Text-based extraction only; always review the M-sheet takeoff and latest revision.</p><button id="scan">Scan uploaded files</button><p id="scanstatus"></p><div id="tags"></div><div id="review"></div></div><div class="card"><h2><span class="step">03</span> Choose report templates</h2><p class="muted">Select the actual ABP worksheets to include. Formatting and formulas are copied from the supplied masters.</p><div><button id="selectall" type="button">Select all</button> <button id="clear" type="button">Clear</button></div><div id="template-recommendations" class="recommend-summary" aria-live="polite">Scan source documents to get automatic template recommendations. You can always change the selections below.</div><div class="templates" id="templates"></div></div><div class="card"><h2><span class="step">04</span> Generate your report</h2><p class="muted">Creates a draft workbook with original template sheets and individual air-moving/exhaust-fan sheets for detected units. Only records explicitly marked Verified populate equipment sheets. All detected tags remain in the review log; no field measurements or approvals are fabricated.</p><button id="saveproject" type="button">Save project review (.json)</button> <label>Restore saved review<input id="loadproject" type="file" accept=".json,application/json"></label><button id="generate">Generate pre-field .xlsx</button><p id="status"></p></div><p class="footer-note"><span aria-hidden="true">ⓘ</span> Pre-field draft only. All extracted values require review; final TAB reports require engineering verification and field signoff.</p></main><script>
let tags=[],records=[];const $=id=>document.getElementById(id);async function init(){let t=await(await fetch('/api/templates')).json();$('templates').innerHTML=t.map(x=>`<label class="template"><input type="checkbox" value="${x.replaceAll('&','&amp;').replaceAll('"','&quot;')}">${x.replaceAll('&','&amp;').replaceAll('<','&lt;')}</label>`).join('');for(const box of document.querySelectorAll('.template input')){if(/project information|notes|air moving equipment|supply diffusers/i.test(box.value))box.checked=true}}init();$('selectall').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=true);$('clear').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=false);
$('scan').onclick=async()=>{let files=$('files').files;if(!files.length){$('scanstatus').textContent='Choose files first';return}let form=new FormData();for(let f of files)form.append('files',f);$('scan').disabled=true;$('scanstatus').textContent='Reading files...';try{let r=await fetch('/api/scan',{method:'POST',body:form});let data=await r.json();if(!r.ok)throw Error(data.error);tags=data.tags||[];records=data.records||[];$('scanstatus').textContent=`Found ${tags.length} unique equipment tags in ${data.characters.toLocaleString()} extracted characters. Candidate measurements are recorded separately and must be verified.`+(data.warnings.length?' Warnings: '+data.warnings.join(' | '):'');$('tags').innerHTML='';renderReview();let recommendation=await(await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags,signals:data.signals||[]})})).json();if(!Array.isArray(recommendation.recommended))throw Error('Template recommendations unavailable');let chosen=new Set(recommendation.recommended.map(x=>x.name));document.querySelectorAll('.template input').forEach(x=>x.checked=chosen.has(x.value));let safe=x=>String(x||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');$('template-recommendations').innerHTML='<strong>Recommended '+recommendation.recommended.length+' ABP templates</strong><p>Selected automatically based on the uploaded documents. Review and change any checked boxes before generating.</p>'+recommendation.recommended.map(x=>'<div class="recommend-item"><span>'+safe(x.name)+(x.review?' <em>Review type</em>':'')+'</span><small>'+safe(x.reason)+'</small></div>').join('')+'<p class="muted">'+safe(recommendation.review_note)+'</p>'}catch(e){$('scanstatus').textContent=e.message}finally{$('scan').disabled=false}};
function renderReview(){let safe=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');$('review').innerHTML='<p>Review detected tags and manually enter verified design values. No CFM or ESP is inferred from unverified text.</p><div class="review-scroll"><table class="review-table"><thead><tr><th>Tag</th><th>Design CFM</th><th>OSA CFM</th><th>ESP</th><th>HP</th><th>Review</th><th>Occurrences</th><th>Suggestions</th><th>Source</th></tr></thead><tbody>'+records.map((r,i)=>`<tr><td>${safe(r.tag)}</td>${['design_cfm','osa_cfm','esp','motor_hp'].map(k=>`<td><input type="number" step="any" data-row="${i}" data-field="${k}" value="${safe(r[k])}"></td>`).join('')}<td><select data-status="${i}"><option value="UNVERIFIED">Unverified</option><option value="VERIFIED">Verified</option><option value="EXCLUDED">Excluded</option></select></td><td>${r.occurrences?.length||1}</td><td title="Unverified extracted suggestions">${safe((r.candidates||[]).map(c=>Object.entries(c.values).map(([k,v])=>k+': '+v).join(', ')).join(' | '))}</td><td title="${safe(r.evidence)}">${safe(r.source)} · ${safe(r.reference)}</td></tr>`).join('')+'</tbody></table></div>';document.querySelectorAll('[data-row]').forEach(el=>el.oninput=()=>{records[+el.dataset.row][el.dataset.field]=el.value});document.querySelectorAll('[data-status]').forEach(el=>el.onchange=()=>{records[+el.dataset.status].status=el.value})}
function projectPayload(){return {project:$('project').value,location:$('location').value,standard:$('standard').value,tags,records,templates:[...document.querySelectorAll('.template input:checked')].map(x=>x.value)}}
$('saveproject').onclick=()=>{const data=JSON.stringify({format:'ABP-PREFIELD-REVIEW',version:1,...projectPayload()},null,2);const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ABP_Project_Review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)};
$('loadproject').onchange=async ev=>{try{const f=ev.target.files[0];if(!f)return;if(f.size>2000000)throw Error('Project review file exceeds 2 MB');const data=JSON.parse(await f.text());if(data.format!=='ABP-PREFIELD-REVIEW'||data.version!==1||!Array.isArray(data.records)||data.records.length>500||!Array.isArray(data.templates))throw Error('Invalid ABP project review');$('project').value=String(data.project||'');$('location').value=String(data.location||'');$('standard').value=data.standard==='USACE'?'USACE':'Commercial';records=data.records;tags=records.map(r=>r.tag);document.querySelectorAll('.template input').forEach(x=>x.checked=data.templates.includes(x.value));renderReview();$('status').textContent='Saved review restored. Recheck verification and source revisions before generating.'}catch(e){$('status').textContent=e.message}};
$('generate').onclick=async()=>{let payload=projectPayload();$('generate').disabled=true;$('status').textContent='Building workbook...';try{let r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){let e=await r.json();throw Error(e.error)}let blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(payload.project.replace(/[^a-z0-9_-]+/gi,'_')||'ABP')+'_PreField_TAB.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent='DRAFT workbook generated. Check all source revisions, flagged records, and formulas before field use.'}catch(e){$('status').textContent=e.message}finally{$('generate').disabled=false}};
</script></html>'''
# LAN mode is explicitly opt-in. HTTP Basic credentials protect the entire app, not only API calls.
LAN_MODE = '--lan' in sys.argv
ACCESS_PASSWORD = os.environ.get('ABP_ACCESS_PASSWORD', '')
class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        if not LAN_MODE:return True
        header=self.headers.get('Authorization','')
        expected='Basic '+base64.b64encode(('abp:'+ACCESS_PASSWORD).encode()).decode()
        return bool(ACCESS_PASSWORD) and secrets.compare_digest(header,expected)
    def gate(self):
        if self.authorized():return False
        self.send_response(401)
        self.send_header('WWW-Authenticate','Basic realm="ABP Mobile - Private LAN"')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length','0')
        self.end_headers()
        return True

    def respond(self,data,typ='application/json',code=200,filename=None):
        self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY');
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.gate():return
        if self.path.split('?',1)[0]=='/':self.respond(PAGE.encode(),'text/html; charset=utf-8')
        elif self.path.split('?',1)[0]=='/logo.png':
            logo=ROOT/'04_Company_Branding/ABP_Company_Logo.png'
            if logo.is_file():self.respond(logo.read_bytes(),'image/png')
            else:self.respond(b'Logo not installed','text/plain',404)
        elif self.path=='/api/templates':self.respond(json.dumps(list(LOOKUP)).encode())
        else:self.respond(b'Not found','text/plain',404)
    def do_POST(self):
        if self.gate():return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>MAX_UPLOAD:raise ValueError('Upload limit is 40 MB')
            data=self.rfile.read(n)
            if self.path=='/api/suggest':self.respond(json.dumps(suggested_templates(json.loads(data).get('tags',[]),json.loads(data).get('signals',[]))).encode());return
            if self.path=='/api/build':
                payload=json.loads(data);out=build(payload);self.respond(out,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='ABP_PreField_TAB.xlsx');return
            if self.path=='/api/scan':
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
        print('WARNING: HTTP Basic authentication is not encrypted. Use only on a trusted private Wi-Fi network, never on public Wi-Fi or the open Internet. Do not port-forward.')
    ThreadingHTTPServer((host,port),Handler).serve_forever()
