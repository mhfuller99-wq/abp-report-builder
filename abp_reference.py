"""Build pre-field reports from a user-approved report, without retaining uploads."""
import io
import re
import zipfile
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.workbook.properties import CalcProperties

MAX_CELLS = 200_000
SUPPORTED = ('CHILLER', 'FAN COIL', 'EXHAUST FAN', 'EXHAUST GRILL', 'PUMP',
             'NOTES', 'PROJECT INFO', 'COVER', 'ABBREVIATION', 'PRE-TAB')


def open_reference(data):
    if not data or len(data) > 8_000_000:
        raise ValueError('Reference workbook must be an .xlsx smaller than 8 MB')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 50_000_000:
            raise ValueError('Reference workbook expands beyond 50 MB')
        if any('vbaProject' in x.filename for x in archive.infolist()):
            raise ValueError('Use a macro-free .xlsx reference')
    wb = load_workbook(io.BytesIO(data), keep_links=False)
    if sum(s.max_row * s.max_column for s in wb) > MAX_CELLS:
        raise ValueError('Reference workbook has too many cells')
    return wb


def family(ws):
    heading = ' '.join(str(ws.cell(r, c).value or '') for r in range(1, 4)
                       for c in range(1, min(ws.max_column, 3) + 1)).upper()
    return next((x for x in SUPPORTED if x in ws.title.upper() or x in heading), None)


def inventory(wb):
    units = []
    for ws in wb:
        for row in ws:
            label = next((c for c in row if str(c.value).strip().upper() == 'UNIT DESIGNATION'), None)
            if label:
                for c in row[label.column:]:
                    if c.value and c.data_type != 'f' and re.fullmatch(r'[A-Z]+[- ]\d+[A-Z]?', str(c.value).strip(), re.I):
                        units.append({'tag':str(c.value).strip(), 'sheet':ws.title, 'cell':c.coordinate})
    return units


def inspect_reference(data):
    wb = open_reference(data)
    try:
        populated = [s for s in wb if any(c.value is not None for row in s for c in row)]
        unsupported = [s.title for s in populated if family(s) is None]
        if unsupported:
            raise ValueError('Reference contains unsupported report layouts: ' + ', '.join(unsupported))
        units = inventory(wb)
        if not units:
            raise ValueError('No UNIT DESIGNATION entries found in the reference report')
        return {'sheets':[s.title for s in populated], 'units':units,
                'note':'Reference design values and equipment names are authoritative. Actual measurements, serial numbers and signoffs will be cleared. Drawings do not overwrite the reference.'}
    finally:
        wb.close()


def clear_value(cell):
    if not isinstance(cell, MergedCell) and cell.data_type != 'f' and cell.value != '--':
        cell.value = None


def reset_measurements(ws):
    """Respect each repeating Design/Actual block; retain calculation formulas."""
    kind = family(ws)
    headers = sorted({c.row for row in ws for c in row
                      if str(c.value).strip().upper() == 'ACTUAL'})
    for index, rownum in enumerate(headers):
        end = headers[index + 1] - 1 if index + 1 < len(headers) else ws.max_row
        # End at the next unit heading so grouped unit designations stay untouched.
        for row in ws.iter_rows(min_row=rownum + 1, max_row=end):
            if any(str(c.value).strip().upper() == 'UNIT DESIGNATION' for c in row):
                end = row[0].row - 2
                break
        actual_cols = [c.column for c in ws[rownum] if str(c.value).strip().upper() == 'ACTUAL']
        if kind == 'EXHAUST GRILL':
            actual_cols += [c.column for c in ws[rownum] if str(c.value).strip().upper() == 'INITIAL']
        for col in actual_cols:
            for row in ws.iter_rows(min_row=rownum + 1, max_row=end, min_col=col, max_col=col):
                c = row[0]
                # Grille headers continue onto the next row.
                if kind == 'EXHAUST GRILL' and c.row == rownum + 1:
                    continue
                if str(c.value or '').strip().upper() in ('--', 'TECHNICIAN:', 'TEST DATE:'):
                    continue
                if c.data_type == 'f' and re.fullmatch(r'=SUM\([A-Z]+\d+:[A-Z]+\d+\)',c.value):
                    inputs=c.value[5:-1]
                    c.value=f'=IF(COUNT({inputs})=0,"",SUM({inputs}))'
                clear_value(c)
    for row in ws:
        for c in row:
            label = str(c.value or '').strip().upper()
            if label.startswith(('SERIAL #', 'SERIAL NUMBER', 'TECHNICIAN:', 'TEST DATE:')):
                limit=ws.max_column
                if label.startswith('SERIAL'):
                    motor_labels=[x.column for cells in ws.iter_rows(min_row=1,max_row=3) for x in cells
                                  if str(x.value or '').strip().upper()=='MOTOR DATA']
                    if motor_labels:limit=min(motor_labels)-1
                for target in row[c.column:limit]:
                    if str(target.value or '').strip().upper() == 'TEST DATE:':
                        continue
                    clear_value(target)
    # Motor measurement panels have their own test-data heading rather than ACTUAL.
    if kind in ('PUMP', 'EXHAUST FAN'):
        motor_col = 8 if kind == 'PUMP' else 21
        for row in ws.iter_rows(min_row=17, max_row=27, min_col=motor_col, max_col=ws.max_column):
            for c in row:
                clear_value(c)
        # Full load amps must come from the field nameplate, not a historical test.
        for row in ws:
            for c in row:
                if str(c.value or '').strip().upper() == 'FULL LOAD AMPS':
                    for target in row[c.column:]:
                        clear_value(target)
    if kind == 'EXHAUST FAN':
        for address in ('B29','I29','Q29','X29'):
            clear_value(ws[address])
    if kind == 'NOTES':
        for row in ws.iter_rows(min_row=3, max_row=min(39, ws.max_row)):
            for c in row:
                clear_value(c)
    # Avoid showing a completed zero-flow test before any measurements exist.
    for row in ws:
        for c in row:
            if c.data_type != 'f':
                continue
            formula = c.value
            if re.fullmatch(r'=[A-Z]+\d+/[A-Z]+\d+', formula):
                numerator, denominator = formula[1:].split('/')
                c.value = f'=IF(OR({numerator}="",{denominator}="",{denominator}=0),"",{numerator}/{denominator})'
    if kind == 'PUMP':
        for target, a, b in [('D20','D18','D19'), ('D27','D25','D26')]:
            if ws[target].data_type == 'f':
                ws[target] = f'=IF(OR({a}="",{b}=""),"",{a}-{b})'
        if ws['H24'].data_type == 'f':
            ws['H24'] = '=IF(H18=1,IF(COUNT(I17,I20)<2,"",I17*I20*0.8*0.9/746),IF(H18=3,IF(COUNT(H17:J17,H20:J20)<6,"",AVERAGE(H17:J17)*AVERAGE(H20:J20)*0.8*0.9*1.732/746),""))'
    if kind == 'EXHAUST FAN':
        if ws['U19'].data_type == 'f':
            ws['U19'] = '=IF(OR(U5="",U6="",U18=""),"",IF(U18=3,IF(COUNT(U17,W17,Y17)<3,"",IF(AVERAGE(U17,W17,Y17)=0,"",U5*U6/AVERAGE(U17,W17,Y17))),IF(U18=1,IF(OR(W17="",W17=0),"",U5*U6/W17),"")))'
        if ws['U24'].data_type == 'f':
            ws['U24'] = '=IF(U18=1,IF(COUNT(W17,W20)<2,"",W17*W20*0.8*0.9/746),IF(U18=3,IF(COUNT(U17,W17,Y17,U20,W20,Y20)<6,"",AVERAGE(U17,W17,Y17)*AVERAGE(U20,W20,Y20)*0.8*0.9*1.732/746),""))'
        for target, a, b in [('K20','I29','Q29'), ('K21','B29','X29')]:
            if ws[target].data_type == 'f':
                ws[target] = f'=IF(OR({a}="",{b}=""),"",IF({a}<0,ABS({a}),-ABS({a}))+{b})'


def build_reference(data, project, location=''):
    info = inspect_reference(data)
    project = str(project).strip()
    if not project or len(project) > 180 or len(str(location)) > 180:
        raise ValueError('Enter a project name and location of at most 180 characters each')
    wb = open_reference(data)
    try:
        for ws in list(wb):
            if ws.title not in info['sheets']:
                wb.remove(ws)
                continue
            reset_measurements(ws)
            ws.oddFooter.left.text = 'PRE-FIELD DRAFT - NOT CERTIFIED'
            ws.oddFooter.right.text = 'Page &P of &N'
        # The report opens on the same equipment page as the approved reference.
        wb.active = 0
        wb.properties.title = project
        wb.properties.subject = str(location)
        wb.properties.description = 'Pre-field draft from user-approved reference design. Field measurements and signoffs cleared.'
        wb.calculation = CalcProperties(calcMode='auto', fullCalcOnLoad=True)
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()
    finally:
        wb.close()
