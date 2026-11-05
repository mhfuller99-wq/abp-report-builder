#!/usr/bin/env python3
"""ABP local report builder. Uses original workbook templates; no cloud upload."""
import io,json,re,sys,zipfile,html,datetime,hashlib,hmac,time,math,csv,os,secrets,base64,ipaddress,socket,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from socketserver import TCPServer
from urllib.parse import unquote,parse_qs,urlsplit
from openpyxl import Workbook,load_workbook
from openpyxl.workbook.properties import CalcProperties
from openpyxl.utils import get_column_letter
from abp_reference import inspect_reference, build_reference, reset_measurements
from abp_fidelity import preserve_template_parts
from abp_grouped import group_template_sheets
from abp_design import extract_design_rows, UNIT_FORMS, TEXT_CELLS, unit_form, inferred_form
from abp_job import NUMERIC_FIELDS, TEXT_FIELDS, canonical_tag, postal_match, performance_candidates, populate_identity, populate_support, prepare_documentation
from abp_schedule import parse_pdf, annotate

ROOT=Path(__file__).resolve().parent
TEMPLATES=ROOT/'03_Workbooks_and_Master_Templates'
FILES=[p for p in sorted(TEMPLATES.glob('*.xlsx')) if p.name not in {'Blue Mountain - TAB Report.xlsx','CAFB Egress Shop - TAB Report.xlsx','CALEDONIA FEILDHOUSE TAB REPORT.xlsx','Cadence  Bank- Starkville MS .xlsx','New Hope Fieldhouse.xlsx','WEST LOWNDES FIELDHOUSE .xlsx'}]
LOOKUP={p.name:p for p in FILES}
TAGS=re.compile(r'\b(?:(?:BCU|BC|CH|CHP|CHWP|HWP|CWP|PCP|SCP|PHP|SHP|P|B|F|AH|ACU|PAC|KSF)(?:\s*-\s*|\s+)|(?:AHU|RTU|OAU|DOAS|CRU|MAU|ERV|HRV|FCU|FC|VAV|FPP|IU|IDU|MSFC|MSE|MS|PTAC|CRAC|IHP|HPBC|HP|AC|ACC|DSS|DCU|KEF|TEF|CEF|SEF|RLF|KH|EF|SF|RF|GF|PU|EUH|EWH|CUH|UH|FFU|LF|VRF|SSAU|SSCU|GUH|HVLS|PF|FS|EH)(?:\s*-\s*|\s+)?)\d+[A-Z]?(?:[-.][A-Z0-9]+)*\b',re.I)
MAX_RECORDS=500
MAX_UPLOAD=200_000_000
# Title-block scraps and image-only drawings fall below this. A real schedule does not.
SPARSE_TEXT_LIMIT=500
OFFICE_FRONT=('Project Information.xlsx','Notes.xlsx')
RECT_TEMPLATE='Duct Traverse Rect..xlsx'
RND_TEMPLATE='Duct Traverse RND.xlsx'
BLANK_RECT_FORMS=30
BLANK_RND_FORMS=15
# Spreadsheet theme index 0 is lt1, 1 is dk1; the theme XML lists dk1 first.
SHEET_THEME_INDEX=(1,0,3,2,4,5,6,7,8,9,10,11)
SCHEME_NAMES=('dk1','lt1','dk2','lt2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink')
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
    if sum(len(data) for _,data in blobs)>MAX_UPLOAD:raise ValueError('Total source size exceeds 200 MB')
    for name,data in blobs:
        name=Path(name).name[:160];ext=Path(name).suffix.lower();chunks=[];structured=[]
        try:
            if ext=='.pdf':
                # Schedule rows come from visual lines. Flattened page text joins a
                # grille mark to a distant dimension, so it is not searched for tags.
                parsed,pdf_warnings=parse_pdf(name,data)
                warnings.extend(pdf_warnings)
                import pymupdf
                with pymupdf.open(stream=data,filetype='pdf') as doc:
                    if doc.page_count>300:raise ValueError('PDF has more than 300 pages')
                    for i,page in enumerate(doc):
                        words=page.get_text('words') or []
                        txt=' '.join(word[4] for word in sorted(words,key=lambda item:(item[1],item[0])))
                        chunks.append((f'page {i+1}',txt))
                        for candidate in performance_candidates(txt,TAGS):
                            structured.append({**candidate,'reference':f'page {i+1}','basis':'TAGGED_PERFORMANCE'})
                for item in parsed:
                    structured.append(item)
                if not any(text.strip() for _,text in chunks):warnings.append(name+': image-only PDF; manual takeoff required')
            elif ext=='.csv':
                decoded=data.decode('utf-8-sig')
                source_rows=list(csv.reader(io.StringIO(decoded)))
                if len(source_rows)>MAX_OUTPUT_ROWS:raise ValueError('CSV has too many rows')
                structured=extract_design_rows(source_rows,name,TAGS)
                for i,row in enumerate(source_rows,1):
                    if any(row):chunks.append((f'CSV row {i}',' | '.join(row)[:4000]))
                    if i>MAX_OUTPUT_ROWS:raise ValueError('CSV has too many rows')
            elif ext=='.xlsx':
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if sum(x.file_size for x in archive.infolist())>50_000_000:raise ValueError('Workbook expands beyond 50 MB')
                wb=load_workbook(io.BytesIO(data),read_only=True,data_only=False)
                for ws in wb:
                    ws.reset_dimensions()
                    source_rows=[]
                    for i,row in enumerate(ws.iter_rows(),1):
                        if i>MAX_OUTPUT_ROWS or len(row)>200:raise ValueError('Workbook exceeds source analysis limits')
                        raw=[c.value if c.data_type!='f' else None for c in row]
                        source_rows.append(raw)
                        vals=[str(v)[:150] if v is not None else '' for v in raw]
                        if any(vals):chunks.append((f'{ws.title} row {i}',' | '.join(vals)[:4000]))
                        if len(chunks)>MAX_OUTPUT_ROWS:raise ValueError('Workbook has too many nonempty rows')
                    structured.extend(extract_design_rows(source_rows,ws.title,TAGS))
                wb.close()
            else:warnings.append(name+': unsupported source type');continue
            sources.append({'name':name,'sections':len(chunks),'sha256':hashlib.sha256(data).hexdigest()})
            for place,chunk in chunks:
                total_chars+=len(chunk)
                # Heading evidence is only a recommendation, never verified TAB data.
                for signal,pattern in SCHEDULE_SIGNALS.items():
                    if pattern.search(chunk[:6000]):signals.add(signal)
                if len(preview)<12:preview.append(chunk[:200])
                if ext=='.pdf':
                    continue
                for line in chunk.splitlines():
                    for m in TAGS.finditer(line):
                        if re.search(r'\b(?:IAS|ICC|ANSI|ASTM)\s*$',line[:m.start()],re.I):continue
                        if postal_match(m,line):continue
                        tag=canonical_tag(m.group())
                        next_tag=TAGS.search(line,m.end())
                        stop=min(m.end()+140,next_tag.start() if next_tag else len(line))
                        local=line[m.end():stop]
                        context=line[max(0,m.start()-55):stop]
                        evidence={'source':name,'reference':place,'evidence':context[:190]}
                        vals=candidate_values(local) if ext=='.pdf' and not re.search(r'\b(ACTUAL|MEASURED|INITIAL|FINAL|AS FOUND)\b',context,re.I) else {}
                        if tag not in records:
                            records[tag]={'tag':tag,**evidence,'occurrences':[evidence],'design_cfm':None,'osa_cfm':None,'esp':None,'motor_hp':None,'status':'UNVERIFIED','candidates':[]}
                        elif len(records[tag]['occurrences'])<30:records[tag]['occurrences'].append(evidence)
                        # Candidates are suggestions, not approved inputs. Restrict to the tag's local context.
                        if vals and len(records[tag]['candidates'])<30:
                            records[tag]['candidates'].append({'values':vals,**evidence})
            for candidate in structured:
                tag=candidate['tag'];evidence={'source':name,'reference':candidate['reference'],'evidence':candidate['evidence']}
                if tag not in records:
                    records[tag]={'tag':tag,**evidence,'occurrences':[evidence],'design_cfm':None,'osa_cfm':None,'esp':None,'motor_hp':None,'design_gpm':None,'status':'UNVERIFIED','candidates':[]}
                if len(records[tag]['candidates'])<30:records[tag]['candidates'].append({**candidate,'source':name})
            if len(records)>MAX_RECORDS:warnings.append('More than 500 unique tags found; only first 500 will be shown')
        except Exception as e:warnings.append(name+': could not parse ('+str(e)[:120]+')')
    for record in records.values():
        annotate(record)
        form=inferred_form(record['tag'])
        if form:record['template']=form
        elif any(item.get('unmapped') or str(item.get('reference','')).startswith('page') for item in record.get('candidates') or []):
            record['template']=''
            record['proposed']={}
            record['text_proposed']={}
            if 'No supported report form; excluded from the workbook until a form is selected' not in record['flags']:
                record['flags'].append('No supported report form; excluded from the workbook until a form is selected')
        for item in record.get('candidates') or []:
            for key in ('fan_rpm','motor_watts','unit_mca','unit_mop','brake_hp'):
                (item.get('values') or {}).pop(key,None)
    image_only=any('image-only PDF' in warning or 'no readable text' in warning for warning in warnings)
    # Schedule headings mean the text was usable, even if another drawing was scanned.
    sparse=total_chars<SPARSE_TEXT_LIMIT or (image_only and not signals)
    return {'tags':list(records)[:MAX_RECORDS],'records':list(records.values())[:MAX_RECORDS],'warnings':warnings,'characters':total_chars,'sources':sources,'preview':'\n'.join(preview)[:1800],'signals':sorted(signals),'sparse':sparse}

# These labels only suggest which original ABP workbook to include.
# They do not verify equipment quantities, schedules, or field measurements.
SCHEDULE_SIGNALS={
 'gas_performance':re.compile(r'Gas Heating Values',re.I),
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
 'air_moving':re.compile(r'\b(?:AIR\s+HANDLING\s+UNIT|ROOFTOP\s+UNIT|SUPPLY\s+FAN|MAKEUP\s+AIR\s+UNIT|DOAS|DEDICATED\s+OUTDOOR\s+AIR)\s+SCHEDULE\b',re.I),
 'exhaust_fan':re.compile(r'\bEXHAUST\s+FAN\s+SCHEDULE\b',re.I),
 'gas_heat':re.compile(r'\b(?:GAS\s+HEAT(?:ING)?|GAS\s+FURNACE|HEATING\s+TYPE\s*[:=]?\s*GAS)\b',re.I),
 'dx_cooling':re.compile(r'\b(?:DX\s+COOL(?:ING)?|DIRECT\s+EXPANSION(?:\s+COIL)?)\b',re.I),
 'electric_heat':re.compile(r'\b(?:ELECTRIC\s+HEAT(?:ING)?|HEATING\s+TYPE\s*[:=]?\s*ELECTRIC)\b',re.I),
 'ductless':re.compile(r'\b(?:DUCTLESS|MINI[-\s]?SPLIT)\b',re.I),
 'vav':re.compile(r'\bVAV\s+(?:BOX(?:ES)?|TERMINAL(?:S)?|SCHEDULE|UNIT(?:S)?)\b',re.I),
 'unit_heater':re.compile(r'\bUNIT\s+HEATERS?\s+SCHEDULE\b',re.I),
}
def lookup_templates(pattern):
    """Master files whose names match. Instrument sheets are never offered for auto-select."""
    return [name for name in sorted(LOOKUP) if re.search(pattern,name,re.I) and not re.search(r'instrument',name,re.I)]
def suggested_templates(tags,signals=None,*,sparse=False):
    """Pre-field worksheet pack. The UI checks these and still allows manual override."""
    tags=[str(x).upper()[:80] for x in tags[:MAX_RECORDS] if isinstance(x,str)] if isinstance(tags,list) else []
    signals=set(x for x in (signals or []) if isinstance(x,str)) if isinstance(signals,list) else set()
    sparse=sparse is True
    result=[]
    def add(filename,reason,review=False):
        # Cover, abbreviations, summaries, checklists and instruments are not part of the initial workbook.
        if not isinstance(filename,str) or banned_initial_template(filename):return
        if filename in LOOKUP and not any(x['name']==filename for x in result):
            result.append({'name':filename,'reason':reason,'review':bool(review)})
    def tagged(prefixes):
        return any(re.match(r'^(?:'+prefixes+r')[- ]?\d',tag) for tag in tags)
    add('Project Information.xlsx','Project information opens the pre-field workbook')
    add('Notes.xlsx','Pre-field notes')
    air=tagged('AHU|RTU|OAU|DOAS|MAU|AC|SF|RF|CRU|GF|PU|AH|ACU|PAC|KSF') or 'air_moving' in signals
    packaged=tagged('RTU|DOAS|OAU|AC|PAC')
    gas='gas_performance' in signals or 'gas_heat' in signals
    dx='dx_cooling' in signals
    electric='electric_heat' in signals
    if air:
        add('Air Moving Equipment.xlsx','Air-moving, rooftop, or dedicated outdoor-air equipment')
    # DX/gas coil sheet for packaged equipment. Water coils stay on their own form.
    if gas or dx or (packaged and not electric):
        add('Coil DX GAS HT.xlsx','DX cooling / gas heating coil sheet for packaged or outdoor-air equipment',not (gas or dx))
    elif electric and (air or packaged):
        add('COIL DX HP ELE.xlsx','Electric heat noted for air-moving equipment; confirm the coil form',True)
    if tagged('EF|KEF|TEF|CEF|SEF|RLF') or 'exhaust_fan' in signals:
        add('Exhaust Fans _Std._.xlsx','Exhaust fan tags or schedule heading')
        add('Exhaust Fans _Sm._.xlsx','Small and standard fan forms both occur in past reports; choose the applicable form per unit',True)
    if tagged('FCU|FC|IU|IDU|MSFC|MSE|MS|DSS|PTAC|BCU|BC|VRF|SSAU') or 'fan_coil' in signals or 'ductless' in signals:
        water=tagged('BCU|BC') or 'water_coil' in signals
        ductless=tagged('IU|IDU|MSFC|DSS|PTAC|VRF|SSAU') or 'ductless' in signals
        if ductless and not water:
            add('Fan Coil Units DX.xlsx','Ductless or DX fan-coil equipment')
        else:
            add('Fan Coil Units WTR.xlsx' if water else 'Fan Coil Units DX.xlsx','Fan-coil equipment; confirm water or DX type against the schedule',True)
            if tagged('FCU|BCU|BC'):
                add('Fan Coil Units DX.xlsx' if water else 'Fan Coil Units WTR.xlsx','This tag appears on multiple coil types in prior projects; verify the new job design',True)
        if gas and not water:
            add('Fan Coil Units DX GAS.xlsx','Gas heat noted with fan-coil equipment',True)
        if electric and not water:
            add('Fan Coil Units DX ELE.xlsx','Electric heat noted with fan-coil equipment',True)
    if tagged('IHP|HPBC|HP|CRAC'):
        add('Air Moving Equipment.xlsx','Heat-pump or packaged equipment; confirm equipment form',True)
        add('COIL DX HP ELE.xlsx','Possible heat-pump coil performance form; verify the schedule',True)
    if tagged('AH|ACU|PAC|KSF'):
        add('Air Moving Equipment.xlsx','Air-moving form observed for this tag family; confirm the current job equipment type',True)
        if tagged('AH'):
            add('Fan Coil Units DX.xlsx','AH also occurs on fan-coil forms; select the applicable unit form',True)
    if tagged('VAV|FPP') or 'vav' in signals:
        for name in lookup_templates(r'vav'):
            add(name,'VAV tag or schedule heading')
    if 'diffusers' in signals:
        for name in lookup_templates(r'diffuser'):
            add(name,'Supply diffuser schedule heading')
    if 'exhaust_grilles' in signals:
        add('Exhaust Grilles.xlsx.xlsx','Exhaust grille schedule detected; review device types',True)
    if tagged('EUH|EWH|CUH|UH') or 'unit_heater' in signals:
        for name in lookup_templates(r'unit\s*heater'):
            add(name,'Unit heater tag or schedule heading')
    if 'water_coil' in signals:
        add('Coil WTR CLG WTR HT.xlsx','Water-coil schedule heading detected')
    if tagged('B'):add('Boiler.xlsx','Boiler tag; confirm service and design data',True)
    if tagged('CH|ACC'):
        add('Chiller - Air Cooled.xlsx','Chiller tag; verify condenser type',True)
    if tagged('CH'):
        add('Chiller - Air Cooled.xlsx','Chiller tag detected; confirm air or water cooling',True)
    if tagged('ERV|HRV') or 'erv' in signals:
        add('ERV.xlsx','Energy-recovery equipment or schedule; confirm model type',True)
    if tagged('FFU') or 'filter_unit' in signals:
        add('Fan Filter Units.xlsx','Fan-filter unit tags or schedule')
    if 'cooling_tower' in signals:add('Cooling Tower.xlsx','Cooling tower schedule heading')
    if 'boiler' in signals:add('Boiler.xlsx','Boiler schedule heading')
    if 'chiller' in signals:
        add('Chiller - Air Cooled.xlsx','Chiller schedule; confirm air or water cooling',True)
    if tagged('KH') or 'kitchen_hood' in signals:add('Kitchen Hood.xlsx','Kitchen exhaust hood tag or schedule heading')
    if 'heat_exchanger' in signals:add('Heat Exchanger.xlsx','Heat exchanger schedule heading')
    if 'hydronic' in signals:add('Hydronic BV - Auto-flow.xlsx','Hydronic balancing valve schedule',True)
    if 'dehumidifier' in signals:add('Dehumidifier.xlsx','Dehumidifier schedule heading')
    # Image-only drawings still get a usable pack. Tag hits above are kept.
    if sparse:
        add('Air Moving Equipment.xlsx','Default pre-field air-moving sheet when the scan has little readable text')
    add(RECT_TEMPLATE,'Rectangular duct traverses follow the equipment tabs')
    add(RND_TEMPLATE,'Round duct traverses follow the rectangular traverses')
    note='Checked from this job’s equipment tags and schedule headings. The workbook opens with Project Info, then Notes, those equipment sheets, rectangular duct traverses, and round duct traverses. Cover, abbreviations, project summary, pre-tab, instrument, and audit tabs stay out. Change any equipment checkbox before building.'
    if sparse:
        note='Little readable text was found, so the default pack is checked and fan-coil, exhaust, and coil sheets are added when tags suggest them. '+note
    return {'recommended':result,'review_note':note}


def banned_initial_template(name):
    """Documentation and audit masters that never belong in the initial workbook."""
    low=name.lower()
    if 'instrument' in low:return True
    if low.startswith('cover'):return True
    if 'abbreviation' in low:return True
    if 'pre-tab' in low or 'pretab' in low:return True
    if 'project summary' in low:return True
    return False

def banned_initial_sheet(title):
    key=' '.join(title.strip().upper().split())
    if key in {'ABP BUILD INFO','TAKEOFF REVIEW','SOURCE EVIDENCE','AIRFLOW CHECK','EXTRACTION CANDIDATES','ABBREVIATIONS','PRE-TAB CHECKLIST','PROJECT SUMMARY','INSTRUMENT'}:return True
    return key=='COVER' or key.startswith('COVER ')

def theme_palette(theme):
    """Twelve scheme colors in theme-XML order, or None when the part cannot be read."""
    if not theme:return None
    text=theme.decode('utf-8','replace') if isinstance(theme,(bytes,bytearray)) else str(theme)
    scheme=re.search(r'<a:clrScheme[\s\S]*?</a:clrScheme>',text)
    if not scheme:return None
    colors=[]
    for tag in SCHEME_NAMES:
        block=re.search(fr'<a:{tag}>(.*?)</a:{tag}>',scheme.group(0))
        if not block:return None
        found=re.search(r'(?:srgbClr[^>]*val|lastClr)="([0-9A-Fa-f]{6})"',block.group(1))
        if not found:return None
        colors.append(found.group(1).upper())
    return tuple(colors)

def read_theme(path):
    try:
        with zipfile.ZipFile(path) as archive:
            parts=sorted(n for n in archive.namelist() if n.startswith('xl/theme/theme'))
            return archive.read(parts[0]) if parts else None
    except (OSError,zipfile.BadZipFile):return None

def _hls(r,g,b):
    r,g,b=r/255,g/255,b/255
    hi,lo=max(r,g,b),min(r,g,b)
    light=(hi+lo)/2
    if hi==lo:return 0.0,light,0.0
    span=hi-lo
    sat=span/(2-hi-lo) if light>0.5 else span/(hi+lo)
    if hi==r:hue=((g-b)/span)%6
    elif hi==g:hue=(b-r)/span+2
    else:hue=(r-g)/span+4
    return hue/6,light,sat

def _rgb(h,light,sat):
    def hue(p,q,t):
        if t<0:t+=1
        if t>1:t-=1
        if t<1/6:return p+(q-p)*6*t
        if t<1/2:return q
        if t<2/3:return p+(q-p)*(2/3-t)*6
        return p
    if sat==0:r=g=b=light
    else:
        q=light*(1+sat) if light<0.5 else light+sat-light*sat
        p=2*light-q
        r,g,b=hue(p,q,h+1/3),hue(p,q,h),hue(p,q,h-1/3)
    return tuple(max(0,min(255,int(round(v*255)))) for v in (r,g,b))

def apply_tint(rgb,tint):
    """Excel theme tint: luminance moves toward white or black. Hue and saturation stay."""
    if not tint:return rgb
    hue,light,sat=_hls(*rgb)
    light=light*(1+tint) if tint<0 else light*(1-tint)+tint
    return _rgb(hue,max(0.0,min(1.0,light)),sat)

def theme_color_rgb(palette,sheet_index,tint=0):
    base=palette[SHEET_THEME_INDEX[int(sheet_index)]]
    rgb=tuple(int(base[i:i+2],16) for i in (0,2,4))
    red,green,blue=apply_tint(rgb,float(tint or 0))
    return f'FF{red:02X}{green:02X}{blue:02X}'

def bake_color(color,palette):
    if color is None or getattr(color,'type',None)!='theme' or color.theme is None:return color
    if not 0<=int(color.theme)<=11:return color
    from openpyxl.styles.colors import Color
    return Color(rgb=theme_color_rgb(palette,color.theme,color.tint))

def bake_painted(obj,palette):
    """Copy a font, fill, or border and freeze its theme colors to the source palette."""
    from copy import copy
    painted=copy(obj)
    if getattr(painted,'color',None) is not None and getattr(painted.color,'type',None)=='theme':
        painted.color=bake_color(painted.color,palette)
    for attr in ('fgColor','bgColor'):
        color=getattr(painted,attr,None)
        if color is not None and getattr(color,'type',None)=='theme':
            setattr(painted,attr,bake_color(color,palette))
    for side in ('left','right','top','bottom','diagonal'):
        edge=getattr(painted,side,None)
        if edge is not None and getattr(edge,'color',None) is not None and getattr(edge.color,'type',None)=='theme':
            edge.color=bake_color(edge.color,palette)
    return painted

def sheet_name(wb,name):
    s=name[:31];i=2
    while s in wb.sheetnames:
        suffix=f' ({i})';s=name[:31-len(suffix)]+suffix;i+=1
    return s

def add_template(wb,path):
    source=load_workbook(path)
    source_palette=theme_palette(source.loaded_theme)
    book_palette=theme_palette(wb.loaded_theme)
    # Same palette and fonts can live on one workbook theme. A different palette is
    # frozen to explicit RGB from its own scheme so the sheet does not recolor.
    bake=False
    if wb.loaded_theme is None:wb.loaded_theme=source.loaded_theme
    elif source.loaded_theme is not None and wb.loaded_theme!=source.loaded_theme:
        if source_palette and book_palette and source_palette!=book_palette:bake=True
        elif not source_palette or not book_palette:raise ValueError('Templates use incompatible themes; build separately to preserve their formatting')
    for ws in source:
        dst=wb.create_sheet(sheet_name(wb,ws.title))
        dst._template_origin=(path.read_bytes(),ws.title)
        dst._template_file=path.name
        dst._template_formulas={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}
        for row in ws:
            for c in row:
                target=dst[c.coordinate]
                target.value=c.value
                if c.has_style:
                    from copy import copy
                    font=bake_painted(c.font,source_palette) if bake else copy(c.font)
                    fill=bake_painted(c.fill,source_palette) if bake else copy(c.fill)
                    border=bake_painted(c.border,source_palette) if bake else copy(c.border)
                    target.font=font;target.fill=fill;target.border=border;target.alignment=copy(c.alignment);target.protection=copy(c.protection);target.number_format=c.number_format
                if c.hyperlink:target._hyperlink=__import__('copy').copy(c.hyperlink)
                if c.comment:target.comment=__import__('copy').copy(c.comment)
        for merged in ws.merged_cells.ranges:dst.merge_cells(str(merged))
        for k,d in ws.column_dimensions.items():dst.column_dimensions[k]=__import__('copy').copy(d);dst.column_dimensions[k].parent=dst
        for k,d in ws.row_dimensions.items():dst.row_dimensions[k]=__import__('copy').copy(d);dst.row_dimensions[k].parent=dst
        from copy import copy
        for originals,copies in ((ws.column_dimensions,dst.column_dimensions),(ws.row_dimensions,dst.row_dimensions)):
            for key,dimension in originals.items():
                for attr in ('font','fill','border','alignment','number_format','protection'):
                    setattr(copies[key],attr,copy(getattr(dimension,attr)))
        dst.sheet_format=__import__('copy').copy(ws.sheet_format)
        dst.sheet_properties=__import__('copy').copy(ws.sheet_properties)
        dst.print_options=__import__('copy').copy(ws.print_options)
        dst.page_margins=__import__('copy').copy(ws.page_margins)
        dst.page_setup=__import__('copy').copy(ws.page_setup)
        dst.freeze_panes=ws.freeze_panes
        from copy import deepcopy
        dst.sheet_view.showGridLines=ws.sheet_view.showGridLines
        dst.sheet_view.zoomScale=ws.sheet_view.zoomScale
        dst.data_validations=deepcopy(ws.data_validations)
        dst.conditional_formatting=deepcopy(ws.conditional_formatting)
        dst.protection=deepcopy(ws.protection)
        dst.auto_filter=deepcopy(ws.auto_filter)
        from copy import deepcopy
        dst.print_area=ws.print_area
        dst.print_title_rows=ws.print_title_rows
        dst.print_title_cols=ws.print_title_cols
        dst.HeaderFooter=deepcopy(ws.HeaderFooter)
        dst.row_breaks=deepcopy(ws.row_breaks)
        dst.col_breaks=deepcopy(ws.col_breaks)
        for picture in ws._images:
            from openpyxl.drawing.image import Image
            image=Image(io.BytesIO(picture._data()));image.anchor=deepcopy(picture.anchor)
            dst.add_image(image)
        if bake:
            for originals,copies in ((ws.column_dimensions,dst.column_dimensions),(ws.row_dimensions,dst.row_dimensions)):
                for key in originals:
                    for attr in ('font','fill','border'):
                        setattr(copies[key],attr,bake_painted(getattr(originals[key],attr),source_palette))
            for rules in getattr(dst.conditional_formatting,'_cf_rules',{}).values():
                for rule in rules:
                    dxf=getattr(rule,'dxf',None)
                    if dxf is None:continue
                    if dxf.font is not None:dxf.font=bake_painted(dxf.font,source_palette)
                    if dxf.fill is not None:dxf.fill=bake_painted(dxf.fill,source_palette)
                    if dxf.border is not None:dxf.border=bake_painted(dxf.border,source_palette)
    source.close()

def validate_payload(payload):
    if not isinstance(payload,dict):raise ValueError('Invalid request')
    if not str(payload.get('project','')).strip():raise ValueError('Project name is required')
    if len(str(payload.get('project','')))>180:raise ValueError('Project name too long')
    if len(str(payload.get('location','')))>180:raise ValueError('Location too long')
    if payload.get('standard','Commercial') not in ('Commercial','USACE'):raise ValueError('Unknown project standard')
    if payload.get('layout','individual') not in ('individual','grouped'):raise ValueError('Unknown report layout')
    selected=payload.get('templates',[])
    if not isinstance(selected,list) or not selected or any(not isinstance(t,str) for t in selected) or len(selected)!=len(set(selected)) or any(t not in LOOKUP for t in selected):raise ValueError('Choose valid, unique templates')
    records=payload.get('records',[])
    if not isinstance(records,list) or len(records)>MAX_RECORDS:raise ValueError('Invalid review records')
    seen=set()
    for r in records:
        if not isinstance(r,dict):raise ValueError('Invalid equipment record')
        tag=canonical_tag(str(r.get('tag','')))
        if not TAGS.fullmatch(tag) or tag in seen:raise ValueError('Invalid or duplicate equipment tag: '+tag)
        seen.add(tag)
        if str(r.get('status','UNVERIFIED')) not in ('UNVERIFIED','VERIFIED','EXCLUDED'):raise ValueError('Invalid review status')
        if 'template' in r and (not isinstance(r['template'],str) or r['template'] and r['template'] not in UNIT_FORMS):raise ValueError(f'{tag}: unknown unit report form')
        if r.get('status')=='VERIFIED':
            form=unit_form(r)
            if not form:raise ValueError(f'{tag}: select a unit report form or use an approved reference for unsupported equipment')
            if form not in selected:raise ValueError(f'{tag}: include its selected unit report form in the worksheet list')
            if all(r.get(k) in (None,'') for k in UNIT_FORMS[form] if k!='tag'):raise ValueError(f'{tag}: verified equipment requires at least one reviewed design value supported by its form')
        for field in NUMERIC_FIELDS:
            v=r.get(field)
            if v is None or v=='':continue
            try:n=float(v)
            except (ValueError,TypeError):raise ValueError(f'{tag}: invalid {field}')
            if not math.isfinite(n) or n<0 or n>1_000_000:raise ValueError(f'{tag}: out-of-range {field}')
        for field in TEXT_FIELDS:
            if field in r and (not isinstance(r[field],str) or len(r[field])>120):raise ValueError(f'{tag}: invalid {field}')
        if r.get('osa_min_cfm') not in (None,''):
            if unit_form(r)!='Air Moving Equipment.xlsx':raise ValueError(f'{tag}: minimum outside air requires an air-moving form')
            if r.get('osa_cfm') in (None,'') or float(r['osa_min_cfm'])>float(r['osa_cfm']):raise ValueError(f'{tag}: minimum outside air must not exceed maximum outside air')
        if r.get('design_cfm') not in (None,'') and r.get('osa_cfm') not in (None,'') and float(r['osa_cfm'])>float(r['design_cfm']):raise ValueError(f'{tag}: outside-air CFM exceeds total design CFM')

def populate_equipment(wb,records,selected):
    """Only verified records get populated. Original worksheet cells are mapped by their actual labels."""
    count=0
    pages={}
    for rec in records:
        if rec.get('status')!='VERIFIED':continue
        tag=str(rec.get('tag','')).strip().upper()
        kind=unit_form(rec)
        if not kind or kind not in selected:continue
        # Fill the existing side-by-side Design/Actual slots before copying a page.
        slots=[(0,0)]
        if kind in ('Fan Coil Units DX.xlsx','Fan Coil Units WTR.xlsx'):
            slots=[(col,0) for col in (0,2,4,6)]
        elif kind=='Exhaust Fans _Sm._.xlsx':
            slots=[(col,row) for row in (0,13) for col in (0,2,4,6)]
        previous,index=pages.get(kind,(None,0))
        if index % len(slots)==0:
            before=set(wb.sheetnames);add_template(wb,LOOKUP[kind]);created=[n for n in wb.sheetnames if n not in before]
            if not created:continue
            ws=wb[created[0]];reset_measurements(ws)
        else:ws=previous
        coloff,rowoff=slots[index % len(slots)];pages[kind]=(ws,index+1)
        from openpyxl.utils.cell import coordinate_from_string,column_index_from_string,get_column_letter
        def shifted(address):
            col,row=coordinate_from_string(address)
            return f'{get_column_letter(column_index_from_string(col)+coloff)}{row+rowoff}'
        cells={key:shifted(addr) for key,addr in UNIT_FORMS[kind].items()};ws[cells['tag']]=tag
        if kind=='Air Moving Equipment.xlsx':
            # The original single-OSA form uses operating/minimum OSA.
            # Maximum OSA remains in the review log and traverse target.
            if rec.get('osa_min_cfm') not in (None,''):
                cells.pop('osa_cfm',None);cells['osa_min_cfm']='G18'
            populate_identity(ws,rec,excel_safe)
        for key,addr in cells.items():
            if key=='tag' or key in TEXT_CELLS:continue
            if addr and rec.get(key) not in (None,'') and ws[addr].data_type!='f':ws[addr]=float(rec[key])
        for key,addr in cells.items():
            if key in TEXT_CELLS and rec.get(key) not in (None,'') and ws[addr].data_type!='f':
                ws[addr]=excel_safe(str(rec[key]))
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
    records=sorted([{**r,'tag':canonical_tag(r['tag'])} for r in payload.get('records',[])],key=lambda r:[int(t) if t.isdigit() else t for t in re.split(r'(\d+)',r['tag'])])
    if not isinstance(records,list):raise ValueError('Invalid review records')
    requested=[name for name in selected if not banned_initial_template(name)]
    equipment=[]
    for name in requested:
        if name in OFFICE_FRONT or name in (RECT_TEMPLATE,RND_TEMPLATE) or name in equipment:continue
        equipment.append(name)
    theme_sources=equipment+[RECT_TEMPLATE,RND_TEMPLATE,'Notes.xlsx','Air Moving Equipment.xlsx']
    for theme_name in theme_sources:
        if theme_name in LOOKUP:
            theme=read_theme(LOOKUP[theme_name])
            if theme:
                wb.loaded_theme=theme
                break
    def add_fresh(name):
        before=set(wb.sheetnames);add_template(wb,LOOKUP[name])
        for title in set(wb.sheetnames)-before:reset_measurements(wb[title])
    for name in OFFICE_FRONT:
        if name in LOOKUP:add_fresh(name)
    verified_air=any(isinstance(r,dict) and r.get('status')=='VERIFIED' and unit_form(r)=='Air Moving Equipment.xlsx' for r in records)
    for name in equipment:
        if name in UNIT_FORMS and any(isinstance(r,dict) and r.get('status')=='VERIFIED' and unit_form(r)==name for r in records):continue
        if name=='Coil DX GAS HT.xlsx' and verified_air:continue
        add_fresh(name)
    support=list(equipment)
    if RECT_TEMPLATE in LOOKUP and RECT_TEMPLATE not in support:support.append(RECT_TEMPLATE)
    populate_support(wb,records,support,LOOKUP,add_template,reset_measurements,sheet_name)
    populate_equipment(wb,records,equipment)
    prepare_documentation(wb,excel_safe(project),excel_safe(str(payload.get('location',''))),support)
    def copies(filename):return sum(1 for ws in wb.worksheets if getattr(ws,'_template_file',None)==filename)
    if RECT_TEMPLATE in LOOKUP:
        while copies(RECT_TEMPLATE)<BLANK_RECT_FORMS:add_fresh(RECT_TEMPLATE)
    if RND_TEMPLATE in LOOKUP:
        while copies(RND_TEMPLATE)<BLANK_RND_FORMS:add_fresh(RND_TEMPLATE)
    for ws in list(wb.worksheets):
        if banned_initial_sheet(ws.title):wb.remove(ws)
    def sheet_rank(ws):
        filename=getattr(ws,'_template_file',None)
        title=ws.title.strip().upper()
        if filename=='Project Information.xlsx' or title=='PROJECT INFO':return 0
        if filename=='Notes.xlsx' or title=='NOTES':return 1
        if filename==RECT_TEMPLATE or title.startswith('DUCT TRAVERSE RECT'):return 3
        if filename==RND_TEMPLATE or title.startswith('DUCT TRAVERSE RND'):return 4
        return 2
    wb._sheets.sort(key=sheet_rank)
    if wb.sheetnames:wb.active=0
    if not wb.sheetnames:
        raise ValueError('No worksheets were generated')
    wb.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True)
    origins={ws.title:ws._template_origin for ws in wb if hasattr(ws,'_template_origin')}
    for ws in wb:
        if hasattr(ws,'_template_formulas') and ws._template_formulas!={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}:
            raise ValueError('Build stopped: a template formula changed on '+ws.title)
    out=io.BytesIO();wb.save(out)
    return group_template_sheets(preserve_template_parts(out.getvalue(),origins),origins)

PAGE='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ABP TAB Report Builder</title><link rel="icon" type="image/png" sizes="32x32" href="/favicon.png"><link rel="icon" href="/favicon.ico" sizes="any"><style>
:root{color-scheme:dark;--bg:#0b1422;--panel:#131f30;--line:#304259;--ink:#edf3fc;--muted:#a9bad0;--accent:#67d4c3;--blue:#77b8f8;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:90px}body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6}button,input,select{font:inherit}button,a,input,select{touch-action:manipulation}[hidden]{display:none!important}a{color:var(--blue)}header{display:flex;align-items:center;gap:20px;max-width:1200px;margin:auto;padding:22px 28px;border-bottom:1px solid var(--line)}header img{width:180px;height:60px;object-fit:contain;background:#fff;padding:8px;border-radius:8px}.brand-name{font-weight:750;font-size:13px}.brand-sub{color:var(--muted);font-size:12px}.wrap{max-width:1200px;margin:auto;padding:32px 28px 48px}.hero{padding:8px 0 30px}.hero-row{display:flex;justify-content:space-between;align-items:end;gap:24px}.eyebrow{color:var(--accent);font-size:11px;font-weight:750;letter-spacing:1.8px;text-transform:uppercase}h1{font-size:clamp(28px,4vw,42px);letter-spacing:-1.4px;line-height:1.15;margin:12px 0}p{margin:10px 0 18px}.hero p{max-width:630px;color:var(--muted);font-size:15px}.draft-pill{border:1px solid #395566;background:#172d36;color:#a5e5da;padding:7px 12px;border-radius:6px;font-size:11px;white-space:nowrap}.workspace-nav{position:sticky;top:0;z-index:5;display:flex;gap:6px;background:#0b1422f5;border-block:1px solid var(--line);padding:10px 0;margin:0 0 24px;backdrop-filter:blur(12px)}.workspace-nav a{color:var(--muted);text-decoration:none;padding:8px 14px;border-radius:6px;font-size:12px;font-weight:650}.workspace-nav a:hover,.workspace-nav a:focus{background:#22354b;color:#fff}.workspace-layout{display:grid;grid-template-columns:minmax(0,1fr) 252px;gap:24px;align-items:start}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:26px;margin-bottom:20px}.card h2{display:flex;align-items:center;gap:12px;font-size:18px;letter-spacing:-.3px;margin:0 0 18px}.step{display:inline-grid;place-items:center;width:30px;height:30px;flex-shrink:0;border:1px solid #3b536e;border-radius:7px;color:var(--blue);font-size:11px;letter-spacing:.5px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}label{display:block;margin:10px 0 16px;font-size:12px;font-weight:650;color:#ccdaec}input[type=text],input[type=search],select,.review-table input{display:block;margin-top:7px;width:100%;min-height:44px;padding:10px 12px;border:1px solid #455973;border-radius:7px;background:#0d1828;color:var(--ink)}input::placeholder{color:#899db7}input[type=checkbox]{accent-color:var(--accent);width:16px;height:16px;vertical-align:middle}input[type=file]{display:block;width:100%;margin:9px 0;padding:22px 16px;background:#101e30;border:1px dashed #567594;border-radius:9px;color:var(--muted);font-size:12px}input[type=file]::file-selector-button{background:#263b53;color:#edf5ff;padding:9px 12px;border:1px solid #4b637e;border-radius:6px;margin-right:12px;cursor:pointer}button{background:#3b88d4;color:#fff;padding:10px 16px;min-height:42px;font-weight:650;font-size:12px;border:1px solid #65a8e6;border-radius:7px;cursor:pointer;transition:background .15s}button:hover{background:#4c9be4}button:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #79bfff;outline-offset:3px}#selectall,#clear,#saveproject{background:#1b2d43;border-color:#415772;color:#dce9fa}#selectall:hover,#clear:hover,#saveproject:hover{background:#2a415b}#generate{background:#68d3bd;border-color:#68d3bd;color:#092e2c;font-size:14px;min-width:235px;min-height:48px}#generate:hover{background:#88e5d1}small,.muted{color:var(--muted);font-weight:400}.card>p.muted{font-size:13px}.template-toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px}.template-toolbar input{margin:0;min-width:0;flex:1}.templates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:330px;overflow:auto;padding:3px}.template{display:flex;align-items:center;gap:9px;padding:12px;margin:0;min-height:48px;background:#101d2d;border:1px solid #354960;border-radius:7px;font-size:12px;font-weight:500;cursor:pointer;line-height:1.4}.template input{flex-shrink:0}.template:has(input:checked){background:#173b40;border-color:#4c9189;color:#d4fff3}.template:hover{border-color:#7ea5c9}.recommend-summary{font-size:12px;background:#11273a;border:1px solid #345773;padding:16px;border-radius:8px;margin:16px 0}.recommend-summary p{margin:8px 0}.recommend-item{padding:9px 0;border-top:1px solid #344b61;display:flex;gap:12px;justify-content:space-between}.recommend-item small{text-align:right;max-width:50%}.recommend-item em{display:inline-block;color:#f7cb88;font-size:10px;font-style:normal;margin-left:5px}.review-scroll{overflow:auto;max-height:420px;border:1px solid var(--line);border-radius:8px}.review-table{width:100%;border-collapse:collapse;font-size:12px}.review-table th{position:sticky;top:0;background:#25364b;text-align:left;z-index:1}.review-table td,.review-table th{padding:10px;border-bottom:1px solid var(--line)}.review-table input{min-width:82px;margin:0}.review-table select{min-width:120px;margin:0}.review-table tr:hover{background:#1b2c41}.tag{display:inline-block;background:#23415b;padding:3px 8px;border-radius:5px;margin:3px}.warn{color:#ffd18c}.success{color:#97e4c3}#scanstatus,#status,#reference-summary{font-size:13px;overflow-wrap:anywhere}#status:not(:empty),#reference-summary:not(:empty){border-left:3px solid var(--blue);background:#10263a;padding:14px;margin-top:18px;border-radius:0 6px 6px 0}.summary{position:sticky;top:88px;padding:22px;background:#101e2e;border:1px solid var(--line);border-radius:12px}.summary h2{font-size:12px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted);margin:0 0 18px}.summary-project{font-size:20px;font-weight:700;line-height:1.3;overflow-wrap:anywhere;margin-bottom:5px}.summary-location{color:var(--muted);font-size:12px}.summary dl{margin:24px 0}.summary dl div{display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding:12px 0;font-size:12px}.summary dt{color:var(--muted)}.summary dd{margin:0;font-weight:650;text-align:right}.summary-note{border-top:1px solid var(--line);padding-top:16px;font-size:12px;color:var(--muted)}.summary-note strong{display:block;color:var(--accent);margin-bottom:6px}.footer-note{font-size:12px;color:var(--muted);margin:22px 2px;max-width:800px}.restore-review{margin:18px 0;border-top:1px solid var(--line);padding-top:16px}.restore-review summary{cursor:pointer;color:var(--muted);font-size:12px}.skip-link{position:absolute;top:-60px;left:16px;z-index:20;background:#fff;color:#123;padding:10px}.skip-link:focus{top:10px}#template-count{font-size:12px;color:var(--accent);margin:8px 0}#reference-panel>p{color:var(--muted);font-size:13px}
@media(max-width:950px){.workspace-layout{grid-template-columns:minmax(0,1fr)}.summary{position:static;display:none}.hero-row{align-items:start}.draft-pill{white-space:normal;max-width:170px}.brand-sub{max-width:190px}.review-table{min-width:720px}}
@media(max-width:600px){header{padding:16px;gap:12px;flex-wrap:wrap}header img{width:150px;height:52px}.brand-name{font-size:11px}.brand-sub{font-size:10px;max-width:150px}header form{margin-left:0!important}header form button{min-height:36px}.wrap{padding:24px 16px}.hero-row{display:block}.draft-pill{display:inline-block;max-width:none;margin-top:8px}.hero p{font-size:13px}.workspace-nav{overflow:auto;white-space:nowrap;gap:0}.workspace-nav a{padding:8px 10px}.card{padding:20px 16px}.grid{grid-template-columns:1fr;gap:0}.templates{grid-template-columns:1fr}.template-toolbar{flex-wrap:wrap}.template-toolbar input{flex-basis:100%}.recommend-item{display:block}.recommend-item small{display:block;text-align:left;max-width:none}#generate{width:100%}.review-scroll{max-height:500px}.review-table{min-width:760px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}

.review-table,.review-table tbody{display:block;min-width:0!important}.review-table thead{display:none}.review-table tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:16px;border-bottom:1px solid var(--line)}.review-table td{display:block;padding:0;border:0;min-width:0;overflow-wrap:anywhere}.review-table td:first-child,.review-table td:nth-child(2),.review-table td:nth-child(10),.review-table td:nth-child(11){grid-column:1/-1}.review-table td:first-child{font-size:17px;font-weight:750;color:var(--accent)}.review-table input,.review-table select{min-width:0;width:100%}.review-table td:before{display:block;color:var(--muted);font-size:11px;margin:0 0 5px}.review-table td:nth-child(2):before{content:'Unit report form'}.review-table td:nth-child(3):before{content:'Design CFM'}.review-table td:nth-child(4):before{content:'Outside-air max / single CFM'}.review-table td:nth-child(5):before{content:'Outside-air min CFM'}.review-table td:nth-child(6):before{content:'ESP (in. w.c.)'}.review-table td:nth-child(7):before{content:'Motor HP'}.review-table td:nth-child(8):before{content:'Design GPM'}.review-table td:nth-child(9):before{content:'Verification'}.review-table td:nth-child(10):before{content:'Source design candidates'}.review-table td:nth-child(11):before{content:'Source location'}.review-table details{margin-top:8px}.review-scroll{max-height:650px}

/* Report building workflow polish. */
.hero{padding:18px 0 32px}.hero h1{font-size:clamp(30px,4vw,44px)}
.workspace-nav a:last-child{margin-left:auto;color:var(--accent);background:#163037;border:1px solid #345d60}
.card{box-shadow:0 8px 28px #00000014}.card h2{margin-bottom:20px}
#build-card{border-color:#477a79;background:linear-gradient(135deg,#142b36,#132034)}
#build-card .step{border-color:#68d3bd;color:#9aebd9}
.build-action{display:flex;align-items:center;gap:22px;margin-top:24px;padding-top:22px;border-top:1px solid #36515c}
.build-action strong{display:block;font-size:12px;color:#e0f0f4}.build-action span{display:block;font-size:12px;color:var(--muted);margin-top:4px}
#generate{min-width:220px;border-radius:9px;box-shadow:0 5px 20px #071b2440}
.summary dd{font-variant-numeric:tabular-nums}.summary-note{line-height:1.7}
@media(max-width:600px){.workspace-nav a:last-child{margin-left:0}.build-action{flex-direction:column;align-items:stretch;gap:12px}.build-action div{text-align:center}.hero{padding-top:8px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}button{transition:none}}

.empty-review{padding:18px;border:1px dashed #45627e;border-radius:8px;color:var(--muted)}
.review-table summary{cursor:pointer;color:#b8ddff;padding:6px 0}
.review-table details p{padding:10px 12px;background:#0d1a29;border-radius:6px}
#template-count{min-height:20px}#generate[aria-busy=true]{cursor:progress}
@media(max-width:600px){.review-table tr{grid-template-columns:1fr}.review-table td{grid-column:1!important}.workspace-nav{display:grid;grid-template-columns:1fr 1fr;gap:4px;overflow:visible}.workspace-nav a{text-align:center;min-width:0}.workspace-nav a:last-child{margin:0}html{scroll-padding-top:120px}}
#files,#reference-file{padding:26px 18px;border:1.5px dashed #6a90ae;border-radius:12px;background:#0e1c2e;transition:border-color .15s,background-color .15s,box-shadow .15s}
#files:hover,#reference-file:hover,#files:focus-visible,#reference-file:focus-visible{border-color:#67d4c3;background:#12283a;box-shadow:inset 0 0 0 1px #67d4c322}
#files::file-selector-button,#reference-file::file-selector-button{background:#1d3c56;border-color:#5f87a6;font-weight:650;padding:10px 14px;border-radius:7px}
#files::file-selector-button:hover,#reference-file::file-selector-button:hover{background:#265072;border-color:#67d4c3;color:#fff}
</style><body><a class="skip-link" href="#project-card">Skip to report builder</a><header><img src="/logo.png" alt="Air Balance Professionals company logo"><div><div class="brand-name">Air Balance Professionals</div><div class="brand-sub">Technical reporting workspace &nbsp;·&nbsp; NEBB #3861</div></div><form action="/logout" method="post" style="margin-left:auto"><button type="submit" style="background:#eff6ff;color:#16508c;border:1px solid #c8daef;min-height:38px;padding:8px 12px;white-space:nowrap">Sign out</button></form></header><main class="wrap"><section class="hero" aria-label="Report builder introduction"><div class="hero-row"><div><div class="eyebrow">ABP / Field engineering tools</div><h1>Build your TAB report</h1><p>Start with your job documents or an approved report. Review the design, choose your worksheets, and build a pre-field report in Excel.</p></div><span class="draft-pill">PRE-FIELD WORKSPACE</span></div></section><nav class="workspace-nav" aria-label="Report sections"><a href="#project-card">01 Project</a><a href="#basis-card">02 Report basis</a><a href="#template-panel" id="templates-nav">03 Worksheets</a><a href="#build-card">04 Build report</a></nav><div class="workspace-layout"><div><div class="card" id="project-card"><h2><span class="step">01</span> Project details</h2><div class="grid"><label>Project name<input id="project" type="text" placeholder="Project / facility name"></label><label>Location<input id="location" type="text" placeholder="City, State"></label></div><label>Standard<select id="standard"><option value="Commercial">Commercial · ±10% target</option><option value="USACE">USACE · ±5% target (DALT prerequisite)</option></select></label></div><div class="card" id="basis-card"><h2><span class="step">02</span> Choose your report source</h2><label>Build method<select id="buildmethod"><option value="sources">Build from source documents and master templates</option><option value="reference">Use an approved report as the design and layout reference</option></select></label><div id="reference-panel" hidden><p>Use a report for this same project whose design values and equipment list you have approved. This keeps its report pages, grouped Design/Actual columns, formulas and branding. Field measurements, serial numbers and signoffs are cleared. Source scans do not overwrite this report.</p><label>Approved reference workbook<input id="reference-file" type="file" accept=".xlsx"></label><button id="inspect-reference" type="button">Review reference report</button><div id="reference-summary" role="status" aria-live="polite"></div><label><input id="reference-approved" type="checkbox"> Use this reference’s equipment list and design values for this project, including differences from drawings.</label></div></div><div class="card" id="source-panel"><h2>Upload source documents</h2><input id="files" aria-label="Project source documents" type="file" accept=".pdf,.xlsx,.csv" multiple><p class="muted">PDF mechanical sheets, approved submittals, Excel and CSV schedules. Text-based extraction only; always review the M-sheet takeoff and latest revision.</p><button id="scan">Scan uploaded files</button><p id="scanstatus" role="status" aria-live="polite"></p><div id="tags"></div><div id="review"></div></div><div class="card" id="template-panel"><h2><span class="step">03</span> Choose report worksheets</h2><p class="muted">Select the actual ABP worksheets to include. Original layouts, formatting, print settings and formulas are preserved. Each copy stays on its own sheet; only existing input cells are filled.</p><div class="template-toolbar"><input id="template-search" type="search" aria-label="Search report worksheets" placeholder="Find a worksheet…"><button id="selectall" type="button">Select all</button> <button id="clear" type="button">Clear</button></div><div id="template-recommendations" class="recommend-summary" aria-live="polite">A pre-field worksheet pack is checked to start. Scan source documents to match it to this job. You can change any selection before building.</div><p id="template-count" aria-live="polite"></p><div class="templates" id="templates"></div></div><div class="card" id="build-card"><h2><span class="step">04</span> Build report</h2><p class="muted" id="build-description">Build an Excel report with one tab per selected equipment form and verified design values. Additional equipment pages continue down the same tab. Equipment still needing review stays in the review log. Unsupported unit forms need an approved reference or manual preparation.</p><details class="restore-review" id="review-tools"><summary>Save or restore project progress</summary><p class="muted">Keep your reviewed tags and worksheet selections for next time.</p><button id="saveproject" type="button">Save project review (.json)</button> <label>Restore saved review<input id="loadproject" type="file" accept=".json,application/json"></label></details><div class="build-action"><button id="generate">Build report</button><div><strong>Excel report · .xlsx</strong><span>Downloads to your device when the build is complete.</span></div></div><p id="status" role="status" aria-live="polite"></p></div></div><aside class="summary" aria-label="Report summary"><h2>Your report</h2><div id="summary-project" class="summary-project">Untitled project</div><div id="summary-location" class="summary-location">Add a location to get started</div><dl><div><dt>Report basis</dt><dd id="summary-basis">Source documents</dd></div><div><dt id="summary-count-label">Worksheets</dt><dd id="summary-count">—</dd></div><div><dt>Equipment entries</dt><dd id="summary-equipment">0</dd></div><div><dt>Design review</dt><dd id="summary-review">No equipment yet</dd></div><div><dt>Report format</dt><dd>Excel · .xlsx</dd></div></dl><div class="summary-note"><strong>Built for pre-field preparation</strong>Design values stay separate from measurements. Add field readings and approvals after testing.</div></aside></div><p class="footer-note"><span aria-hidden="true">ⓘ</span> Pre-field draft only. All extracted values require review; final TAB reports require engineering verification and field signoff.</p></main><script>
__UI_HELPERS__
const savedTagPattern=new RegExp(__TAG_PATTERN__,'i');
let templatesReady=false,templateError='';
const defaultPack=new Set(__DEFAULT_PACK_JSON__);
let inspectedReference=null;
function referenceForm(){const f=$('reference-file').files[0];if(!f)throw Error('Choose an approved reference workbook');if(f.size>8000000)throw Error('Reference workbook exceeds 8 MB');const form=new FormData();form.append('reference',f);return form}
function resetReference(){inspectedReference=null;referenceEntryCount=0;$('status').textContent='';$('reference-approved').checked=false;$('reference-summary').textContent='Review the selected reference before building.'}
async function generateReference(){try{if(!inspectedReference||inspectedReference!==$('reference-file').files[0])throw Error('Review the selected reference first');if(!$('reference-approved').checked)throw Error('Confirm the reference equipment list and design values');if(!$('project').value.trim())throw Error('Enter the project name');$('generate').disabled=true;$('generate').textContent='Building report…';$('generate').setAttribute('aria-busy','true');$('status').textContent='Building report from approved reference...';const form=referenceForm();form.append('project',$('project').value);form.append('location',$('location').value);form.append('approved','true');const r=await fetch('/api/reference/build',{method:'POST',body:form});if(!r.ok)await readApiJson(r);const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=($('project').value.replace(/[^a-z0-9_-]+/gi,'_')||'ABP')+'_PreField_TAB.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent='Report built from your approved reference. Design values and report layout retained; field measurements and signoffs cleared.'}catch(e){$('status').textContent=e.message}finally{$('generate').disabled=false;$('generate').textContent='Build report';$('generate').removeAttribute('aria-busy')}}
window.addEventListener('DOMContentLoaded',()=>{
 const sourceDescription=$('build-description').textContent; $('buildmethod').onchange=()=>{const ref=$('buildmethod').value==='reference';$('status').textContent='';$('source-panel').hidden=ref;$('template-panel').hidden=ref;$('build-description').textContent=ref?'Build the approved reference report with its design data and page layout. Actual field readings and signoffs will be blank.':sourceDescription;$('reference-panel').hidden=$('buildmethod').value!=='reference';$('scan').disabled=$('buildmethod').value==='reference';$('saveproject').disabled=$('buildmethod').value==='reference';$('loadproject').disabled=$('buildmethod').value==='reference';$('template-recommendations').textContent=$('buildmethod').value==='reference'?'Reference mode uses the approved workbook’s sheets. Template selections below are ignored.':'A pre-field worksheet pack is checked to start. Scan source documents to match it to this job. You can change any selection before building.'};
 $('reference-file').onchange=resetReference;
 $('inspect-reference').onclick=async()=>{resetReference();$('inspect-reference').disabled=true;$('reference-summary').textContent='Checking workbook layouts and equipment…';try{const file=$('reference-file').files[0],form=referenceForm();const r=await fetch('/api/reference/inspect',{method:'POST',body:form});const info=await readApiJson(r);if(file!==$('reference-file').files[0])return;inspectedReference=file;referenceEntryCount=info.units.length;$('reference-summary').textContent=info.sheets.length+' report sheets: '+info.sheets.join(', ')+'. '+info.units.length+' equipment entries: '+info.units.map(x=>x.tag).join(', ')+'. '+info.note}catch(e){$('reference-summary').textContent=e.message}finally{$('inspect-reference').disabled=false;updateWorkspace()}};
});

let tags=[],records=[];const $=id=>document.getElementById(id);async function init(){let t=await readApiJson(await fetch('/api/templates'));if(!Array.isArray(t)||t.some(x=>typeof x!=='string'))throw Error('Invalid worksheet list. Refresh the page to try again.');$('templates').innerHTML=t.map(x=>`<label class="template"><input type="checkbox" value="${x.replaceAll('&','&amp;').replaceAll('"','&quot;')}">${worksheetLabel(x).replaceAll('&','&amp;').replaceAll('<','&lt;')}</label>`).join('');for(const box of document.querySelectorAll('.template input'))box.checked=defaultPack.has(box.value);templatesReady=true;updateWorkspace()}init().catch(e=>{templateError=e.message;updateWorkspace()});$('selectall').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=true);$('clear').onclick=()=>document.querySelectorAll('.template input').forEach(x=>x.checked=false);
$('files').onchange=()=>{tags=[];records=[];renderReview();$('scanstatus').textContent='Source files changed. Scan these files to review their equipment.';$('status').textContent='';updateWorkspace()};
$('scan').onclick=async()=>{if(!templatesReady){$('scanstatus').textContent=templateError||'Wait for report worksheets to load.';return}let files=$('files').files;if(!files.length){$('scanstatus').textContent='Choose files first';return}let form=new FormData();for(let f of files)form.append('files',f);$('scan').disabled=true;$('files').disabled=true;$('buildmethod').disabled=true;$('generate').disabled=true;$('loadproject').disabled=true;$('scanstatus').textContent='Reading files...';try{let r=await fetch('/api/scan',{method:'POST',body:form});let data=await readApiJson(r);tags=data.tags||[];records=(data.records||[]).map(row=>{const copy={...row};applyProposed(copy);return copy});$('scanstatus').textContent=`Found ${tags.length} equipment entries. Review the suggested design values and verify each unit before you build the report.`+(data.warnings.length?' Warnings: '+data.warnings.join(' | '):'');$('tags').innerHTML='';renderReview();let recommendation=await readApiJson(await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags,signals:data.signals||[],sparse:data.sparse===true})}));if(!Array.isArray(recommendation.recommended))throw Error('Template recommendations unavailable');let chosen=new Set(recommendation.recommended.map(x=>x.name));document.querySelectorAll('.template input').forEach(x=>x.checked=chosen.has(x.value));let safe=x=>String(x||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');$('template-recommendations').innerHTML='<strong>Recommended '+recommendation.recommended.length+' ABP templates</strong><p>Selected automatically based on the uploaded documents. Review and change any checked boxes before building your report.</p>'+recommendation.recommended.map(x=>'<div class="recommend-item"><span>'+safe(worksheetLabel(x.name))+(x.review?' <em>Review type</em>':'')+'</span><small>'+safe(x.reason)+'</small></div>').join('')+'<p class="muted">'+safe(recommendation.review_note)+'</p>'}catch(e){$('scanstatus').textContent=e.message}finally{$('scan').disabled=false;$('files').disabled=false;$('buildmethod').disabled=false;$('generate').disabled=false;$('loadproject').disabled=false;updateWorkspace()}};

const unitForms=__UNIT_FORMS_JSON__;
function defaultUnitForm(tag){if(/^(AHU|RTU|OAU|DOAS|MAU|AC)[- ]?[0-9]/.test(tag))return 'Air Moving Equipment.xlsx';if(/^(EF|KEF|TEF|CEF|SEF)[- ]?[0-9]/.test(tag))return 'Exhaust Fans _Std._.xlsx';if(/^(VRF|SSAU)[- ]?[0-9]/.test(tag))return 'Fan Coil Units DX.xlsx';if(/^KH[- ]?[0-9]/.test(tag))return 'Kitchen Hood.xlsx';return ''}
function applyProposed(record){record.status='UNVERIFIED';for(const [field,value] of Object.entries(record.proposed||{})){if(field==='manufacturer'||field==='model')continue;if(record[field]===undefined||record[field]===null||record[field]==='')record[field]=value}for(const [field,value] of Object.entries(record.text_proposed||{})){if(field==='manufacturer'||field==='model')continue;if(record[field]===undefined||record[field]===null||record[field]==='')record[field]=value}if(record.template===undefined||record.template===null)record.template=defaultUnitForm(record.tag)}
function renderReview(){
 if(!records.length){$('review').innerHTML='<p class="empty-review">No equipment to review yet. Scan your project documents to get started.</p>';return}
 const safe=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
 $('review').innerHTML='<p>Review design candidates against this job’s sources, choose a unit form, then mark the record Verified. Past field measurements are never new design values. Equipment shares its applicable worksheet tab. Existing multi-unit spaces are filled first; additional forms continue below. Template designs and calculation logic are preserved; copied formulas follow their page. The standard single-OSA form uses minimum OSA when supplied; maximum OSA stays in the review log and traverse targets. Calculated template cells are never overwritten. Supporting coil, diffuser and traverse worksheets are selected below.</p><div class="review-scroll"><table class="review-table"><thead><tr><th>Tag</th><th>Unit form</th><th>Design CFM</th><th>OSA max / single CFM</th><th>OSA min CFM</th><th>ESP</th><th>Motor HP</th><th>Design GPM</th><th>Review</th><th>Design candidates</th><th>Source</th></tr></thead><tbody>'+records.map((r,i)=>`<tr><td>${safe(r.tag)}</td><td><select aria-label="${safe(r.tag)} report form" data-form="${i}"><option value="">Choose a unit form</option>${Object.keys(unitForms).map(name=>`<option value="${safe(name)}">${safe(worksheetLabel(name))}</option>`).join('')}</select></td>${['design_cfm','osa_cfm','osa_min_cfm','esp','motor_hp','design_gpm'].map(k=>`<td><input aria-label="${safe(r.tag+' '+k)}" type="number" min="0" step="any" data-row="${i}" data-field="${k}" value="${safe(r[k])}"></td>`).join('')}<td><select aria-label="${safe(r.tag)} verification" data-status="${i}"><option value="UNVERIFIED">Unverified</option><option value="VERIFIED">Verified</option><option value="EXCLUDED">Excluded</option></select></td><td>${(r.candidates||[]).length?`<button type="button" data-candidates="${i}">Use undisputed candidates</button><details><summary>${r.candidates.length} source entries</summary>${r.candidates.map(c=>`<p>${safe(Object.entries(c.values).map(([k,v])=>k+': '+v).join(', '))}<br><small>${safe(c.source)} · ${safe(c.reference)}</small></p>`).join('')}</details>`:'No labeled design values found'}${(r.flags||[]).length?`<p class="warn">${r.flags.map(safe).join('<br>')}</p>`:''}</td><td>${safe(r.source)} · ${safe(r.reference)}</td></tr>`).join('')+'</tbody></table></div><p id="candidate-notice" role="status"></p>';
 $('review').insertAdjacentHTML('beforeend','<details><summary>Reviewed submittal details and coil design</summary>'+records.map((r,i)=>`<fieldset><legend>${safe(r.tag)}</legend><div class="grid">${reviewTextFields.map(k=>`<label>${safe(fieldLabel(k))}<input type="text" maxlength="120" aria-label="${safe(r.tag+' '+k)}" data-text-row="${i}" data-text-field="${k}" value="${safe(r[k])}"></label>`).join('')}${reviewNumericFields.filter(k=>!['design_cfm','osa_cfm','osa_min_cfm','esp','motor_hp','design_gpm'].includes(k)).map(k=>`<label>${safe(fieldLabel(k))}<input type="number" min="0" step="any" aria-label="${safe(r.tag+' '+k)}" data-row="${i}" data-field="${k}" value="${safe(r[k])}"></label>`).join('')}</div></fieldset>`).join('')+'</details>');
 document.querySelectorAll('[data-text-row]').forEach(el=>el.oninput=()=>{records[+el.dataset.textRow][el.dataset.textField]=el.value;records[+el.dataset.textRow].status='UNVERIFIED';document.querySelector('[data-status="'+el.dataset.textRow+'"]').value='UNVERIFIED'});
 document.querySelectorAll('[data-row]').forEach(el=>el.oninput=()=>{records[+el.dataset.row][el.dataset.field]=el.value;records[+el.dataset.row].status='UNVERIFIED';document.querySelector('[data-status="'+el.dataset.row+'"]').value='UNVERIFIED'});
 document.querySelectorAll('[data-status]').forEach(el=>{el.value=records[+el.dataset.status].status||'UNVERIFIED';el.onchange=()=>{records[+el.dataset.status].status=el.value}});
 document.querySelectorAll('[data-form]').forEach(el=>{const r=records[+el.dataset.form];el.value=r.template??defaultUnitForm(r.tag);el.onchange=()=>{r.template=el.value;r.status='UNVERIFIED';document.querySelectorAll('.template input').forEach(box=>{if(box.value===el.value)box.checked=true});renderReview();updateWorkspace()}});
 document.querySelectorAll('[data-candidates]').forEach(el=>el.onclick=()=>{
  const r=records[+el.dataset.candidates];
  applyProposed(r);renderReview();
  $('candidate-notice').textContent='Suggested values are ready for '+r.tag+'. Manufacturer and model stay blank. Verify before building.'+((r.flags||[]).length?' '+r.flags.join(' '):'');
 });
}
function projectPayload(){return {project:$('project').value,location:$('location').value,standard:$('standard').value,layout:'individual',tags,records,templates:[...document.querySelectorAll('.template input:checked')].map(x=>x.value)}}
$('saveproject').onclick=()=>{const data=JSON.stringify({format:'ABP-PREFIELD-REVIEW',version:1,...projectPayload()},null,2);const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ABP_Project_Review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)};
$('loadproject').onchange=async ev=>{try{const f=ev.target.files[0];if(!f)return;if(f.size>2000000)throw Error('Project review file exceeds 2 MB');if(!templatesReady)throw Error('Wait for report worksheets to load before restoring a review.');const data=validateSavedReview(JSON.parse(await f.text()),[...document.querySelectorAll('.template input')].map(x=>x.value),unitForms,savedTagPattern);$('project').value=String(data.project||'');$('location').value=String(data.location||'');$('standard').value=data.standard==='USACE'?'USACE':'Commercial';records=data.records;tags=records.map(r=>r.tag);document.querySelectorAll('.template input').forEach(x=>x.checked=data.templates.includes(x.value));renderReview();$('status').textContent='Saved review restored. Recheck verification and source revisions before building your report.'}catch(e){$('status').textContent=e.message}};
$('generate').onclick=async()=>{if($('buildmethod').value==='reference'){await generateReference();return}if(!templatesReady){$('status').textContent=templateError||'Wait for report worksheets to load.';return}let payload=projectPayload();if(!payload.project.trim()){$('status').textContent='Add a project name before building your report.';$('project').focus();return}if(!payload.templates.length){$('status').textContent='Select at least one report worksheet.';$('template-panel').scrollIntoView();return}$('generate').disabled=true;$('generate').textContent='Building report…';$('generate').setAttribute('aria-busy','true');$('status').textContent='Building your report...';try{let r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)await readApiJson(r);let blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(payload.project.replace(/[^a-z0-9_-]+/gi,'_')||'ABP')+'_PreField_TAB.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent='Report built. Your Excel download is ready. Review flagged records and source revisions before field use.'}catch(e){$('status').textContent=e.message}finally{$('generate').disabled=false;$('generate').textContent='Build report';$('generate').removeAttribute('aria-busy')}};

function updateWorkspace(){
 const reference=$('buildmethod').value==='reference';
 $('summary-project').textContent=$('project').value.trim()||'Untitled project';
 $('summary-location').textContent=$('location').value.trim()||'Add a location to get started';
 $('summary-basis').textContent=reference?'Approved reference':'Source documents';
 $('summary-count-label').textContent=reference?'Reference':'Worksheets';
 const selected=document.querySelectorAll('.template input:checked').length;
 $('summary-count').textContent=reference?(inspectedReference?'Reviewed':'Needs review'):selected;
 $('summary-equipment').textContent=reference?(inspectedReference?String(referenceEntryCount):'—'):String(records.length);
 const verified=records.filter(r=>r.status==='VERIFIED').length;
 $('summary-review').textContent=reference?(inspectedReference&&$('reference-approved').checked?'Reference approved':'Approval needed'):(records.length?verified+' of '+records.length+' verified':'No equipment yet');
 const query=$('template-search').value.trim().toLowerCase();const matching=[...document.querySelectorAll('.template')].filter(el=>el.textContent.toLowerCase().includes(query)).length;
 $('template-count').textContent=templateError||(!templatesReady?'Loading report worksheets…':query?matching+' matching worksheets · '+selected+' selected':selected+' worksheets selected');
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
DEFAULT_PACK=[item['name'] for item in suggested_templates([],sparse=True)['recommended']]
PAGE=PAGE.replace('__UNIT_FORMS_JSON__',json.dumps(UNIT_FORMS)).replace('__UI_HELPERS__',(ROOT/'abp_ui.js').read_text(encoding='utf-8')).replace('__TAG_PATTERN__',json.dumps('^(?:'+TAGS.pattern+')$')).replace('__DEFAULT_PACK_JSON__',json.dumps(DEFAULT_PACK))
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
<title>Sign in · ABP Report Builder</title><link rel="icon" type="image/png" sizes="32x32" href="/favicon.png"><link rel="icon" href="/favicon.ico" sizes="any"><style>:root{color-scheme:dark;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#f2f6ff;background:#071326}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:22px 15px;background:radial-gradient(ellipse at 10% 20%,#133e78,transparent 45%),radial-gradient(ellipse at 95% 85%,#174c94,transparent 38%),#080f22}.panel{max-width:460px;width:100%;background:linear-gradient(145deg,#1b2a46,#101a30);padding:36px;border:1px solid #506b8c;border-radius:20px;box-shadow:0 25px 80px #0008}.logo{display:block;width:250px;max-width:100%;height:92px;object-fit:contain;padding:10px 16px;background:#fff;border-radius:12px;margin:0 auto 27px}.tag{font-size:11px;font-weight:800;letter-spacing:1.8px;text-transform:uppercase;color:#68c7ff;margin:0 0 10px}h1{margin:0 0 9px;font-size:32px;letter-spacing:-.8px;color:#f5f8ff}p{color:#c1d0e4;font-size:14px;line-height:1.6;margin:0 0 23px}label{display:block;font-weight:700;font-size:13px;color:#edf4ff;margin:16px 0 8px}input{width:100%;min-height:51px;border:1px solid #5d7394;border-radius:10px;font:inherit;padding:12px 14px;background:#182640;color:#fff}input::placeholder{color:#a5b5cf}input:focus{outline:3px solid #248aff50;border-color:#56bdff}button[type=submit]{width:100%;border:1px solid #53aaff;background:linear-gradient(#258cff,#095fca);color:white;border-radius:10px;font-size:15px;font-weight:800;min-height:52px;cursor:pointer;margin-top:25px;box-shadow:0 7px 19px #0757be55}button[type=submit]:hover{background:#258cff}.error{padding:13px;background:#61313d;border:1px solid #bd6a77;color:#ffe3e7;border-radius:9px;font-size:13px;margin:0 0 20px}.note{color:#afc1db;font-size:12px;border-top:1px solid #50617e;margin-top:27px;padding-top:21px;line-height:1.6;text-align:center}@media(max-width:480px){.panel{padding:26px 22px}.logo{width:215px}}</style></head><body><main class="panel"><img class="logo" src="/logo.png" alt="Air Balance Professionals logo"><div class="tag">Secure reporting workspace</div>
<h1>Welcome back</h1><p>Sign in to build your TAB reports with Air Balance Professionals.</p>
{{ERROR}}<form action="/login" method="post"><input type="hidden" name="csrf" value="{{CSRF}}"><label for="user">Username</label><input id="user" name="username" autocomplete="username" required autofocus placeholder="Enter your username">
<label for="pass">Password</label><input id="pass" name="password" type="password" autocomplete="current-password" required placeholder="Enter your password">
<button type="submit">Sign in to build reports</button></form><div class="note">Access is limited to authorized ABP team members. Contact your administrator for your credentials.</div></main></body></html>'''
FAVICON_PNG=(ROOT/'04_Company_Branding/favicon.png').read_bytes()
FAVICON_ICO=(ROOT/'04_Company_Branding/favicon.ico').read_bytes()
# Static page chrome for unknown browser routes. Report APIs keep their own responses.
NOT_FOUND_HTML='''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page not found · ABP Report Builder</title>
<link rel="icon" type="image/png" sizes="32x32" href="/favicon.png">
<link rel="icon" href="/favicon.ico" sizes="any">
<style>
:root{color-scheme:dark;--bg:#0b1422;--panel:#131f30;--line:#304259;--ink:#edf3fc;--muted:#a9bad0;--accent:#67d4c3;--blue:#77b8f8;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.6}
header{display:flex;align-items:center;gap:20px;max-width:1200px;margin:auto;padding:22px 28px;border-bottom:1px solid var(--line)}
header img{width:180px;height:60px;object-fit:contain;background:#fff;padding:8px;border-radius:8px}
.brand-name{font-weight:750;font-size:13px}
.brand-sub{color:var(--muted);font-size:12px}
header form{margin-left:auto}
header button{background:#eff6ff;color:#16508c;border:1px solid #c8daef;min-height:38px;padding:8px 12px;border-radius:7px;font:inherit;font-weight:650;font-size:12px;cursor:pointer;white-space:nowrap}
header button:hover{background:#fff}
main{max-width:720px;margin:0 auto;padding:72px 28px 80px}
.eyebrow{color:var(--accent);font-size:11px;font-weight:750;letter-spacing:1.8px;text-transform:uppercase;margin:0 0 12px}
.code{margin:0;font-size:13px;font-weight:750;letter-spacing:1.6px;color:var(--accent)}
h1{font-size:clamp(32px,5vw,48px);letter-spacing:-1.4px;line-height:1.1;margin:8px 0 14px}
p{margin:0 0 28px;color:var(--muted);max-width:460px}
.home{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:12px 18px;border-radius:8px;background:#68d3bd;color:#092e2c;text-decoration:none;font-weight:750;font-size:14px}
.home:hover{background:#88e5d1}
.home:focus-visible,header button:focus-visible{outline:3px solid #79bfff;outline-offset:3px}
@media(max-width:600px){header{padding:16px;gap:12px;flex-wrap:wrap}header img{width:150px;height:52px}header form{margin-left:0}main{padding:48px 16px 64px}.home{width:100%}}
</style>
</head>
<body>
<header>
<img src="/logo.png" alt="Air Balance Professionals company logo">
<div><div class="brand-name">Air Balance Professionals</div><div class="brand-sub">Technical reporting workspace &nbsp;·&nbsp; NEBB #3861</div></div>
<form action="/logout" method="post"><button type="submit">Sign out</button></form>
</header>
<main>
<p class="eyebrow">ABP / Field engineering tools</p>
<p class="code">404</p>
<h1>Page not found</h1>
<p>This address isn't part of the report builder.</p>
<a class="home" href="/">Back to Report Builder</a>
</main>
</body>
</html>'''
NOT_FOUND_BYTES=NOT_FOUND_HTML.encode('utf-8')
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
        elif path in ('/favicon.ico','/favicon.png','/logo.png'):
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
        if path in ('/favicon.ico','/favicon.png'):
            if path.endswith('.png'):self.respond(FAVICON_PNG,'image/png')
            else:self.respond(FAVICON_ICO,'image/x-icon')
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
        elif path.startswith('/api/'):self.respond(b'Not found','text/plain',404)
        else:self.respond(NOT_FOUND_BYTES,'text/html; charset=utf-8',404)
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
            if n<0 or n>MAX_UPLOAD:raise ValueError('Upload limit is 200 MB')
            data=self.rfile.read(n)
            if path=='/api/suggest':
                if n>2_000_000:raise ValueError('Template suggestion request too large')
                request=json.loads(data)
                self.respond(json.dumps(suggested_templates(request.get('tags',[]),request.get('signals',[]),sparse=request.get('sparse') is True)).encode());return
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
class ReportHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's reverse DNS lookup can block before socket.listen().
        # The application does not need a resolved hostname to serve requests.
        TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]


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
    with ReportHTTPServer((host,port),Handler) as server:
        print(f'Listening on {host}:{server.server_port}; health endpoint /healthz',flush=True)
        server.serve_forever()
