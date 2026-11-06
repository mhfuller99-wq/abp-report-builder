"""Conservative, coordinate-addressed schedule and plan candidates.

These readers propose design data only. They never verify equipment, infer a
duct connection, or replace an older drawing with an unapproved revision.
"""
import re


def center(word):
    return (word[0] + word[2]) / 2


def rows(words, tolerance=2.6):
    result = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        if not result or abs(word[1] - result[-1][0][1]) > tolerance:
            result.append([word])
        else:
            result[-1].append(word)
    return [sorted(row, key=lambda w: w[0]) for row in result]


def phrases(words, pattern):
    """Find whole header phrases and preserve their visual bounds."""
    found = []
    for row in rows(words):
        for i in range(len(row)):
            for j in range(i + 1, min(i + 7, len(row) + 1)):
                part = row[i:j]
                if any(b[0] - a[2] > 18 for a, b in zip(part, part[1:])):
                    break
                if re.fullmatch(pattern, ' '.join(w[4] for w in part), re.I):
                    found.append((part[0][0], part[0][1], part[-1][2], part[-1][3]))
    return [box for box in found if not any(box != other and abs(box[1]-other[1]) < 3
            and other[0] <= box[0] and other[2] >= box[2] for other in found)]


def schedule_candidates(words, page_number, name):
    """Read supported families beneath explicit MARK and design column headers.

    Column positions, not a fixed numeric order, determine the field. Repeated
    MARK columns bound adjacent schedules. Unlabeled numbers are never imported.
    """
    found = []
    for tagword in words:
        if not re.fullmatch(r'(?:PAHU|MSAH|MSHP|EUH|EF)-\d+[A-Z]?', tagword[4], re.I):
            continue
        marks = [w for w in words if w[4].upper() == 'MARK'
                 and 0 < tagword[1] - w[1] < 85 and abs(center(w) - center(tagword)) < 30]
        if not marks:
            continue
        mark = max(marks, key=lambda w: w[1])
        right = min((w[0] - 12 for w in words if w[4].upper() == 'MARK'
                     and abs(w[1] - mark[1]) < 5 and w[0] > mark[2]), default=100000)
        header = [w for w in words if mark[0] - 20 <= w[0] < right
                  and mark[1] - 65 < w[1] <= mark[1] + 2]
        if any(w[4].upper() in {'ACTUAL','MEASURED','INITIAL','FINAL'} for w in header):
            continue
        row = [w for w in words if mark[0] - 20 <= w[0] < right and abs(w[1] - tagword[1]) < 2]
        family = tagword[4].split('-')[0].upper()
        values = {}
        text = {}

        def take(pattern, field, scale=1):
            anchors = phrases(header, pattern)
            if len(anchors) != 1:
                return
            x = center(anchors[0])
            choices = [w for w in row if abs(center(w) - x) < 25
                       and re.fullmatch(r'\d[\d,]*(?:\.\d+)?', w[4])]
            if len(choices) == 1:
                values[field] = float(choices[0][4].replace(',', '')) * scale

        if family == 'EF':
            take(r'SCFM(?: @ \S+)?', 'design_cfm')
            take(r'ESP \(IN W\.C\.\)', 'esp')
            take(r'MOTOR HP', 'motor_hp')
            take(r'FAN RPM', 'fan_rpm')
            take(r'(?:MOTOR )?WATTS', 'motor_watts')
            take(r'VOLTAGE \(V\)', 'motor_volts')
            take(r'FLA \(A\)', 'motor_fla')
            service = [w[4].upper() for w in row if w[4].upper() in {'CEILING', 'INLINE'}]
            if len(service) == 1:
                text['service'] = service[0]
        elif family == 'PAHU':
            take(r'SUPPLY AIRFLOW', 'design_cfm')
            take(r'OA', 'osa_cfm')
            take(r'E\.S\.P\. \(IN', 'esp')
            take(r'HP', 'motor_hp')
            # Compressor RLA and condenser FLA are not supply motor FLA.
            for pattern, fields in [(r'D\.B\. \(°F\)', ('cooling_edb', 'cooling_ldb')),
                                    (r'W\.B\. \(°F\)', ('cooling_ewb', 'cooling_lwb'))]:
                anchors = sorted(phrases(header, pattern))
                if len(anchors) == 2 and phrases(header, r'ENTERING AIR') and phrases(header, r'LEAVING COIL'):
                    for anchor, field in zip(anchors, fields):
                        choices = [w for w in row if abs(center(w) - center(anchor)) < 18
                                   and re.fullmatch(r'\d+(?:\.\d+)?', w[4])]
                        if len(choices) == 1:
                            values[field] = float(choices[0][4])
            if phrases(header, r'ELECTRIC') and phrases(header, r'HEATER'):
                text['unit_type'] = 'PACKAGED / ELECTRIC HEAT'
        elif family == 'MSAH':
            take(r'TOTAL CFM', 'design_cfm')
            take(r'MCA', 'unit_mca')
        elif family == 'EUH':
            # Keep the source heating capacity even when no validated form exists.
            take(r'\(BTUH\)', 'heating_output_btu')
        evidence = ' '.join(w[4] for w in sorted(row, key=lambda w: w[0]))
        item = {'tag': tagword[4].upper(), 'values': values, 'text': text,
                'source': name, 'reference': f'page {page_number}',
                'evidence': evidence[:240], 'basis': 'PLAN_SCHEDULE'}
        if family in {'EUH', 'MSHP'}:
            item['unmapped'] = True
        found.append(item)
    return found


def diffuser_legend(doc):
    """Read type and neck from a labeled ceiling-diffuser table, never max CFM."""
    legend = {}
    for page in doc:
        words = page.get_text('words') or []
        if not phrases(words, r'LOUVERED FACE CEILING DIFFUSER SCHEDULE'):
            continue
        for row in rows(words):
            for i, word in enumerate(row):
                if not re.fullmatch(r'S[A-Z]', word[4]):
                    continue
                tail = row[i + 1:]
                necks = [w for w in tail if 0 < w[0] - word[0] < 300
                         and re.fullmatch(r'\d+(?:\.\d+)?"[Øø]', w[4])]
                if necks:
                    size = min(necks, key=lambda w: w[0])[4]
                    legend.setdefault(word[4], set()).add(size)
    return {mark: next(iter(sizes)) for mark, sizes in legend.items() if len(sizes) == 1}


def keyed_outlets(words, page_number, name, legend):
    """Read stacked symbol/airflow callouts, preserving unconfirmed associations."""
    # Avoid schedules, details and their rated maximum flows.
    if not phrases(words, r'FLOOR PLAN - HVAC'):
        return []
    notes = set()
    for row in rows(words):
        line = ' '.join(w[4] for w in row)
        match = re.search(r'\b(\d+)\. .*DUCT MOUNTED.*SUPPLY', line, re.I)
        if match:
            notes.add(match[1])
    result = []
    for word in words:
        size = None
        kind = word[4]
        if kind in legend:
            size = legend[kind]
        elif re.fullmatch(r'S[A-Z]', kind):
            # An addendum may omit the original legend. Preserve the symbol as
            # an unselected candidate with no invented neck or system.
            size = ''
        elif re.fullmatch(r'\d+(?:\.\d+)?[xX]\d+(?:\.\d+)?', kind):
            note = [w for w in words if w[4] in notes and -22 < w[0] - word[0] < -3
                    and -3 < w[1] - word[1] < 12]
            if len(note) == 1:
                size, kind = kind, 'DUCT GRILLE'
        if size is None:
            continue
        numbers = [w for w in words if re.fullmatch(r'\d{1,4}', w[4])
                   and abs(w[0] - word[0]) < 4 and 6 < w[1] - word[1] < 14]
        if len(numbers) != 1:
            continue
        flow = int(numbers[0][4])
        result.append({'include': False, 'type': kind, 'size': size,
                       'shape': ('rectangular' if 'x' in size.lower() else 'round') if size else 'unknown',
                       'system': '', 'location': '', 'design_cfm': flow,
                       'source': name, 'reference': f'page {page_number}',
                       'evidence': f'{word[4]} / {flow}; stacked plan callout; confirm supply duct, room and source revision'
                                   + ('; no neck legend in this document' if not size else ''),
                       'position': [round(word[0], 2), round(word[1], 2)]})
    return sorted(result, key=lambda item: (item['position'][1], item['position'][0]))


def packaged_submittals(doc, name):
    """Explicit shared Unit Tag lists in packaged-unit selection sheets."""
    result = []
    for page in doc:
        text = page.get_text(sort=True)
        taglines = re.findall(r'Unit Tag:\s*([^\r\n]+)', text, re.I)
        if len(taglines) != 1 or not re.fullmatch(r'\s*PAHU-\d+(?:\s*,\s*PAHU-\d+)*\s*', taglines[0], re.I):
            continue
        values = {}
        patterns = {
            'design_cfm': r'\bAirflow\s+([\d,]+)\s+cfm',
            'esp': r'Design ESP\s+([\d.]+)\s+in H2O',
            'motor_hp': r'Supply Motor Horsepower\s+([\d.]+)\s+hp',
            'heating_edb': r'Heat pump EAT\s+([\d.]+)\s+F',
            'heating_ldb': r'Heat pump LAT\s+([\d.]+)\s+F',
            'electric_heating_edb': r'(?<!pump )Heating EAT\s+([\d.]+)\s+F',
            'electric_heating_ldb': r'(?<!pump )Heating LAT\s+([\d.]+)\s+F',
        }
        for field, pattern in patterns.items():
            matches = set(re.findall(pattern, text, re.I))
            if len(matches) == 1:
                values[field] = float(next(iter(matches)).replace(',', ''))
        if not values:
            continue
        for tag in re.findall(r'PAHU-\d+', taglines[0], re.I):
            result.append({'tag': tag.upper(), 'values': values.copy(), 'source': name,
                           'reference': f'page {page.number + 1}', 'basis': 'SUBMITTAL_SELECTION',
                           'evidence': f'Explicit shared Unit Tag: {taglines[0].strip()}; packaged selection; review approval/revision',
                           'text': {'unit_type': 'PACKAGED / ELECTRIC HEAT'} if 'Electric Heat' in text else {}})
    return result
