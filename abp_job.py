"""Source-based equipment review and job-specific ABP form assembly."""
import re

NUMERIC_FIELDS = ('design_cfm','osa_cfm','osa_min_cfm','esp','motor_hp','design_gpm',
                  'cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb',
                  'heating_cfm','heating_edb','heating_ldb','heating_input_btu','heating_output_btu',
                  'cooling_total_btu','cooling_sensible_btu')
TEXT_FIELDS = ('manufacturer','model','unit_type','service','equipment_location')
COIL_FIELDS = {'design_cfm':8,'cooling_edb':14,'cooling_ewb':15,'cooling_ldb':16,
               'cooling_lwb':17,'heating_cfm':23,'heating_edb':25,'heating_ldb':26,
               'cooling_total_btu':19,'cooling_sensible_btu':20,'heating_output_btu':28}

def canonical_tag(value):
    return re.sub(r'\s*-\s*|\s+', '-', value.strip().upper())

def postal_match(match, line):
    # Keep real MS equipment tags. Only reject the state + ZIP address shape.
    return bool(re.fullmatch(r'MS\s+\d{5}(?:-\d{4})?', match.group(), re.I))

def performance_candidates(text, tag_pattern):
    """Single tagged performance sheet, including explicit shared tag lists.

    Do not join arbitrary nearby tags and values. The tagged page must identify
    itself as a performance summary and contain exactly one Tag: declaration.
    """
    if not re.search(r'Performance\s+Summary',text,re.I):return []
    declarations=list(re.finditer(r'(?m)^\s*Tag\s*:\s*([^\r\n]+)',text,re.I))
    if len(declarations)!=1:return []
    line=declarations[0].group(1).split('Model')[0]
    match=tag_pattern.search(line)
    if not match:return []
    tags=[canonical_tag(match.group())]
    prefix=re.match(r'([A-Z]+)-',tags[0])
    tail=line[match.end():]
    # Explicit "RTU - 1, 3" is shared equipment, not a numeric range.
    if prefix and re.fullmatch(r'\s*(?:,\s*\d+[A-Z]?)*\s*',tail):
        tags += [prefix[1]+'-'+n for n in re.findall(r',\s*(\d+[A-Z]?)',tail)]
    elif tail.strip():return []
    values={}
    patterns={
      'design_cfm':r'Airflow\s*\(CFM\)\s*-\s*CFM:\s*([\d,]+)',
      'esp':r'External Static Pressure[^\n]*?ESP:\s*([\d.]+)',
      'cooling_edb':r'System Entering Air[^\n]*?Dry Bulb:\s*([\d.]+)',
      'cooling_ewb':r'System Entering Air[^\n]*?Wet Bulb:\s*([\d.]+)',
      'cooling_ldb':r'System Leaving Air[^\n]*?Dry Bulb:\s*([\d.]+)',
      'cooling_lwb':r'System Leaving Air[^\n]*?Wet Bulb:\s*([\d.]+)',
      'heating_cfm':r'Heating Airflow[^\n]*?CFM:\s*([\d,]+)',
      'heating_edb':r'Air Dry Bulb[^\n]*?Entering Air:\s*([\d.]+)',
      'heating_ldb':r'Air Dry Bulb[^\n]*?Leaving Air:\s*([\d.]+)',
      'heating_input_btu':r'Gas Heating Values[^\n]*?Input:\s*([\d,]+)',
      'heating_output_btu':r'Gas Heating Values[^\n]*?Output:\s*([\d,]+)',
      'cooling_total_btu':r'Design Net Cooling Capacity[^\n]*?Total:\s*([\d,]+)',
      'cooling_sensible_btu':r'Design Net Cooling Capacity[^\n]*?Sensible:\s*([\d,]+)',
    }
    for field,pattern in patterns.items():
        m=re.search(pattern,text,re.I)
        if m:values[field]=float(m[1].replace(',',''))
    m=re.search(r'Model No:\s*([A-Z0-9][A-Z0-9-]+)',text,re.I)
    if m:values['model']=m[1]
    return [{'tag':tag,'values':values.copy(),'evidence':'Tagged performance summary; review submittal approval and revision.','basis':'TAGGED_PERFORMANCE'} for tag in dict.fromkeys(tags)]

def configure_air_form(ws, record):
    """Retain the standard form; use the ABP min/max panel when specified."""
    if record.get('osa_min_cfm') in (None,''):return False
    from copy import copy
    labels={18:'OSA AIRFLOW MAX (CFM)',19:'OSA AIRFLOW MIN (CFM)',20:'RETURN AIRFLOW (CFM)',
            21:'TOTAL S.P. (in w.c.)',22:'EXTERNAL S.P. (in w.c.)',23:'OSA DAMPER POS. MAX',
            24:'OSA DAMPER POS. MIN',25:'RETURN DAMPER POS. MAX',26:'RETURN DAMPER POS. MIN'}
    for row,label in labels.items():
        ws[f'A{row}']=label;ws[f'G{row}']=None;ws[f'J{row}']=None
        ws[f'A{row}'].alignment=copy(ws['A18'].alignment)
        ws[f'A{row}'].font=copy(ws['A18'].font)
    for row in (17,18,19,20):
        for col in ('G','J'):ws[f'{col}{row}'].number_format='#,##0'
    for row in (21,22):
        for col in ('G','J'):ws[f'{col}{row}'].number_format='0.00'
    ws['G20']='=IF(OR(G17="",G19=""),"",G17-G19)'
    ws['J20']='=IF(OR(J17="",J19=""),"",J17-J19)'
    ws['J21']='=IF(OR(W29="",Q29=""),"",W29-Q29)'
    ws['J22']='=IF(OR(W29="",A29=""),"",W29-A29)'
    for row in range(23,27):ws[f'G{row}']='--'
    return True

def populate_identity(ws, record, safe):
    for field,address in {'manufacturer':'G5','model':'G6','unit_type':'G9','service':'G10','equipment_location':'G12'}.items():
        if record.get(field):ws[address]=safe(record[field])

def populate_support(wb, records, selected, lookup, add, reset, sheet_name):
    verified=[r for r in records if r.get('status')=='VERIFIED' and r.get('template','Air Moving Equipment.xlsx')=='Air Moving Equipment.xlsx']
    coil='Coil DX GAS HT.xlsx'
    if coil in selected and verified:
        for start in range(0,len(verified),3):
            before=set(wb.sheetnames);add(wb,lookup[coil]);ws=wb[next(n for n in wb.sheetnames if n not in before)];reset(ws)
            ws.title=sheet_name(wb,'COIL DX GAS '+str(start//3+1))
            for col,rec in zip(('D','F','H'),verified[start:start+3]):
                ws[f'{col}4']=rec['tag']
                for field,row in COIL_FIELDS.items():
                    if rec.get(field) not in (None,''):ws[f'{col}{row}']=float(rec[field])
    traverse='Duct Traverse Rect..xlsx'
    if traverse in selected and verified:
        for rec in verified:
            before=set(wb.sheetnames);add(wb,lookup[traverse]);ws=wb[next(n for n in wb.sheetnames if n not in before)];reset(ws)
            ws.title=sheet_name(wb,rec['tag']+' OSA TRAVERSE')
            for off,field,label in [(0,'osa_cfm','OSA MAX'),(22,'osa_min_cfm','OSA MIN')]:
                ws[f'D{3+off}']=rec['tag'];ws[f'D{4+off}']=label
                if rec.get(field) not in (None,''):ws[f'L{3+off}']=float(rec[field])
    return bool(verified)

def group_report_pages(wb, records):
    """Group like ABP report pages without changing their forms or formulas."""
    from copy import copy, deepcopy
    from openpyxl.formula.translate import Translator
    from openpyxl.worksheet.pagebreak import Break
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image
    import io
    groups=[('AIR MOVING EQUIPMENT',[r['tag'] for r in records if r.get('status')=='VERIFIED' and r.get('template','Air Moving Equipment.xlsx')=='Air Moving Equipment.xlsx'],43),
            ('COIL DX GAS HT',[n for n in wb.sheetnames if n.startswith('COIL DX GAS ')],44),
            ('DUCT TRAVERSE RECT.',[n for n in wb.sheetnames if n.endswith('OSA TRAVERSE')],43)]
    for title,names,stride in groups:
        sources=[wb[n] for n in names if n in wb.sheetnames]
        if not sources:continue
        dst=sources[0];dst.title=title
        for i,src in enumerate(sources[1:],1):
            off=i*stride
            for row in src:
                for c in row:
                    target=dst.cell(c.row+off,c.column)
                    target.value=Translator(c.value,origin=c.coordinate).translate_formula(target.coordinate) if c.data_type=='f' else c.value
                    if c.has_style:target._style=copy(c._style)
            for r,dim in src.row_dimensions.items():dst.row_dimensions[r+off].height=dim.height
            for rng in src.merged_cells.ranges:
                dst.merge_cells(start_row=rng.min_row+off,end_row=rng.max_row+off,start_column=rng.min_col,end_column=rng.max_col)
            for pic in src._images:
                im=Image(io.BytesIO(pic._data()));im.anchor=deepcopy(pic.anchor)
                if hasattr(im.anchor,'_from'):im.anchor._from.row+=off
                if hasattr(im.anchor,'to'):im.anchor.to.row+=off
                dst.add_image(im)
            dst.row_breaks.append(Break(id=off));wb.remove(src)
        dst.print_area=f'A1:{get_column_letter(dst.max_column)}{len(sources)*stride-1}'
        dst.page_setup.fitToWidth=1;dst.page_setup.fitToHeight=0

def prepare_documentation(wb, project, location, selected):
    for ws in wb:
        ws.oddFooter.left.text='PRE-FIELD DRAFT - NOT CERTIFIED'
        if 'COVER' in ws.title.upper():
            ws['A12']=project;ws['A14']=location;ws['A15']=None
            # The template TOC describes an old completed job. Build an honest list.
            for row in range(52,71):
                for col in ('B','G'):ws[f'{col}{row}']=None
            for row,name in zip(range(52,71,2),[s.title for s in wb if s!=ws]):ws[f'B{row}']=name
    if 'Cover - Drew.xlsx' in selected:
        ws=wb.create_sheet('INSTRUMENT')
        ws.append(['INSTRUMENT CALIBRATION DATA & CERTIFICATES'])
        ws.append(['Instrument','Manufacturer','Model','Serial number','Calibration date'])
        for name in ('Micromanometer / Flowhood','Hot wire anemometer','Digital thermometer','Tachometer','Clamp meter'):ws.append([name])
        for col in 'ABCDE':ws.column_dimensions[col].width=26
        ws.oddFooter.left.text='PRE-FIELD DRAFT - ENTER CURRENT INSTRUMENTS'

def order_report(wb):
    order=('COVER','ABBREVIATIONS','PROJECT SUMMARY','AIR MOVING EQUIPMENT','COIL DX GAS HT','DUCT TRAVERSE RECT.','INSTRUMENT')
    def key(ws):
        title=ws.title.strip().upper()
        return order.index(title) if title in order else len(order)
    wb._sheets.sort(key=key)
    for ws in wb:
        if ws.title.strip().upper()=='COVER':
            for row in range(52,71):
                for col in ('B','G'):ws[f'{col}{row}']=None
            for row,name in zip(range(52,71,2),[s.title for s in wb if s!=ws and key(s)<len(order)]):ws[f'B{row}']=name
    wb.active=0
