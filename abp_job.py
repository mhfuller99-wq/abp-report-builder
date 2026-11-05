"""Source-based equipment review and job-specific ABP form assembly."""
import re

NUMERIC_FIELDS = ('design_cfm','osa_cfm','osa_min_cfm','esp','total_sp','motor_hp','motor_volts','motor_fla','design_gpm',
                  'cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb',
                  'heating_cfm','heating_edb','heating_ldb','heating_input_btu','heating_output_btu',
                  'cooling_total_btu','cooling_sensible_btu')
TEXT_FIELDS = ('manufacturer','model','unit_type','service','equipment_location','area_served')
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

def populate_identity(ws, record, safe):
    # Manufacturer and model stay blank on a pre-field export. Nameplate identity
    # is reviewed in the app; the workbook is not a catalog cut sheet.
    for field,address in {'unit_type':'G9','service':'G10','area_served':'G11','equipment_location':'G12'}.items():
        if record.get(field) and ws[address].data_type!='f':ws[address]=safe(record[field])

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
                    if rec.get(field) not in (None,'') and ws[f'{col}{row}'].data_type!='f':ws[f'{col}{row}']=float(rec[field])
    traverse='Duct Traverse Rect..xlsx'
    if traverse in selected and verified:
        for rec in verified:
            before=set(wb.sheetnames);add(wb,lookup[traverse]);ws=wb[next(n for n in wb.sheetnames if n not in before)];reset(ws)
            for off,field,label in [(0,'osa_cfm','OSA MAX'),(22,'osa_min_cfm','OSA MIN')]:
                ws[f'D{3+off}']=rec['tag'];ws[f'D{4+off}']=label
                if rec.get(field) not in (None,''):ws[f'L{3+off}']=float(rec[field])
    return bool(verified)

def prepare_documentation(wb, project, location, selected):
    # Fill only existing project-input cells. Never rebuild the cover or TOC.
    for ws in wb:
        if 'COVER' in ws.title.upper():
            for address,value in [('A12',project),('A14',location)]:
                if ws[address].data_type!='f':ws[address]=value
