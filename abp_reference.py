"""Build pre-field reports from a user-approved report, without retaining uploads."""
import io
import re
import zipfile
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.workbook.properties import CalcProperties
from abp_fidelity import preserve_template_parts

MAX_CELLS = 200_000
SUPPORTED = ('AIR MOVING EQUIPMENT', 'MAU', 'COIL DX GAS', 'SUPPLY DIFFUSERS',
             'DUCT TRAVERSE RECT', 'KITCHEN HOOD', 'EXHAUST FANS SMALL',
             'PROJECT SUMMARY', 'INSTRUMENT', 'CHILLER', 'FAN COIL', 'EXHAUST FAN', 'EXHAUST GRILL', 'PUMP',
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
            label = next((c for c in row if str(c.value).strip().upper() in ('UNIT DESIGNATION', 'COIL DESIGNATION')), None)
            if label:
                for c in row[label.column:]:
                    if c.value and c.data_type != 'f' and re.fullmatch(r'(?:[A-Z]+[- ]\d+[A-Z]?|MAU)', str(c.value).strip(), re.I):
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


def reset_special_layout(ws):
    """Reset supported ABP forms with measurement panels outside ACTUAL columns.

    Coordinates are relative to repeated printed form headings, not job names.
    Design columns, equipment identity, geometry and static diagrams stay intact.
    """
    kind = family(ws)
    special = {'AIR MOVING EQUIPMENT', 'MAU', 'COIL DX GAS', 'SUPPLY DIFFUSERS',
               'DUCT TRAVERSE RECT', 'KITCHEN HOOD', 'EXHAUST FANS SMALL',
               'PROJECT SUMMARY', 'INSTRUMENT', 'COVER'}
    if kind not in special:
        return False

    def blank(address):
        for row in ws[address] if ':' in address else ((ws[address],),):
            for c in row:
                if isinstance(c, MergedCell):
                    continue
                if c.data_type != 'f':c.value = None

    if kind in ('AIR MOVING EQUIPMENT', 'MAU'):
        starts = [c.row-3 for row in ws for c in row
                  if str(c.value or '').strip().upper() == 'UNIT DESIGNATION']
        for off in starts:
            for address in (f'G{off+7}', f'J{off+17}:M{off+27}',
                            f'T{off+17}:Y{off+27}', f'A{off+29}', f'W{off+29}',
                            f'J{off+37}:M{off+40}', f'N{off+36}:Y{off+40}',
                            f'T{off+6}', f'T{off+8}:Y{off+13}'):
                blank(address)
            for cell in ws[off+29]:
                if isinstance(cell.value,(int,float)) or cell.data_type=='f':blank(cell.coordinate)
    elif kind == 'COIL DX GAS':
        for row in ws:
            for c in row:
                if str(c.value or '').strip().upper() == 'ACTUAL':
                    from openpyxl.utils import get_column_letter
                    col = get_column_letter(c.column)
                    blank(f'{col}{c.row+1}:{col}{c.row+22}')
        # Some copies retain calculation formulas in unused equipment slots.
        for row in ws:
            for c in row:
                if c.data_type == 'f':
                    blank(c.coordinate)
    elif kind == 'SUPPLY DIFFUSERS':
        starts = [c.row for row in ws for c in row if str(c.value or '').strip().upper() == 'INITIAL']
        for start in starts:
            blank(f'F{start+2}:F{start+30}')
            blank(f'H{start+2}:H{start+30}')
            for row in ws.iter_rows(min_row=start+2, max_row=start+30, min_col=9, max_col=9):
                if row[0].data_type == 'f':
                    blank(row[0].coordinate)
    elif kind == 'DUCT TRAVERSE RECT':
        # Every repeated traverse panel, not just the first one on the sheet.
        starts = [c.row-3 for row in ws for c in row
                  if str(c.value or '').strip().upper() == 'UNIT DESIGNATION']
        for off in starts or [0]:
            blank(f'B{off+10}:O{off+18}'); blank(f'D{off+7}')
            blank(f'N{off+3}:N{off+4}'); blank(f'D{off+6}')
            for col,row in [('L',4),('N',7)]:
                cell=ws[f'{col}{off+row}']
                if cell.data_type=='f':blank(cell.coordinate)
    elif kind == 'KITCHEN HOOD':
        blank('D11:M13'); blank('D7'); blank('K7')
        # Row 12 is the selected instrument's conversion factor, not design CFM.
    elif kind == 'EXHAUST FANS SMALL':
        for row in ws:
            for c in row:
                if str(c.value or '').strip().upper() == 'ACTUAL':
                    from openpyxl.utils import get_column_letter
                    col = get_column_letter(c.column)
                    blank(f'{col}{c.row+1}:{col}{c.row+3}')
    elif kind == 'PROJECT SUMMARY':
        blank(f'A5:{ws.cell(ws.max_row, ws.max_column).coordinate}')
    elif kind == 'INSTRUMENT':
        blank(f'B4:E{ws.max_row}')
        ws._images = []  # prior-job calibration certificates are not current evidence
        ws.print_area = 'A1:E12'
        from openpyxl.worksheet.pagebreak import RowBreak
        ws.row_breaks = RowBreak()
    elif kind == 'COVER':
        for row in ws:
            for c in row:
                text = str(c.value or '')
                if 'ANALYSIS REPORT' in text.upper() and 'CERTIFIED' in text.upper():
                    c.value = 'PRE-FIELD DRAFT\nTEST, ADJUST AND BALANCE\nREPORT'
                elif 'certif' in text.lower() and ('measurements' in text.lower() or 'nebb' in text.lower()):
                    c.value = 'Pre-field draft. Design information is retained from the approved reference. Field measurements, verification, and certification are pending.'
                elif text.strip().upper() == 'APPROVED BY:':
                    blank(f'A{c.row+1}:H{c.row+4}')
        blank('A5')
        blank('G52:G70')  # old page numbers include historical certificate pages
        # Keep header logos; remove approval/signature imagery below the header.
        ws._images = [im for im in ws._images if hasattr(im.anchor, '_from') and im.anchor._from.row < 18]

    # Signoffs and comments are historical evidence, not pre-field requirements.
    for row in ws:
        for c in row:
            label = str(c.value or '').strip().upper()
            if label in ('TECHNICIAN:', 'TEST DATE:'):
                for target in row[c.column:]:
                    if str(target.value or '').strip().upper() != 'TEST DATE:':
                        blank(target.coordinate)
            if label.rstrip(':') == 'COMMENTS' and kind not in ('AIR MOVING EQUIPMENT', 'MAU'):
                for r in range(c.row+1, min(c.row+6, ws.max_row+1)):
                    for target in ws[r]:
                        blank(target.coordinate)
    return True


def _reset_measurements_legacy(ws):
    """Respect each repeating Design/Actual block; retain calculation formulas."""
    if reset_special_layout(ws):
        return
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
def reset_measurements(ws):
    """Clear literal field inputs, preserving every original formula and format.

    No formula guards, translations, replacements or number-format changes.
    Calculated zero/error displays are the original template's behavior.
    """
    from copy import deepcopy
    formulas={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}
    print_area=ws.print_area
    row_breaks=deepcopy(ws.row_breaks)
    images=list(ws._images)
    kind=family(ws)
    if kind=='COVER':
        # Keep template labels/certification text and artwork unchanged.
        for addr in ('A5','B39'):
            if ws[addr].data_type!='f':clear_value(ws[addr])
    else:
        _reset_measurements_legacy(ws)
    for address,value in formulas.items():ws[address]=value
    ws.print_area=print_area;ws.row_breaks=row_breaks;ws._images=images


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
        # The report opens on the same equipment page as the approved reference.
        wb.active = 0
        wb.properties.title = project
        wb.properties.subject = str(location)
        wb.properties.description = 'Pre-field draft from user-approved reference design. Field measurements and signoffs cleared.'
        wb.calculation = CalcProperties(calcMode='auto', fullCalcOnLoad=True)
        out = io.BytesIO()
        wb.save(out)
        return preserve_template_parts(out.getvalue(),{ws.title:(data,ws.title) for ws in wb})
    finally:
        wb.close()
