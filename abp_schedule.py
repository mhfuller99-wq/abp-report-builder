"""Read mechanical schedule rows, plan outlets, and submittal nameplates.

Words are grouped into visual rows. A tag is accepted only when it leads a
schedule row or an explicit mark, so a distant column cannot glue "B" to "6"
or a model fragment into an equipment tag. Submittal unit totals and motor
nameplate values outrank the plan schedule. Supply-outlet airflow is read
only from a plan callout (type mark, neck, and CFM). A unit total is never
copied onto an outlet. Fan RPM is never stored as motor RPM, and unit MCA is
never stored as motor FLA.
"""
import re

LEAD = re.compile(
    r'^(EF|VRF|DOAS|SSAU|SSCU|EUH|GUH|HVLS|PF|FS|EH)-\d+[A-Z]?\b', re.I)
MAPPED = re.compile(r'^(?:EF|VRF|DOAS|SSAU)-\d+[A-Z]?$', re.I)
VOLT = re.compile(r'\b(\d{2,3}(?:-\d{2,3})?)/(\d+)/(\d)\b')
UNIT_TOTALS = {
    'design_cfm', 'osa_cfm', 'esp', 'total_sp', 'motor_hp', 'motor_fla', 'motor_volts',
    'cooling_edb', 'cooling_ewb', 'cooling_ldb', 'cooling_lwb',
    'heating_edb', 'heating_ldb', 'heating_cfm',
    'heating_input_btu', 'heating_output_btu',
    'cooling_total_btu', 'cooling_sensible_btu',
}
# Kept on the candidate so a reviewer can see them. They are not form inputs:
# fan RPM is not motor RPM, watts are not horsepower, unit MCA is not motor FLA.
EVIDENCE_ONLY = {'fan_rpm', 'motor_watts', 'unit_mca', 'unit_mop', 'brake_hp'}


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
    found = []
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
        family = lead.group(1).upper()
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
    return segments(page.get_text('words') or [])


def parse_doas_submittal(doc, name):
    blob = []
    for page in doc:
        for y, words in _page_segments(page):
            blob.append((y, text_of(words), page.number + 1))
    joined = '\n'.join(text for _y, text, _page in blob)
    if 'DOAS' not in joined.upper() or not re.search(r'Supply Air:\s*[\d,]+', joined, re.I):
        return []
    values = {}
    text = {}

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
    heating_cfm = values.get('design_cfm')
    if heating_cfm:
        values['heating_cfm'] = heating_cfm
    evidence = (f'DOAS-1 submittal nameplate; motor FLA {values.get("motor_fla")}; '
                f'unit MCA {values.get("unit_mca")}; fan RPM {values.get("fan_rpm")}')
    if not values.get('design_cfm'):
        return []
    return [candidate('DOAS-1', values, 'submittal', evidence, 'SUBMITTAL_NAMEPLATE', text)]


def parse_fan_submittal(doc, name):
    found = []
    for page in doc:
        rows = [text_of(words) for _y, words in _page_segments(page)]
        page_text = '\n'.join(rows)
        mark = re.search(r'Mark:\s*((?:EF)-\d+)', page_text, re.I)
        if not mark:
            continue
        tag = mark.group(1).upper()
        values = {}

        def grab(pattern, field):
            match = re.search(pattern, page_text, re.I)
            if match:
                values[field] = number(match.group(1).replace(',', ''))

        grab(r'Actual Volume \(CFM\)\s*([\d,]+)', 'design_cfm')
        if 'design_cfm' not in values:
            grab(r'Requested Volume \(CFM\)\s*([\d,]+)', 'design_cfm')
        grab(r'Fan RPM\s*(\d+)', 'fan_rpm')
        grab(r'FLA \(A\)\s*([\d.]+)', 'motor_fla')
        grab(r'Input Watts \(W\)\s*(\d+)', 'motor_watts')
        volts = VOLT.search(page_text)
        if volts:
            values['motor_volts'] = single_voltage(volts.group(0))
        evidence = (f'{tag} fan submittal; fan RPM {values.get("fan_rpm")}; '
                    f'motor FLA {values.get("motor_fla")}; {values.get("motor_watts")} W')
        found.append(candidate(tag, values, f'page {page.number + 1}', evidence, 'SUBMITTAL_NAMEPLATE'))
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


def parse_pdf(name, data):
    import pymupdf
    warnings = []
    found = []
    outlets = []
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if doc.page_count > 300:
            raise ValueError('PDF has more than 300 pages')
        for index, page in enumerate(doc):
            words = page.get_text('words') or []
            if len(text_of(words).strip()) < 40:
                warnings.append(f'{name}: page {index + 1} has no readable text and may be a scanned sheet; manual takeoff required')
            found.extend(parse_page(words, index + 1, name))
            outlets.extend(parse_supply_outlets(words, index + 1, name))
        found.extend(parse_doas_submittal(doc, name))
        found.extend(parse_fan_submittal(doc, name))
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
            proposed[field] = sub_values[0]
            if plan_values and plan_values != sub_values:
                plan_text = ', '.join(f'{value:g}' if isinstance(value, float) else str(value) for value in plan_values)
                sub_text = f'{sub_values[0]:g}' if isinstance(sub_values[0], float) else str(sub_values[0])
                flags.append(f'{field}: submittal {sub_text} used; plan had {plan_text}')
        elif len(sub_values) > 1:
            flags.append(f'{field}: submittal values disagree; left blank for review')
        elif len(plan_values) == 1:
            proposed[field] = plan_values[0]
        elif len(plan_values) > 1:
            flags.append(f'{field}: plan values disagree; left blank for review')
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
    for field in ('area_served', 'service', 'equipment_location', 'unit_type'):
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
    record['proposed'] = proposed
    record['flags'] = flags
    record['text_proposed'] = text
    record['status'] = 'UNVERIFIED'
    return record
