"""Read mechanical schedule rows, plan outlets, and submittal nameplates.

Words are grouped into visual rows. A tag is accepted only when it leads a
schedule row or an explicit mark, so a distant column cannot glue "B" to "6"
or a model fragment into an equipment tag. Design targets and manufacturer selected performance remain separate;
conflicting values require review. Supply-outlet airflow is read
only from a plan callout (type mark, neck, and CFM). A unit total is never
copied onto an outlet. Fan RPM is never stored as motor RPM, and unit MCA is
never stored as motor FLA.
"""
import re
from abp_mechanical import schedule_candidates, diffuser_legend, keyed_outlets, packaged_submittals, TAG, expand_marks, page_words, selection_airflows, readable_text
from abp_outlets import centered_outlets, necked_outlets, distinct_outlets, sized_registers

LEAD = re.compile(
    r'^(' + TAG.split('(?:', 1)[1].split(')', 1)[0] + r')-\d+(?:\.\d+)*[A-Z]?(?:-\d+(?:\.\d+)*[A-Z]?)?\b', re.I)
MAPPED = re.compile(r'^(?:EF|VRF|DOAS|SSAU)-\d+[A-Z]?$', re.I)
VOLT = re.compile(r'\b(\d{2,3}(?:-\d{2,3})?)/(\d+)/(\d)\b')
UNIT_TOTALS = {
    'design_cfm', 'osa_cfm', 'esp', 'total_sp', 'motor_hp', 'motor_fla', 'motor_volts',
    'cooling_edb', 'cooling_ewb', 'cooling_ldb', 'cooling_lwb',
    'heating_edb', 'heating_ldb', 'heating_cfm',
    'electric_heating_edb', 'electric_heating_ldb',
    'heating_input_btu', 'heating_output_btu',
    'cooling_total_btu', 'cooling_sensible_btu',
    'heater_volts', 'heater_phase', 'heater_amps', 'heater_stages', 'heating_ewt', 'heating_lwt', 'water_dp_ft', 'design_gpm',
}
# Kept on the candidate so a reviewer can see them. They are not form inputs:
# fan RPM is not motor RPM, watts are not horsepower, unit MCA is not motor FLA.
EVIDENCE_ONLY = {'fan_rpm', 'motor_watts', 'unit_mca', 'unit_mop', 'brake_hp', 'selected_cfm', 'heater_kw'}


def is_submittal(basis):
    return str(basis or '').startswith('SUBMITTAL') or basis == 'TAGGED_PERFORMANCE'


def segments(words, ytol=2.6, gap=80):
    rows = []
    for word in sorted(words, key=lambda item: (item[1], item[0])):
        if not rows or abs(word[1] - rows[-1][0]) > ytol:
            rows.append([word[1], [word]])
        else:
            rows[-1][1].append(word)
    found = []
    for y, row in rows:
        row.sort(key=lambda item: item[0])
        current = [row[0]]
        for word in row[1:]:
            if word[0] - current[-1][2] > gap:
                found.append((y, current))
                current = [word]
            else:
                current.append(word)
        found.append((y, current))
    return found


def text_of(words):
    return ' '.join(word[4] for word in words)


def number(token):
    token = str(token).replace(',', '').strip()
    if not re.fullmatch(r'\d+(?:\.\d+)?', token):
        return None
    value = float(token)
    return value if 0 <= value <= 1_000_000 else None


def horsepower(token):
    token = str(token).strip().upper().rstrip('.')
    if token in {'N/A', 'NA', '-', '--'}:
        return None
    if token.endswith('W') and number(token[:-1]) is not None:
        return None
    if re.fullmatch(r'\d+/\d+', token):
        num, den = token.split('/')
        den_f = float(den)
        return float(num) / den_f if den_f else None
    return number(token)


def watts(token):
    token = str(token).strip().upper()
    if token.endswith('W') and number(token[:-1]) is not None:
        return number(token[:-1])
    return None


def single_voltage(token):
    match = VOLT.search(str(token))
    if not match or '-' in match.group(1):
        return None
    return number(match.group(1))


def candidate(tag, values, reference, evidence, basis, text=None):
    values = {key: value for key, value in values.items() if value is not None}
    item = {'tag': tag.upper(), 'values': values, 'reference': reference,
            'evidence': evidence[:240], 'basis': basis}
    if text:
        item['text'] = {key: value for key, value in text.items() if value}
    return item


def parse_vrf(line, reference):
    match = re.match(
        r'(VRF-\d+[A-Z]?)\s+(.+?)\s+CARRIER\s+\(NO(?:\s+EXCEPTIONS\))?\s+'
        r'((?:MMU|MMK)-[A-Z0-9-]+)\s+(\d+)\s+(\d+)\s+'
        r'(\d+\.?\d*)/(\d+\.?\d*)\s+(\d+)\s+(\d+)\s+'
        r'(\d+\.?\d*)\s+(\d+\.?\d*)\s+(\d+)\s+'
        r'(\d{3}-\d{3}/\d+/\d)\s+([\d.]+)\s*/\s*(\d+)',
        line, re.I)
    if not match:
        return None
    area = re.sub(r'\s+', ' ', match.group(2)).strip(' ,/')
    values = {
        'design_cfm': number(match.group(4)),
        'motor_watts': number(match.group(5)),
        'cooling_edb': number(match.group(6)),
        'cooling_ewb': number(match.group(7)),
        'cooling_sensible_btu': number(match.group(8)),
        'cooling_total_btu': number(match.group(9)),
        'heating_edb': number(match.group(10)),
        'heating_ldb': number(match.group(11)),
        'heating_output_btu': number(match.group(12)),
        'unit_mca': number(match.group(14)),
        'unit_mop': number(match.group(15)),
    }
    evidence = (f'{match.group(1)} {area}; {match.group(13)}; '
                f'MCA/MOCP {match.group(14)}/{match.group(15)}; motor {match.group(5)} W')
    return candidate(match.group(1), values, reference, evidence, 'PLAN_SCHEDULE',
                     {'area_served': area})


def parse_ef(line, reference):
    match = re.match(
        r'(EF-\d+)\s+(.+?)\s+GREENHECK\s+(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\S+)\s+(\S+)',
        line, re.I)
    if not match:
        return None
    volts = VOLT.search(line)
    motor = match.group(8)
    values = {
        'design_cfm': number(match.group(4)),
        'fan_rpm': number(match.group(5)),
        'esp': number(match.group(6)),
        'brake_hp': number(match.group(7)) if horsepower(match.group(7)) else None,
        'motor_hp': horsepower(motor),
        'motor_watts': watts(motor),
        'motor_volts': single_voltage(volts.group(0)) if volts else None,
    }
    service = re.sub(r'\s+', ' ', match.group(2)).strip(' ,/')
    evidence = (f'{match.group(1)} {service}; fan {match.group(5)} RPM; '
                f'motor power {motor}; {volts.group(0) if volts else "voltage unlabeled"}')
    return candidate(match.group(1), values, reference, evidence, 'PLAN_SCHEDULE',
                     {'service': service})


def parse_doas(line, reference):
    match = re.search(
        r'DOAS-(\d+)\s+CARRIER\s+\(NO(?:\s+EXCEPTIONS\))?\s+\S+\s+'
        r'\d+\s+\(\d+\s+TONS\)\s+\S+\s+\S+\s+\S+\s+\d+\s+'
        r'([\d.]+)\s+(\d+)\s+([\d.]+)/\s*([\d.]+)\s+([\d.]+)/([\d.]+)\s+'
        r'([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+'
        r'(\d{3}/\d+/\d)\s+(\d+)\s*/\s*(\d+)',
        line, re.I)
    if not match:
        return None
    tag = 'DOAS-' + match.group(1)
    values = {
        'esp': number(match.group(2)),
        'design_cfm': number(match.group(3)),
        'cooling_edb': number(match.group(4)),
        'cooling_ewb': number(match.group(5)),
        'cooling_ldb': number(match.group(6)),
        'cooling_lwb': number(match.group(7)),
        'heating_edb': number(match.group(8)),
        'heating_ldb': number(match.group(9)),
        'heating_input_btu': (number(match.group(10)) or 0) * 1000,
        'heating_output_btu': (number(match.group(11)) or 0) * 1000,
        'motor_volts': single_voltage(match.group(13)),
        'unit_mca': number(match.group(14)),
        'unit_mop': number(match.group(15)),
    }
    if values['heating_input_btu'] == 0:
        values['heating_input_btu'] = None
    if values['heating_output_btu'] == 0:
        values['heating_output_btu'] = None
    evidence = (f'{tag} plan schedule; {match.group(13)}; '
                f'MCA/MOCP {match.group(14)}/{match.group(15)}')
    return candidate(tag, values, reference, evidence, 'PLAN_SCHEDULE',
                     {'service': 'DEDICATED OUTSIDE AIR', 'unit_type': 'DOAS'})


def parse_ssau(line, reference):
    match = re.match(
        r'(SSAU-\d+)\s+(.+?)\s+(40MB[A-Z0-9-]+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+'
        r'R410A\s+([\d.]+)/([\d.]+)\s+([\d.]+)(?:/([\d.]+))?\s+(\d+)\s+(\d+)\s+'
        r'([\d.]+)\s+([\d.]+)\s+(\d+)',
        line, re.I)
    if not match:
        return None
    area = re.sub(r'\s*CARRIER.*$', '', match.group(2), flags=re.I)
    area = re.sub(r'\s+', ' ', area).strip(' ,/')
    values = {
        'design_cfm': number(match.group(4)),
        'osa_cfm': number(match.group(5)),
        'esp': number(match.group(6)),
        'cooling_edb': number(match.group(7)),
        'cooling_ewb': number(match.group(8)),
        'cooling_ldb': number(match.group(9)),
        'cooling_lwb': number(match.group(10)) if match.group(10) else None,
        'cooling_sensible_btu': number(match.group(11)),
        'cooling_total_btu': number(match.group(12)),
        'heating_edb': number(match.group(13)),
        'heating_ldb': number(match.group(14)),
        'heating_output_btu': number(match.group(15)),
    }
    evidence = f'{match.group(1)} {area}; model kept as evidence only'
    return candidate(match.group(1), values, reference, evidence, 'PLAN_SCHEDULE',
                     {'area_served': area})


PARSERS = {'VRF': parse_vrf, 'EF': parse_ef, 'DOAS': parse_doas, 'SSAU': parse_ssau}


def wrapped_words(index, rows):
    y, words = rows[index]
    left = words[0][0]
    extra = []
    for y2, words2 in rows[index + 1:index + 6]:
        if y2 - y > 18:
            break
        if y2 <= y:
            continue
        for word in words2:
            if word[4].upper() in {'OFFICE', 'BREAK', 'ROOM'} and left - 10 <= word[0] <= left + 260:
                extra.append(word[4])
    return extra


def parse_page(words, page_number, name):
    reference = f'page {page_number}'
    found = schedule_candidates(words, page_number, name)
    scheduled = {item['tag'] for item in found}
    # A complete printed plan mark remains a review item even when it is not
    # the first word of a visual row. It supplies no inferred design values.
    for word in words:
        tag=word[4].upper()
        if re.fullmatch(r'(?:RTU|AHU|KEF|BCU)-\d+(?:[.-]\d+)*[A-Z]?',tag) and tag not in scheduled:
            found.append({'tag':tag,'values':{},'text':{},'source':name,'reference':reference,
                          'basis':'PLAN_TAG','evidence':'Printed equipment mark only; confirm scheduled scope, revision and design data'})
            scheduled.add(tag)
    rows = segments(words)
    for index, (_y, words_in_row) in enumerate(rows):
        line = text_of(words_in_row)
        extra = wrapped_words(index, rows)
        if extra and 'GREENHECK' in line:
            line = line.replace(' GREENHECK', ' ' + ' '.join(extra) + ' GREENHECK', 1)
        elif extra and line.upper().startswith('SSAU-'):
            line = re.sub(r'^(SSAU-\d+\s+\S+)', lambda match: match.group(1) + ' ' + ' '.join(extra), line, count=1)
        gas = re.match(r'(DOAS-\d+)\s+DEDICATED OUTSIDE AIR SYSTEM\s+([A-Z][A-Z ]+?)\s+\d+\s*$', line, re.I)
        if gas:
            item = candidate(gas.group(1).upper(), {}, reference, line, 'PLAN_SCHEDULE', {
                'service': 'DEDICATED OUTSIDE AIR',
                'equipment_location': re.sub(r'\s+', ' ', gas.group(2)).strip(),
            })
            item['source'] = name
            found.append(item)
            continue
        lead = LEAD.match(line)
        if not lead:
            continue
        if re.search(r'\bTHRU\b', line, re.I) and lead.group(1).upper() == 'FS':
            continue
        tag = lead.group(0).upper()
        if tag in scheduled:
            continue
        family = lead.group(1).upper()
        if any(w[4].upper() in {'ACTUAL', 'MEASURED', 'INITIAL', 'FINAL'}
               and 0 < words_in_row[0][1] - w[1] < 100 for w in words):
            continue
        # New packaged/split families require schedule or explicit submittal
        # evidence. A plan tag touching a keyed note can read as PAHU-12.
        if family in {'PAHU', 'MSAH', 'MSHP'}:
            continue
        parser = PARSERS.get(family)
        item = parser(line, reference) if parser else None
        if item is None:
            item = candidate(tag, {}, reference, line[:240], 'PLAN_SCHEDULE')
            item['unmapped'] = True
        elif family not in {'VRF', 'EF', 'DOAS', 'SSAU'}:
            item['unmapped'] = True
        item['source'] = name
        found.append(item)
    return found


def _page_segments(page):
    return segments(page_words(page))


def parse_doas_submittal(doc, name):
    found = []
    for page in doc:
        text = readable_text(page)
        marks = set(m.upper() for m in re.findall(r'\bDOAS-\d+(?:\.\d+)*[A-Z]?\b', text, re.I))
        marks.update('DOAS-'+n for n in re.findall(r'\bDOAS\s*\(#(\d+)\)', text, re.I))
        if len(marks) != 1:
            continue
        tag = next(iter(marks))
        if not (re.search(r'(?:Unit (?:Mark|Tag)|Mark|Tag)\s*:\s*'+re.escape(tag)+r'\b', text, re.I)
                or re.search(r'^\s*'+re.escape(tag)+r'\s*$', text, re.I | re.M)
                or re.search(r'\bDOAS\s*\(#\d+\)', text, re.I)):
            continue
        if len(set(re.findall(r'Supply Air:\s*([\d,]+)\s*CFM', text, re.I))) > 1:
            continue
        found.extend(_parse_doas_selection_page(page, name, tag))
    return found


def _parse_doas_selection_page(page, name, tag):
    blob = [(y, text_of(words), page.number + 1) for y, words in _page_segments(page)]
    joined = '\n'.join(text for _y, text, _page in blob)
    table_values = selection_airflows(page_words(page))
    if 'DOAS' not in joined.upper() or not (table_values or re.search(r'Supply Air:\s*[\d,]+', joined, re.I)):
        return []
    values = table_values
    text = {}
    if re.search(r'\bIndirect Gas\b', joined, re.I):
        text['unit_type'] = 'DOAS / INDIRECT GAS'

    def grab(pattern, field, scale=1, page_hint=None):
        match = re.search(pattern, joined, re.I)
        if not match:
            return
        raw = match.group(1).replace(',', '')
        parsed = number(raw)
        if parsed is None:
            return
        values[field] = parsed * scale

    grab(r'Supply Air:\s*([\d,]+)\s*CFM', 'design_cfm')
    grab(r'Outdoor Air:\s*([\d,]+)\s*CFM', 'osa_cfm')
    grab(r'([\d.]+)\s*HP,\s*\d\s*Phs', 'motor_hp')
    grab(r'([\d.]+)\s*FLA', 'motor_fla')
    esp = re.search(r'\(([\d.]+)"\s*Ductwork Discharge ESP', joined, re.I)
    if esp:
        values['esp'] = number(esp.group(1))
    total = re.search(r'SP:\s*([\d.]+)"\s*w\.g\.', joined, re.I)
    if total:
        values['total_sp'] = number(total.group(1))
    volts = re.search(r'(\d{3})\s*V,\s*60\s*Hz,\s*[\d.]+\s*FLA', joined, re.I)
    if volts:
        values['motor_volts'] = number(volts.group(1))
    grab(r'Output BTU:\s*([\d,]+)', 'heating_output_btu')
    grab(r'Input BTU:\s*([\d,]+)', 'heating_input_btu')
    winter = re.search(r'Winter Outdoor Air Dry Bulb Temp:\s*([\d.]+)', joined, re.I)
    rise = re.search(r'(?<!Max )Temp Rise:\s*([\d.]+)', joined, re.I)
    discharges = re.findall(r'Discharge Dry Bulb Temp:\s*([\d.]+)', joined, re.I)
    if winter and rise and discharges:
        entering = number(winter.group(1))
        delta = number(rise.group(1))
        leaving = number(discharges[0])
        if None not in (entering, delta, leaving) and abs((entering + delta) - leaving) <= 1.5:
            values['heating_edb'] = entering
            values['heating_ldb'] = leaving
    cool_db = re.search(r'(?<!Winter )Outdoor Air Dry Bulb Temp:\s*([\d.]+)', joined, re.I)
    cool_wb = re.search(r'Outdoor Air Wet Bulb Temp:\s*([\d.]+)', joined, re.I)
    # The first unlabeled "Leaving" pair is the cooling coil. Reheat leaving is named.
    leave_db = re.search(r'(?<!Reheat Coil )Leaving Dry Bulb Temp:\s*([\d.]+)', joined, re.I)
    leave_wb = re.search(r'(?<!Reheat Coil )Leaving Wet Bulb Temp:\s*([\d.]+)', joined, re.I)
    if cool_db:
        values['cooling_edb'] = number(cool_db.group(1))
    if cool_wb:
        values['cooling_ewb'] = number(cool_wb.group(1))
    if leave_db:
        values['cooling_ldb'] = number(leave_db.group(1))
    if leave_wb:
        values['cooling_lwb'] = number(leave_wb.group(1))
    grab(r'Total Capacity:\s*([\d.]+)\s*MBH', 'cooling_total_btu', 1000)
    grab(r'Sensible Capacity:\s*([\d.]+)\s*MBH', 'cooling_sensible_btu', 1000)
    mca = re.search(r'([\d.]+)\s*Amps\s*MCA', joined, re.I)
    mop = re.search(r'(\d+)\s*Amps\s*MOP', joined, re.I)
    if mca:
        values['unit_mca'] = number(mca.group(1))
    if mop:
        values['unit_mop'] = number(mop.group(1))
    rpm = re.search(r'RPM:\s*(\d+)', joined, re.I)
    if rpm:
        values['fan_rpm'] = number(rpm.group(1))
    bhp = re.search(r'BHP:\s*([\d.]+)', joined, re.I)
    if bhp:
        values['brake_hp'] = number(bhp.group(1))
    if values.get('design_cfm') and values.get('osa_cfm') == values['design_cfm']:
        text['service'] = 'DEDICATED OUTSIDE AIR'
    grab(r'Heating Air(?:flow)?:\s*([\d,]+)\s*CFM', 'heating_cfm')
    evidence = (f'{tag} submittal nameplate; motor FLA {values.get("motor_fla")}; '
                f'unit MCA {values.get("unit_mca")}; fan RPM {values.get("fan_rpm")}')
    if not values.get('design_cfm'):
        return []
    return [candidate(tag, values, f'page {page.number + 1}', evidence, 'SUBMITTAL_NAMEPLATE', text)]


def fan_motor_fla_rows(rows):
    """Read a scalar FLA only from an evidenced fan/motor data table.

    A flattened page can put a starter dial tick immediately after ``FLA (A)``.
    Require both the complete scalar row and its local table structure. NEC
    reference ratings, ranges and control illustrations do not qualify. Keep
    the actual words so the reviewer can inspect the value's provenance.
    """
    scalar = re.compile(r'^\*?\s*(?:Motor\s+)?FLA\s*\*?\s*\((?:A|Amps)\)\s+(\d+(?:\.\d+)?)$', re.I)
    heading = re.compile(r'^(?:Performance|Motor(?:\s+(?:Data|Information|Details|Specifications))?)$', re.I)
    support = re.compile(
        r'^((?:Requested|Actual) Volume \(CFM\)|Fan RPM|Motor RPM|RPM|'
        r'Total External SP \([^)]*\)|Input Watts \(W\)|Voltage/Cycle/Phase|'
        r'Voltage|Volts|Size \(HP\)|Horsepower|Motor HP|HP|Motor Mounted)\s+\S+$', re.I)
    scalar_rows, header_rows, support_rows = [], [], []
    for y, row in rows:
        text = text_of(row)
        matched = scalar.fullmatch(text)
        if matched:
            scalar_rows.append((y, row, matched))
        if heading.fullmatch(text):
            header_rows.append((y, row))
        matched = support.fullmatch(text)
        if matched:
            support_rows.append((y, row, matched))
        # Bound relational work on pathological pages, withholding FLA rather
        # than accepting a truncated, potentially ambiguous group of ratings.
        if len(scalar_rows) > 64 or len(header_rows) > 128 or len(support_rows) > 512:
            return None, []
    candidates = []
    for y, row, match in scalar_rows:
        if len(row) < 2 or number(row[-1][4]) is None:
            continue
        label, value_word = row[:-1], row[-1]
        height = max(1.0, min(20.0, value_word[3] - value_word[1]))
        label_right = max(w[2] for w in label)
        value_center = (value_word[0] + value_word[2]) / 2
        if value_word[0] < label_right:
            continue
        headers = [(hy, hw) for hy, hw in header_rows if 0 < y - hy <= 18 * height
                   and min(w[0] for w in row) - 2 * height <= (hw[0][0] + hw[-1][2]) / 2 <= value_word[2] + 2 * height]
        if not headers:
            continue
        hy, header = max(headers, key=lambda item: item[0])
        witnesses = {}
        for sy, other, supported in support_rows:
            if len(other) < 2 or not hy < sy or abs(sy - y) > 12 * height:
                continue
            other_right = max(w[2] for w in other[:-1])
            other_center = (other[-1][0] + other[-1][2]) / 2
            if abs(other_right - label_right) <= 1.5 * height and abs(other_center - value_center) <= 2 * height:
                witnesses.setdefault(supported.group(1).upper(), other)
        if len(witnesses) < 2:
            continue
        candidates.append((number(match.group(1)), list(row) + list(header) +
                           [w for words in witnesses.values() for w in words]))
    # Two different motor ratings on the same marked page cannot be assigned
    # safely by proximity alone. Leave the value for manual review.
    if not candidates or len({value for value, _words in candidates}) != 1:
        return None, []
    return candidates[0]


def parse_fan_submittal(doc, name):
    found = []
    for page in doc:
        spatial_rows = _page_segments(page)
        rows = [text_of(words) for _y, words in spatial_rows]
        page_text = '\n'.join(rows)
        # Manufacturer selections may print explicit Tags at the top and an
        # unrelated internal Mark at the bottom. Read only complete EF lists;
        # never translate a manufacturer mark into a project equipment ID.
        lists=[]
        for line in rows:
            match=re.fullmatch(r'(?:Unit )?(?:Mark|Tags?):\s*(EF-\d+.*)',line,re.I)
            if not match:continue
            printed=re.sub(r'(?<=\d)\s+(?=EF-)',', ',match.group(1),flags=re.I)
            parsed=expand_marks(printed)
            if not parsed or any(not re.fullmatch(r'EF-\d+',tag,re.I) for tag in parsed):
                lists.append(None)
            else:lists.append(parsed)
        if not lists or any(tags is None for tags in lists) or len({tuple(sorted(tags)) for tags in lists if tags})!=1:
            continue
        tags=lists[0]
        tag = ', '.join(tags)
        values = {}

        def grab(pattern, field):
            match = re.search(pattern, page_text, re.I)
            if match:
                values[field] = number(match.group(1).replace(',', ''))

        grab(r'Requested Volume \(CFM\)\s*([\d,]+)', 'design_cfm')
        grab(r'Actual Volume \(CFM\)\s*([\d,]+)', 'selected_cfm')
        grab(r'Fan RPM\s*(\d+)', 'fan_rpm')
        motor_fla, fla_words = fan_motor_fla_rows(spatial_rows)
        if motor_fla is not None:
            values['motor_fla'] = motor_fla
        grab(r'Total External SP[^\n]*?\s(\d*\.\d+)', 'esp')
        grab(r'Input Watts \(W\)\s*(\d+)', 'motor_watts')
        volts = VOLT.search(page_text)
        if volts:
            values['motor_volts'] = single_voltage(volts.group(0))
        evidence = (f'{tag} fan submittal; fan RPM {values.get("fan_rpm")}; '
                    f'motor FLA {values.get("motor_fla")}; {values.get("motor_watts")} W')
        service = 'CEILING' if 'Ceiling Exhaust Fan' in page_text else 'INLINE' if 'Inline Fan' in page_text else ''
        for tag in tags:
            item = candidate(tag, values.copy(), f'page {page.number + 1}', evidence, 'SUBMITTAL_NAMEPLATE', {'service': service} if service else {})
            if fla_words:
                item['value_words'] = {'motor_fla': fla_words}
            found.append(item)
    return found


MARK = re.compile(r'^[A-Z]:$')
NECK = re.compile(r'^(\d+(?:\.\d+)?)"(?:([Øø])|([xX])(\d+(?:\.\d+)?)")$')
SUPPLY_UNIT = re.compile(r'^(DOAS|AHU|RTU|MAU|OAU|SSAU)$', re.I)
LEGEND_ROW = re.compile(r'\b(?:SCHEDULE|LAY-IN|MANUFACTURER|ACCESSORIES|MFR)\b', re.I)


def _center(word):
    return ((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)


def _distance(a, b):
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _nearest(word, marks, limit):
    best = None
    best_d = limit
    for mark in marks:
        dist = _distance(word, mark)
        if dist < best_d:
            best, best_d = mark, dist
    return best


def _sheet_area(words):
    for word in words:
        if word[4].upper() != 'AREA':
            continue
        previous = [other for other in words
                    if other[2] <= word[0] + 2 and abs(other[1] - word[1]) < 6 and word[0] - other[2] < 40]
        nxt = [other for other in words
               if other[0] >= word[2] - 2 and abs(other[1] - word[1]) < 6 and other[0] - word[2] < 16
               and re.fullmatch(r'[A-Z]', other[4])]
        if nxt and any('PLAN' in item[4].upper() or item[4] in {'-', '–'} for item in previous):
            return 'AREA ' + nxt[0][4].upper()
    return ''


ROOM_NOISE = {'VRF', 'EF', 'DOAS', 'SSAU', 'AHU', 'RTU', 'CFM', 'TA', 'VD', 'SA', 'RA', 'OA', 'EA'}


def _callout_number(word, words):
    """True when this integer is an airflow callout or sits under a neck, not a room tag."""
    for other in words:
        if other[4].upper() == 'CFM' and _distance(word, other) < 36:
            return True
        if NECK.fullmatch(other[4]):
            dx = _center(word)[0] - _center(other)[0]
            dy = _center(word)[1] - _center(other)[1]
            if abs(dx) < 18 and 4 <= dy <= 28:
                return True
    return False


def _room_labels(words):
    rooms = []
    for word in words:
        if not re.fullmatch(r'\d{3}', word[4]) or _callout_number(word, words):
            continue
        above = [other for other in words
                 if other[4].isalpha() and len(other[4]) >= 3 and other[4].upper() not in ROOM_NOISE
                 and -32 <= (other[1] - word[1]) <= -6 and abs(other[0] - word[0]) < 70]
        if not above:
            continue
        line = max(other[1] for other in above)
        name = ' '.join(other[4] for other in sorted(above, key=lambda item: item[0]) if abs(other[1] - line) < 4)
        if name:
            rooms.append((word, f'{name} {word[4]}'))
    return rooms


def _page_supply_tags(words):
    """Unit tags printed on this sheet. One tag can explain the plan's supply outlets."""
    tags = set()
    for word in words:
        token = word[4].upper().replace(' ', '')
        hyphen = re.fullmatch(r'(DOAS|AHU|RTU|MAU|OAU|SSAU)-(\d+[A-Z]?)', token)
        if hyphen:
            tags.add(f'{hyphen.group(1)}-{hyphen.group(2)}')
            continue
        if not SUPPLY_UNIT.fullmatch(token):
            continue
        for other in words:
            if not re.fullmatch(r'\d+[A-Z]?', other[4]):
                continue
            if abs(other[0] - word[0]) < 40 and abs(other[1] - word[1]) < 18:
                tags.add(f'{token}-{other[4].upper()}')
    return tags


def parse_supply_outlets(words, page_number, name):
    """Individual type-A plan symbols. Legends, details, and return marks stay out.

    Design CFM is the integer printed with the word CFM at that symbol. A bare
    integer under a neck is kept in the evidence and is not treated as airflow.
    """
    marks = [word for word in words if MARK.fullmatch(word[4])]
    if not marks:
        return []
    area = _sheet_area(words)
    rooms = _room_labels(words)
    tags = _page_supply_tags(words)
    # A type-A grille can serve exhaust as well as supply. A unit elsewhere on
    # the page does not establish a duct connection; require explicit review.
    system = ''
    outlets = []
    for mark in marks:
        if mark[4].upper() != 'A:':
            continue
        neighbors = ' '.join(word[4] for word in words
                             if abs(word[1] - mark[1]) < 5 and abs(word[0] - mark[0]) < 280)
        if LEGEND_ROW.search(neighbors):
            continue
        size = None
        size_dist = 36
        for word in words:
            if not NECK.fullmatch(word[4]):
                continue
            dist = _distance(mark, word)
            if dist < size_dist and _nearest(word, marks, 42) is mark:
                size, size_dist = word, dist
        if size is None:
            continue
        neck = NECK.fullmatch(size[4])
        cfm_word = None
        cfm_dist = 42
        for word in words:
            if word[4].upper() != 'CFM':
                continue
            dist = _distance(mark, word)
            if dist < cfm_dist and _nearest(word, marks, 48) is mark:
                cfm_word, cfm_dist = word, dist
        design = None
        if cfm_word is not None:
            number_dist = 30
            for word in words:
                if not re.fullmatch(r'\d{1,4}', word[4]):
                    continue
                dist = _distance(cfm_word, word)
                if dist < number_dist and _nearest(word, marks, 40) is mark:
                    design = int(word[4])
                    number_dist = dist
        unlabeled = None
        if design is None:
            for word in words:
                if not re.fullmatch(r'\d{2,4}', word[4]):
                    continue
                if _nearest(word, marks, 40) is not mark:
                    continue
                dx = _center(word)[0] - _center(size)[0]
                dy = _center(word)[1] - _center(size)[1]
                if abs(dx) < 18 and 6 <= dy <= 26:
                    unlabeled = word[4]
        location = area
        if rooms:
            room_word, room_name = min(rooms, key=lambda item: _distance(mark, item[0]))
            if _distance(mark, room_word) <= 90:
                location = room_name if not area else f'{area} · {room_name}'
        evidence = f'A: {size[4]}'
        if design is not None:
            evidence += f' {design} CFM'
        elif unlabeled:
            evidence += f'; nearby integer {unlabeled} is not labeled CFM'
        outlets.append({
            'include': False,
            'type': 'A',
            'size': size[4],
            'neck_in': float(neck.group(1)),
            'shape': 'round' if neck.group(2) else 'rectangular',
            'system': system,
            'location': '',
            'design_cfm': design,
            'source': name,
            'reference': f'page {page_number}',
            'position': [round(mark[0],2),round(mark[1],2)],
            'evidence': evidence + '; confirm supply duct and room before including'
                        + (f'; nearby room candidate: {location}' if location else '')
                        + (f'; sheet units: {", ".join(sorted(tags))}' if tags else ''),
            '_y': mark[1],
            '_x': mark[0],
        })
    outlets.sort(key=lambda item: (item['_y'], item['_x']))
    for item in outlets:
        item.pop('_y', None)
        item.pop('_x', None)
    return outlets


def parse_pdf(name, data=None, *, path=None, page_numbers=None, checkpoint=None):
    import pymupdf
    warnings = []
    found = []
    outlets = []
    with (pymupdf.open(filename=path) if path is not None else pymupdf.open(stream=data, filetype='pdf')) as doc:
        if doc.page_count > 300:
            raise ValueError('PDF has more than 300 pages')
        class CachedPage:
            # MuPDF text extraction on drawing pages is expensive. All readers
            # share one bounded native word list instead of decoding each pass.
            def __init__(self,page):
                self.page=page; self.words=page.get_text('words') or []
                if len(self.words)>30000:raise ValueError('native page word limit')
            def __getattr__(self,key):return getattr(self.page,key)
            def get_text(self,kind,*args,**kwargs):
                return self.words if kind=='words' else self.page.get_text(kind,*args,**kwargs)
        pages=[]; count=0
        for page in doc:
            cached=CachedPage(page);count+=len(cached.words)
            if count>200000:raise ValueError('native document word limit')
            pages.append(cached)
        legend = diffuser_legend(pages)
        selected=[p for p in pages if page_numbers is None or p.number+1 in page_numbers]
        completed=[]
        for page in selected:
            index=page.number
            words = page_words(page)
            if len(words)<100 and any('PLAN' in w[4].upper() for w in words):
                warnings.append(f'{name}: page {index + 1} is a plan with little readable text; graphic or outlined labels may be missing. Compare the visible drawing manually before accepting coverage')
            # A readable title block does not make an embedded raster schedule
            # readable. Report substantial raster content without claiming OCR.
            if any(pymupdf.Rect(info['bbox']).get_area() > page.rect.get_area()*.25
                   for info in page.get_image_info()):
                warnings.append(f'{name}: page {index + 1} contains substantial raster content; text extraction may omit schedules or callouts even when its title block is readable')
            if len(text_of(words).strip()) < 40:
                warnings.append(f'{name}: page {index + 1} has no readable text and may be a scanned sheet; manual takeoff required')
            found.extend(parse_page(words, index + 1, name))
            outlets.extend(parse_supply_outlets(words, index + 1, name))
            outlets.extend(keyed_outlets(words, index + 1, name, legend))
            outlets.extend(centered_outlets(words, index + 1, name, legend))
            outlets.extend(necked_outlets(words, index + 1, name))
            from abp_outlets import coded_outlets
            outlets.extend(coded_outlets(words,index+1,name))
            outlets.extend(sized_registers(words,index+1,name))
            outlets=distinct_outlets(outlets)
            for outlet in outlets:
                if outlet.get('reference') == f'page {index+1}':
                    outlet['position_coordinate_space']='displayed_pdf_points'
                    outlet['page_rotation']=page.rotation
            completed.append(index+1)
            if checkpoint:checkpoint(found,warnings,outlets,completed,False)
        found.extend(parse_doas_submittal(selected, name))
        for page in selected:
            page_text = readable_text(page)
            if 'DOAS' in page_text.upper() and (re.search(r'Supply Air:\s*[\d,]+', page_text, re.I)
                                               or selection_airflows(page_words(page))):
                if not any(is_submittal(item.get('basis')) and item.get('reference') == f'page {page.number + 1}'
                           and item.get('values', {}).get('design_cfm') for item in found):
                    warnings.append(f'{name}: page {page.number + 1} DOAS selection could not be uniquely associated with a unit mark; review manually')
        found.extend(parse_fan_submittal(selected, name))
        found.extend(packaged_submittals(selected, name))
        if checkpoint:checkpoint(found,warnings,outlets,completed,True)
    for item in found:
        item.setdefault('source', name)
    return found, warnings, outlets


def _unique(items, field):
    values = []
    for item in items:
        value = item.get('values', {}).get(field)
        if value is None or value == '':
            continue
        if value not in values:
            values.append(value)
    return values


def resolve_proposed(candidates):
    """Return review values, flags, and text. Do not mark anything verified."""
    fields = []
    for item in candidates:
        for field in item.get('values', {}):
            if field not in fields:
                fields.append(field)
    proposed = {}
    flags = []
    for field in fields:
        items = [item for item in candidates if item.get('values', {}).get(field) not in (None, '')]
        if field in EVIDENCE_ONLY:
            continue
        submittal = [item for item in items if is_submittal(item.get('basis'))]
        plan = [item for item in items if not is_submittal(item.get('basis'))]
        sub_values = _unique(submittal, field)
        plan_values = _unique(plan, field)
        if field in UNIT_TOTALS and len(sub_values) == 1:
            if plan_values and plan_values != sub_values:
                flags.append(f'{field}: design target {plan_values} and manufacturer selected performance {sub_values} disagree; left blank for review')
            else:
                proposed[field] = sub_values[0]
        elif len(sub_values) > 1:
            flags.append(f'{field}: submittal values disagree; left blank for review')
        elif len(plan_values) == 1:
            proposed[field] = plan_values[0]
        elif len(plan_values) > 1:
            flags.append(f'{field}: plan values disagree; left blank for review')
    selected_flow = _unique(candidates, 'selected_cfm')
    if selected_flow:
        flags.append(f'Manufacturer selected fan airflow {selected_flow} CFM is retained separately from requested design airflow and is not an actual field reading')
    heater_kw = _unique(candidates, 'heater_kw')
    if heater_kw:
        flags.append(f'Rated heater capacity {heater_kw} kW stays as source evidence; original kW and BTU formulas are not overwritten and may differ because of rounded electrical ratings')
    fan = _unique(candidates, 'fan_rpm')
    if len(fan) > 1:
        flags.append('Fan RPM sources disagree ({}); not written to motor RPM'.format(
            ', '.join(f'{value:g}' for value in fan)))
    elif fan:
        flags.append(f'Fan RPM {fan[0]:g} is fan speed, not motor RPM')
    watts_values = _unique(candidates, 'motor_watts')
    if len(watts_values) > 1 and 'motor_hp' not in proposed:
        flags.append('Motor watts differ ({}); not converted to horsepower or FLA'.format(
            ', '.join(f'{value:g}' for value in watts_values)))
    elif watts_values and 'motor_hp' not in proposed:
        flags.append(f'Motor power {watts_values[0]:g} W is not horsepower; motor HP left blank')
    mca = _unique([item for item in candidates if is_submittal(item.get('basis'))], 'unit_mca')
    fla = proposed.get('motor_fla')
    if mca and fla is not None and mca[0] != fla:
        flags.append(f'Unit MCA {mca[0]:g} A is not motor FLA {fla:g} A')
    text = {}
    for field in ('area_served', 'service', 'equipment_location', 'unit_type', 'heating_type'):
        choices = []
        for item in candidates:
            value = (item.get('text') or {}).get(field)
            if value and value not in choices:
                choices.append(value)
        if len(choices) == 1:
            text[field] = choices[0]
        elif len(choices) > 1:
            flags.append(f'{field}: descriptions disagree; left blank for review')
    if any(field in proposed for field in ('cooling_total_btu', 'cooling_sensible_btu', 'heating_output_btu')):
        flags.append('Schedule capacity stays as evidence; coil BTU cells that are formulas are not overwritten')
    return proposed, flags, text


def annotate(record):
    """Attach a review proposal without verifying or filling design inputs."""
    proposed, flags, text = resolve_proposed(record.get('candidates') or [])
    record['design_targets'] = [item for item in record.get('candidates', []) if not is_submittal(item.get('basis'))]
    record['selected_performance'] = [item for item in record.get('candidates', []) if is_submittal(item.get('basis'))]
    record['proposed'] = proposed
    record['flags'] = flags
    record['text_proposed'] = text
    record['status'] = 'UNVERIFIED'
    return record
