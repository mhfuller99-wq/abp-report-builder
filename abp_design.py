"""Read explicitly labeled design data without importing field measurements.

Rules follow recurring report structures. Historical job values are never used
as defaults for another job, and extracted candidates still require review.
"""
import re
from openpyxl.utils import get_column_letter
from abp_job import canonical_tag


def normalized(value):
    return re.sub(r'[^A-Z0-9]+',' ',str(value or '').upper()).strip()


def design_field(label, schedule=False):
    label=normalized(label)
    if any(word in label.split() for word in ('ACTUAL','MEASURED','INITIAL','FINAL','TEST')):
        return None
    aliases={
        'design_cfm':{'DESIGN CFM','SUPPLY CFM','SUPPLY AIR CFM','TOTAL CFM','TOTAL AIRFLOW CFM','COOLING CFM','DESIGN AIRFLOW'},
        'osa_min_cfm':{'OSA AIRFLOW MIN CFM','MINIMUM OUTSIDE AIR CFM','OA MIN CFM'},
        'osa_cfm':{'OSA AIRFLOW MAX CFM','MAXIMUM OUTSIDE AIR CFM','OA MAX CFM','OSA CFM','OA CFM','OUTSIDE AIR CFM','OUTDOOR AIR CFM','OSA AIRFLOW CFM'},
        'esp':{'ESP','ESP IN W C','EXTERNAL S P','EXTERNAL S P IN W C','EXTERNAL STATIC PRESSURE'},
        'motor_hp':{'MOTOR HP','DESIGN HP','HORSEPOWER'},
        'design_gpm':{'DESIGN GPM','WATER FLOW GPM','FLOW RATE GPM'},
    }
    for field,names in aliases.items():
        if label in names:return field
    if schedule and label in ('CFM','GPM'):
        return {'CFM':'design_cfm','GPM':'design_gpm'}[label]
    return None


def number(value):
    if isinstance(value,bool):return None
    text=str(value or '').strip().replace(',','') if value!=0 else '0'
    if not re.fullmatch(r'\d+(?:\.\d+)?',text):return None
    n=float(text)
    return n if 0<=n<=1_000_000 else None


def extract_design_rows(rows, sheet, tag_pattern):
    """Return cell-addressed candidates from row schedules and Design/Actual forms.

    rows are bounded, raw values with formulas excluded by the caller.
    A bare CFM/GPM heading is accepted only within a named schedule or beneath
    an explicit Design header. Actual/Initial/Final columns are never inputs.
    """
    results=[]
    def tag_at(value):
        value=canonical_tag(str(value or ''))
        return value if tag_pattern.fullmatch(value) else None
    def emit(tag,field,value,r,c,label):
        n=number(value)
        if n is not None:
            addr=f'{get_column_letter(c+1)}{r+1}'
            results.append({'tag':tag,'values':{field:n},'reference':f'{sheet}!{addr}',
                            'evidence':f'{label}: {n:g} (explicit design cell)','basis':'DESIGN_COLUMN'})
    def at(r,c):return rows[r][c] if 0<=r<len(rows) and 0<=c<len(rows[r]) else None
    # Standard row-oriented schedule: unit tag and design fields share a row.
    schedule='SCHEDULE' in normalized(sheet)
    for i,row in enumerate(rows):
        labels=[normalized(v) for v in row]
        tag_cols=[c for c,l in enumerate(labels) if l in ('MARK','TAG','UNIT','UNIT TAG','EQUIPMENT TAG','UNIT DESIGNATION')]
        fields={c:design_field(v,schedule) for c,v in enumerate(row)}
        fields={c:f for c,f in fields.items() if f}
        if len(tag_cols)!=1 or not fields:continue
        for r in range(i+1,min(i+501,len(rows))):
            tag=tag_at(at(r,tag_cols[0]))
            if not tag:
                if r>i+1:break
                continue
            for c,field in fields.items():emit(tag,field,at(r,c),r,c,row[c])
    # ABP report panels: tags on a unit row, DESIGN/ACTUAL below it.
    unit_rows=[i for i,row in enumerate(rows) if any(normalized(v) in ('UNIT DESIGNATION','COIL DESIGNATION') for v in row)]
    for idx,i in enumerate(unit_rows):
        end=unit_rows[idx+1] if idx+1<len(unit_rows) else min(i+45,len(rows))
        units=[(c,tag_at(v)) for c,v in enumerate(rows[i]) if tag_at(v)]
        for c,tag in units:
            header=next((r for r in range(i+1,min(i+19,end)) if normalized(at(r,c))=='DESIGN'),None)
            if header is not None:
                for r in range(header+1,end):
                    labels=[v for v in rows[r][:c] if v is not None and str(v).strip()]
                    if not labels:continue
                    field=design_field(labels[0],True)
                    if field:emit(tag,field,at(r,c),r,c,labels[0])
            elif len(units)==1:
                # Hood reports label their design cell directly instead of a column.
                for r in range(i+1,min(i+6,end)):
                    labels=[v for v in rows[r][:c] if v is not None]
                    if labels and normalized(labels[0])=='DESIGN CFM':
                        emit(tag,'design_cfm',at(r,c),r,c,labels[0])
    unique={ (r['tag'],r['reference'],next(iter(r['values']))):r for r in results }
    return list(unique.values())


# Actual cell maps from the supplied master workbooks. This is separate from
# recommendations: the reviewer explicitly chooses the unit's report form.
UNIT_FORMS={
    'Air Moving Equipment.xlsx':{'tag':'G3','design_cfm':'G17','osa_cfm':'G18','total_sp':'G20','esp':'G21','motor_hp':'T4','motor_volts':'T5','motor_fla':'T6','service':'G10','area_served':'G11','equipment_location':'G12','unit_type':'G9'},
    'Exhaust Fans _Std._.xlsx':{'tag':'H3','design_cfm':'H17','esp':'H21','motor_hp':'U4','motor_volts':'U5','motor_fla':'U6','service':'H10','area_served':'H11'},
    'Exhaust Fans _Sm._.xlsx':{'tag':'C3','design_cfm':'C10','esp':'C11'},
    'Fan Coil Units WTR.xlsx':{'tag':'C3','design_cfm':'C11','osa_cfm':'C12','area_served':'C4'},
    'Fan Coil Units DX.xlsx':{'tag':'C3','area_served':'C4','design_cfm':'C11','osa_cfm':'C12','cooling_edb':'C16','cooling_ewb':'C17','cooling_ldb':'C18','cooling_lwb':'C19','heating_edb':'C26','heating_ldb':'C27'},
    'Kitchen Hood.xlsx':{'tag':'D3','design_cfm':'D6'},
    'Chiller - Air Cooled.xlsx':{'tag':'C3','design_gpm':'C17'},
}
TEXT_CELLS={'service','area_served','equipment_location','unit_type'}


def inferred_form(tag):
    tag=str(tag or '').upper()
    if re.match(r'^(AHU|RTU|OAU|DOAS|MAU|AC)[- ]?\d',tag):return 'Air Moving Equipment.xlsx'
    if re.match(r'^(EF|KEF|TEF|CEF|SEF|RLF)[- ]?\d',tag):return 'Exhaust Fans _Std._.xlsx'
    if re.match(r'^(VRF|SSAU)[- ]?\d',tag):return 'Fan Coil Units DX.xlsx'
    if re.match(r'^KH[- ]?\d',tag):return 'Kitchen Hood.xlsx'
    return None


def unit_form(record):
    if 'template' in record:
        return record['template'] if record.get('template') in UNIT_FORMS else None
    return inferred_form(record.get('tag'))
