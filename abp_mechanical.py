"""Conservative, coordinate-addressed schedule and plan candidates.

These readers propose design data only. They never verify equipment, infer a
duct connection, or replace an older drawing with an unapproved revision.
"""
import re


def page_words(page):
    """Use displayed page coordinates; PDF text coordinates ignore page rotation."""
    words = page.get_text('words') or []
    # Large drawing sets otherwise retain MuPDF rendering resources between
    # repeated text passes. Returned word tuples do not depend on this cache.
    import pymupdf
    pymupdf.TOOLS.store_shrink(100)
    if not getattr(page, 'rotation', 0):
        return words
    matrix = page.rotation_matrix
    return [(*tuple(pymupdf.Rect(w[:4]) * matrix), *w[4:]) for w in words]


def center(word):
    return (word[0] + word[2]) / 2


def readable_text(page):
    """Bound text size by words, avoiding layout-padding on rotated drawings."""
    return '\n'.join(' '.join(w[4] for w in row) for row in rows(page_words(page)))


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


TAG = r'(?:PAHU|PU|MSAH|MSHP|MS|EUH|GUH|CUH|UH|KEF|EF|SF|RF|FS|PF|VRF|IU|IDU|DSS|DOAS|SSAU|AHU|RTU|MAU|OAU|FCU|SSCU|HVLS|EH|BCU)-\d+(?:\.\d+)*[A-Z]?(?:-\d+(?:\.\d+)*[A-Z]?)?'
MARK_HEADERS = {'MARK', 'TAG', 'ID', 'UNIT MARK', 'UNIT TAG'}


def expand_marks(value):
    """Expand explicit same-family lists and bounded integer ranges, atomically."""
    value = value.upper().strip()
    first = re.match(r'(' + TAG + r')', value)
    if not first:
        return []
    prefix = first.group(1).split('-', 1)[0]
    result = []
    for part in re.split(r'\s*(?:,|&|\bAND\b)\s*', value):
        if not part:
            return []
        if not part.startswith(prefix+'-'):
            part = prefix+'-'+part
        if re.fullmatch(TAG, part) and (prefix == 'BCU' or part.count('-') == 1):
            if part.split('-',1)[0] != prefix:
                return []
            result.append(part)
            continue
        match = re.fullmatch(r'(' + TAG + r')\s*(?:THRU|THROUGH|TO|–|-)\s*(' + TAG + r'|\d+)', part)
        if not match:
            return []
        start, end = match.groups()
        family, start = start.rsplit('-',1)
        if '-' in end:
            other, end = end.rsplit('-',1)
            if other != family:
                return []
        if family != prefix or not start.isdigit() or not end.isdigit() or not 0 <= int(end)-int(start) < 100:
            return []
        result.extend(f'{prefix}-{n}' for n in range(int(start),int(end)+1))
    return list(dict.fromkeys(result))


def selection_airflows(words):
    """Read explicitly unit-labeled vertical airflow columns in selection tables."""
    result = {}
    for label, field in [(r'Supply(?: Air)?', 'design_cfm'), (r'Outdoor Air|Outside Air', 'osa_cfm')]:
        choices = []
        for anchor in phrases(words, label):
            units = [w for w in words if w[4].upper() == '(CFM)'
                     and abs(center(w)-center(anchor)) < 12 and 0 < w[1]-anchor[1] < 20]
            if len(units) != 1:
                continue
            unit = units[0]
            numbers = [w for w in words if re.fullmatch(r'\d[\d,]*(?:\.\d+)?',w[4])
                       and abs(center(w)-center(unit)) < 12 and 5 < w[1]-unit[1] < 25]
            if len(numbers) == 1:
                choices.append(float(numbers[0][4].replace(',','')))
        if len(choices) == 1:
            result[field] = choices[0]
    return result


def joined_schedule_tags(words):
    """Join horizontal CAD tag tokens only inside an explicit ID column.

    An explicit hyphen and unique adjacent number are required. Do not turn a
    nearby schedule value or a prose equipment reference into a new tag.
    """
    added=[];consumed=set()
    family=re.compile(TAG.split(')-',1)[0]+')',re.I)
    for row in rows(words):
        for i,w in enumerate(row):
            if not family.fullmatch(w[4]):continue
            if not any(m[4].upper() in MARK_HEADERS and 0<w[1]-m[1]<600
                       and abs(center(m)-center(w))<30 for m in words):continue
            parts=[w]
            for other in row[i+1:i+3]:
                if other[0]-parts[-1][2]>6 or other[0]<parts[-1][2]-1:break
                if other[4] not in {'-','–','−'} and not re.fullmatch(r'-?\d+(?:\.\d+)*[A-Z]?',other[4],re.I):break
                parts.append(other)
                token=''.join(p[4] for p in parts).replace('–','-').replace('−','-')
                if re.fullmatch(TAG,token,re.I):
                    added.append((w[0],w[1],other[2],w[3],token,*w[5:]))
                    consumed.update(id(p) for p in parts);break
    return [w for w in words if id(w) not in consumed]+added


def schedule_candidates(words, page_number, name):
    """Read supported families beneath explicit MARK and design column headers.

    Column positions, not a fixed numeric order, determine the field. Repeated
    MARK columns bound adjacent schedules. Unlabeled numbers are never imported.
    """
    words = joined_schedule_tags(list(words))
    # Stacked family/number tags are accepted only beneath a matching tag column.
    for word in list(words):
        if not re.fullmatch(TAG.split(')-', 1)[0] + ')', word[4], re.I):
            continue
        marks = [w for w in words if w[4].upper() in MARK_HEADERS
                 and 0 < word[1]-w[1] < 600 and abs(center(w)-center(word)) < 20]
        numbers = [w for w in words if re.fullmatch(r'\d+(?:\.\d+)*[A-Z]?',w[4])
                   and 5 < w[1]-word[1] < 20 and abs(center(w)-center(word)) < 4]
        if marks and len(numbers) == 1:
            n = numbers[0]
            y = (word[1]+n[1])/2
            words.append((word[0],y,word[2],y+word[3]-word[1],word[4]+'-'+n[4],*word[5:]))
    found = []
    consumed = set()
    for tagword in words:
        if id(tagword) in consumed or not re.match(TAG, tagword[4], re.I):
            continue
        adjacent = sorted([w for w in words if abs(w[1]-tagword[1]) < 2 and w[0] >= tagword[0]], key=lambda w: w[0])
        mark_words = [tagword]
        for w in adjacent[1:]:
            if w[0]-mark_words[-1][2] > 18 or not re.fullmatch(r'(?:'+TAG+r'|THRU|THROUGH|TO|AND|[,&–-]|\d+(?:,\d+)*,?)', w[4], re.I):
                break
            mark_words.append(w)
        tags = []
        for count in range(len(mark_words),0,-1):
            tags = expand_marks(' '.join(w[4] for w in mark_words[:count]))
            if tags:
                consumed.update(id(w) for w in mark_words[:count])
                break
        if not tags:
            continue
        marks = [w for w in words if w[4].upper() in MARK_HEADERS
                 and 0 < tagword[1]-w[1] < 600 and abs(center(w)-center(tagword)) < 30]
        if not marks:
            continue
        mark = max(marks, key=lambda w: w[1])
        first_row = min((w[1] for w in words if re.fullmatch(TAG,w[4],re.I)
                         and w[1] > mark[1] and abs(center(w)-center(mark)) < 30), default=tagword[1])
        right = min((w[0] - 12 for w in words if w[4].upper() in MARK_HEADERS
                     and abs(w[1] - mark[1]) < 5 and w[0] > mark[2]), default=100000)
        header = [w for w in words if mark[0] - 20 <= w[0] < right
                  and mark[1] - 65 < w[1] < first_row - 3]
        if any(w[4].upper() in {'ACTUAL','MEASURED','INITIAL','FINAL'}
               and not (w[4].lower()=='actual' and any(u[4].lower()=='paper' and 0<u[0]-w[2]<8 and abs(u[1]-w[1])<3 for u in header))
               for w in header):
            continue
        row = [w for w in words if mark[0] - 20 <= w[0] < right and abs(w[1] - tagword[1]) < 3]
        family = tags[0].split('-')[0]
        values = {}
        text = {}
        value_words = {}

        def take(pattern, field, scale=1):
            anchors = phrases(header, pattern)
            if field.startswith('heater_'):
                motor = phrases(header, r'(?:MOTOR|FAN) (?:VOLTS?|VOLTAGE|PHASE|PH|AMPS|FLA|KW)')
                anchors = [a for a in anchors if not any(abs(a[1]-b[1]) < 3 and b[0] <= a[0] and b[2] >= a[2] for b in motor)]
            if field == 'design_cfm':
                outside = phrases(header, r'(?:OUTSIDE AIR|OUTDOOR AIR|OA|OSA|EXHAUST|RETURN)(?: CFM| \(CFM\))|(?:PEAK|MAXIMUM|MAX|RATED|SELECTED)(?: FAN)? AIRFLOW')
                anchors = [a for a in anchors if not any(abs(a[1]-b[1]) < 3 and b[0] <= a[0] and b[2] >= a[2] for b in outside)]
            if len(anchors) != 1:
                return
            x = center(anchors[0])
            tolerance = max(25, (anchors[0][2]-anchors[0][0])/2) if field == 'selected_cfm' else 25
            choices = [w for w in row if abs(center(w) - x) < tolerance
                       and re.fullmatch(r'(?:\d[\d,]*(?:\.\d+)?|\.\d+)' + (r'|\d+/[1-9]\d*' if field == 'motor_hp' else ''), w[4])]
            if len(choices) == 1:
                value = choices[0][4].replace(',', '')
                values[field] = (float(value.split('/')[0])/float(value.split('/')[1]) if '/' in value else float(value)) * scale
                a=anchors[0]
                value_words[field] = [tagword, choices[0]] + [w for w in header if a[0] <= w[0] and w[2] <= a[2] and abs(w[1]-a[1]) < 3]

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
        elif family in {'EUH','GUH','CUH','UH'}:
            # Capacities are evidence; the original heater BTU/kW cells are formulas.
            take(r'\(BTUH\)', 'heating_output_btu')
            take(r'(?:HEATER )?(?:VOLT|VOLTS|VOLTAGE)', 'heater_volts')
            take(r'(?:HEATER )?(?:PH|PHASE)', 'heater_phase')
            take(r'(?:HEATER )?AMPS', 'heater_amps')
            take(r'(?:HEATER )?STAGES', 'heater_stages')
            take(r'\(KW\)|HEATER KW', 'heater_kw')
            take(r'ENTERING WATER TEMP\.?|EWT', 'heating_ewt')
            take(r'LEAVING WATER TEMP\.?|LWT', 'heating_lwt')
            take(r'GPM', 'design_gpm')
            take(r'WATER (?:DP|∆P) FT\.?', 'water_dp_ft')
            kinds = []
            for pattern, kind in [(r'ELECTRIC UNIT HEATER SCHEDULE','ELECTRIC'),
                                  (r'GAS(?: FIRED)? UNIT HEATER SCHEDULE','GAS'),
                                  (r'(?:HOT WATER|HYDRONIC) UNIT HEATER SCHEDULE','HOT WATER')]:
                if phrases(header, pattern):kinds.append(kind)
            if len(kinds)==1:text['heating_type']=kinds[0]
        take(r'(?:DESIGN |TOTAL |SUPPLY |SUPPLY AIR |SA )?(?:CFM|AIRFLOW)(?: \(CFM\))?|SCFM(?: @ \S+)?', 'design_cfm')
        take(r'(?:OUTSIDE AIR|OUTDOOR AIR|OA|OSA)(?: CFM| \(CFM\))?', 'osa_cfm')
        take(r'(?:ESP|E\.S\.P\.)(?: \(.*\))?', 'esp')
        take(r'EXT\.? S\.?P\.?(?: IN\.? WG)?', 'esp')
        take(r'MOTOR HP', 'motor_hp')
        take(r'MOTOR FLA', 'motor_fla')
        take(r'MOTOR VOLTS|VOLTAGE \(V\)', 'motor_volts')
        take(r'FAN RPM', 'fan_rpm')
        take(r'MCA', 'unit_mca')
        # Stacked headers are common in CAD schedules. Bind each numeric value
        # to its own labeled column; never use a fixed numeric field order.
        numeric = [w for w in row if re.fullmatch(r'\d[\d,]*(?:\.\d+)?', w[4])]
        def below(anchor, field):
            choices = sorted(numeric, key=lambda w: abs(center(w)-center(anchor)))
            if choices and abs(center(choices[0])-center(anchor)) < 18:
                if len(choices) == 1 or abs(center(choices[1])-center(anchor)) > abs(center(choices[0])-center(anchor))+5:
                    if field not in values:
                        values[field] = float(choices[0][4].replace(',', ''))
                        value_words[field] = [tagword, choices[0]] + [w for w in header if abs(center(w)-center(anchor)) < 30 and 0 <= anchor[1]-w[1] < 38]
        for anchor in phrases(header, r'CFM|AIRFLOW|ESP|E\.S\.P\.|HP'):
            context = ' '.join(w[4].upper() for w in sorted(header,key=lambda w:(w[1],w[0]))
                               if abs(center(w)-center(anchor)) < 30 and 0 <= anchor[1]-w[1] < 38)
            label = next((w[4].upper() for w in header if tuple(w[:4]) == anchor), '')
            if label in {'ESP','E.S.P.'}:below(anchor,'esp')
            elif label == 'HP' and 'MOTOR' in context:below(anchor,'motor_hp')
            elif label in {'CFM','AIRFLOW'}:
                if re.search(r'\b(?:OUTDOOR|OUTSIDE|O/?A|OSA)\b',context):below(anchor,'osa_cfm')
                elif 'SUPPLY' in context or (label == 'AIRFLOW' and family == 'BCU'):below(anchor,'design_cfm')
        # A SUPPLY FAN heading can span CFM, ESP and HP subcolumns. Bind the
        # single nearby CFM column after rejecting outside/return/exhaust air.
        supply_groups=phrases(header,r'SUPPLY FAN')
        supply_flows=[]
        for anchor in phrases(header,r'CFM|AIRFLOW'):
            context=' '.join(w[4].upper() for w in header if abs(center(w)-center(anchor))<30 and 0<=anchor[1]-w[1]<38)
            if re.search(r'\b(?:OUTDOOR|OUTSIDE|O/?A|OSA|RETURN|EXHAUST)\b',context):continue
            if any(abs(center(g)-center(anchor))<75 and 0<anchor[1]-g[1]<45 for g in supply_groups):supply_flows.append(anchor)
        if len(supply_flows)==1:below(supply_flows[0],'design_cfm')
        # Fan schedules often spell static pressure S.P. IN / INCHES / IN H2O.
        # Keep this abbreviation confined to fan equipment and labeled units.
        if family in {'EF','KEF','SF','RF','PF'}:
            anchors=phrases(header,r'S\.P\.(?: IN)?')
            if len(anchors)==1:
                anchor=anchors[0]
                context=' '.join(w[4].upper() for w in header if abs(center(w)-center(anchor))<25 and -20<w[1]-anchor[1]<40)
                if re.search(r'\b(?:INCHES|H2O|H20)\b',context):below(anchor,'esp')
        for anchor in phrases(header, r'EXTERNAL'):
            nearby = ' '.join(w[4].upper() for w in header if abs(center(w)-center(anchor)) < 22 and 0 < w[1]-anchor[1] < 40)
            if 'STATIC' in nearby and 'PRESSURE' in nearby:below(anchor,'esp')
        if phrases(header,r'OCCUPIED') and phrases(header,r'UNOCCUPIED'):
            for label,field in [(r'TOTAL AIRFLOW','design_cfm'),(r'OUTSIDE AIR','osa_cfm')]:
                anchors=phrases(header,label)
                # Exclude a larger schedule title above the actual column band.
                if anchors:
                    lowest=max(a[1] for a in anchors)
                    anchors=[a for a in anchors if abs(a[1]-lowest)<3]
                if len(anchors)!=1:continue
                anchor=anchors[0]
                cfm_values=[float(w[4].replace(',','')) for w in numeric if abs(center(w)-center(anchor))<95
                            and any(u[4].upper()=='CFM' and -2<u[0]-w[2]<8 and abs(u[1]-w[1])<3 for u in row)
                            and float(w[4].replace(',',''))>0]
                if len(cfm_values)==2 and len(set(cfm_values))==1:values[field]=cfm_values[0]
        heat_labels = phrases(header, r'MEDIUM|TYPE')
        for anchor in heat_labels:
            above = ' '.join(w[4].upper() for w in header if abs(center(w)-center(anchor)) < 65 and 0 < anchor[1]-w[1] < 40)
            if 'HEATING' not in above and family not in {'UH','EUH','GUH','BCU','RTU','OAU','AHU'}:continue
            cell = ' '.join(w[4].upper() for w in row if abs(center(w)-center(anchor)) < 28)
            if 'ELEC' in cell:text.update(heating_type='ELECTRIC',unit_type='ELECTRIC HEAT')
            elif 'HOT WATER' in cell:text.update(heating_type='HOT WATER',unit_type='HYDRONIC')
            elif re.search(r'\bGAS\b',cell):text.update(heating_type='GAS',unit_type='GAS HEAT')
        if family in {'EUH','GUH','CUH','UH'}:
            take(r'HEATING CFM|CFM', 'heating_cfm')
            values.pop('design_cfm', None)
        if phrases(header, r'DUCTED') and phrases(header, r'UNIT FAN'):
            take(r'SA', 'design_cfm')
        peak = phrases(header, r'Peak Fan Airflow')
        if peak:
            take(r'Peak Fan Airflow', 'selected_cfm')
        if family == 'DOAS':
            text['unit_type'] = 'DOAS'
        evidence = ' '.join(w[4] for w in sorted(row, key=lambda w: w[0]))
        item = {'tag': tags[0], 'values': values, 'text': text,
                'value_words': value_words,
                'source': name, 'reference': f'page {page_number}',
                'evidence': evidence[:240], 'basis': 'SUBMITTAL_SELECTION' if peak else 'PLAN_SCHEDULE'}
        if family == 'MSHP':
            item['unmapped'] = True
        for tag in tags:
            found.append({**item, 'tag': tag, 'values': values.copy()})
    return found


def diffuser_legend(doc):
    """Read type and neck from a labeled ceiling-diffuser table, never max CFM."""
    legend = {}
    for page in doc:
        words = page_words(page)
        if not phrases(words, r'(?:LOUVERED FACE CEILING )?DIFFUSER (?:SCHEDULE|LEGEND)|(?:DIFFUSER/REGISTER/GRILLE|AIR TERMINAL|REGISTER,? GRILLE,? (?:&|AND) DIFFUSER|AIR DEVICE|AIR DISTRIBUTION DEVICE) SCHEDULE'):
            continue
        all_neck_headers=phrases(words,r'NECK(?: SIZE)?')
        for row in rows(words):
            for i, word in enumerate(row):
                if not re.fullmatch(r'(?:S[A-Z]|[A-Z]\d?|SD\d*|[A-Z]-\d+|\d+s)', word[4]):
                    continue
                tail = row[i + 1:]
                description = ' '.join(w[4] for w in words if word[0] < w[0] < word[0]+170
                                       and abs(w[1]-word[1]) < 4).upper()
                if any(kind in description for kind in ('RETURN','EXHAUST','TRANSFER')):
                    continue
                necks = [w for w in tail if 0 < w[0] - word[0] < 300
                         and re.fullmatch(r'\d+(?:\.\d+)?(?:"[Øø]|"?[xX]\d+(?:\.\d+)?"?)', w[4])]
                neck_headers=[a for a in all_neck_headers if 0<word[1]-a[1]<100 and word[0]<a[0]<word[0]+300]
                if neck_headers:
                    nearest=max(neck_headers,key=lambda a:a[1])
                    necks=[w for w in necks if abs(center(w)-center(nearest))<30]
                if necks:
                    size = min(necks, key=lambda w: w[0])[4]
                    legend.setdefault(word[4], set()).add(size)
                elif 'SUPPLY' in description or 'DIFFUSER' in description:
                    legend.setdefault(word[4], set()).add('')
    return {mark: next(iter(sizes)) for mark, sizes in legend.items() if len(sizes) == 1}


def keyed_outlets(words, page_number, name, legend):
    """Read stacked symbol/airflow callouts, preserving unconfirmed associations."""
    # Avoid schedules, details and their rated maximum flows.
    from abp_outlets import plan_context, EQUIPMENT_MARKS
    if not plan_context(words):
        return []
    notes = set()
    for row in rows(words):
        line = ' '.join(w[4] for w in row)
        match = re.search(r'\b(\d+)\. .*DUCT MOUNTED.*SUPPLY', line, re.I)
        if match:
            notes.add(match[1])
    result = []
    indicators=[w for w in words if w[4].upper()=='INDICATES']
    for word in words:
        if any(0 < w[0]-word[0] < 140 and abs(w[1]-word[1])<18 for w in indicators):
            continue  # A symbol-key example is not a physical outlet.
        size = None
        kind = word[4].rstrip(',')
        if kind in EQUIPMENT_MARKS:continue
        if kind in legend:
            size = legend[kind]
        elif re.fullmatch(r'[A-Z]',kind):
            # Unclassified type letters need an explicit round neck/flow pair.
            # Retain as unselected candidates, never infer a supply connection.
            necks=[w for w in words if 0 < w[0]-word[2] < 18 and -8 < w[1]-word[1] < 0
                   and re.fullmatch(r'\d+(?:\.\d+)?"[Øø⌀\ufffd]',w[4])]
            if len(necks)==1:
                neck=necks[0]
                flows=[w for w in words if re.fullmatch(r'\d{1,4}',w[4]) and abs(w[0]-neck[0])<3 and 6<w[1]-neck[1]<15]
                if len(flows)==1:
                    result.append({'include':False,'type':kind,'size':neck[4],'shape':'round','system':'','location':'',
                                   'design_cfm':int(flows[0][4]),'source':name,'reference':f'page {page_number}',
                                   'evidence':'Type / round neck / airflow callout; supply service and duct association unconfirmed; review before including',
                                   'position':[round(word[0],2),round(word[1],2)]})
            continue
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
        # A type followed by a neck, with its flow stacked under that neck.
        # Both links must be unique; a loose nearby number is never enough.
        necks = [w for w in words if 0 < w[0]-word[2] < 18 and abs(w[1]-word[1]) < 3
                 and re.fullmatch(r'\d+(?:\.\d+)?(?:[xX]\d+(?:\.\d+)?"|"[ØOo])',w[4])]
        flow_anchor = word
        if len(necks) == 1:
            flow_anchor = necks[0]
            size = necks[0][4]
        numbers = [w for w in words if re.fullmatch(r'\d{1,4}', w[4])
                   and (abs(w[0] - flow_anchor[0]) < 4 or
                        (flow_anchor is word and not size and abs(center(w)-center(word)) < 4))
                   and 6 < w[1] - flow_anchor[1] < 18]
        if not numbers:
            # Explicit CFM beside the value supports offset callouts. A nearby
            # unlabeled number is deliberately insufficient.
            numbers = [w for w in words if re.fullmatch(r'\d{1,4}',w[4])
                       and abs(center(w)-center(word)) < 35 and 6 < w[1]-word[1] < 30
                       and any(u[4].upper()=='CFM' and 0 < u[0]-w[2] < 8 and abs(u[1]-w[1]) < 3 for u in words)]
        if len(numbers) != 1:
            continue
        flow = int(numbers[0][4])
        if not 10 <= flow <= 10000:continue
        result.append({'include': False, 'type': kind, 'size': size,
                       'shape': ('rectangular' if 'x' in size.lower() else 'round') if size else 'unknown',
                       'system': '', 'location': '', 'design_cfm': flow,
                       'source': name, 'reference': f'page {page_number}',
                       'evidence': f'{word[4]} / {flow}; stacked plan callout; confirm supply duct, room and source revision'
                                   + ('; no neck legend in this document' if not size else ''),
                       'position': [round(word[0], 2), round(word[1], 2)]})
        quantities=[re.fullmatch(r'\(TYP[- ](\d+)\)',w[4],re.I) for w in words
                    if abs(center(w)-center(word)) < 25 and 0 < w[1]-numbers[0][1] < 18]
        quantities=[int(m[1]) for m in quantities if m]
        if len(quantities)==1 and 1 < quantities[0] <= 50:
            item=result[-1]
            item['evidence'] += f'; explicitly repeated TYP-{quantities[0]}; confirm each physical location'
            for occurrence in range(2,quantities[0]+1):
                result.append({**item,'evidence':item['evidence']+f'; occurrence {occurrence}'})
    return sorted(result, key=lambda item: (item['position'][1], item['position'][0]))


def packaged_submittals(doc, name):
    """Explicit shared tags on a single packaged selection/product page.

    Product identity remains useful when performance pages are raster-only.
    Never carry the tags forward to an untagged page or assume heating type.
    """
    result = []
    for page in doc:
        text = readable_text(page)
        if re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|FINAL READING|TEST REPORT)\b',text,re.I):
            continue
        taglines = re.findall(r'(?:Unit Tag:|\bTag\(s\):)[ \t]*([^\r\n]+)', text, re.I)
        if len(taglines) != 1 or not re.fullmatch(r'\s*(?:PAHU|PU)-\d+(?:\s*,\s*(?:PAHU|PU)-\d+)*\s*', taglines[0], re.I):
            continue
        tags = expand_marks(taglines[0])
        if not tags or (tags[0].startswith('PU-') and not re.search(r'Packaged.*(?:Unit|Rooftop)', text, re.I)):
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
        # Trane product-data wording labels supply motor HP explicitly. Fan
        # drive RPM and whole-unit electrical values are deliberately ignored.
        if 'motor_hp' not in values:
            matches = set(re.findall(r'\b([\d.]+)\s+hp supply motor\b', text, re.I))
            if len(matches) == 1: values['motor_hp'] = float(next(iter(matches)))
        unit_text = {}
        if re.search(r'\bDX Cooling,?\s+no heat\b', text, re.I):
            unit_text['unit_type'] = 'PACKAGED / DX COOLING ONLY'
        elif 'Electric Heat' in text:
            unit_text['unit_type'] = 'PACKAGED / ELECTRIC HEAT'
        for tag in tags:
            result.append({'tag': tag.upper(), 'values': values.copy(), 'source': name,
                           'reference': f'page {page.number + 1}', 'basis': 'SUBMITTAL_SELECTION',
                           'evidence': f'Explicit shared tags: {taglines[0].strip()}; packaged selection; review approval/revision',
                           'text': unit_text.copy()})
    return result
