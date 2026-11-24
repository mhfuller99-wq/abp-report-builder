"""Read design airflow and pressure from ruled equipment tables on schedule drawings."""
import re


UNIT = re.compile(r'(RTU|AHU|FCU|AH|EF|KEF|SF|RF)-?(\d+(?:\.\d+)*[A-Z]?)\Z', re.I)
TITLES = (
    (r'(?:PACKAGED )?ROOFTOP UNITS?(?: ELECTRIC HEAT| GAS HEAT)?', {'RTU'}),
    (r'(?:DX )?FAN COIL UNITS?', {'FCU'}),
    (r'AIR HANDLING UNITS?', {'AH', 'AHU'}),
    (r'(?:INVERTER DRIVEN )?MINI[- ]SPLIT SYSTEMS?(?: ONE[- ]TO[- ]ONE)?', {'AH', 'FCU'}),
    (r'(?:GENERAL )?EXHAUST FANS?', {'EF', 'KEF'}),
    (r'SUPPLY FANS?', {'SF'}),
    (r'RETURN FANS?', {'RF'}),
)


def label(text):
    text = re.sub(r'\(\d+\)', ' ', text.upper())
    return ' '.join(re.sub(r'[.,()]', '', text).split())


def field_for(text, fan):
    if text in {'EVAP CFM', 'EVAPORATOR CFM', 'SA CFM', 'SUPPLY CFM', 'SUPPLY AIR CFM'} or (fan and text == 'CFM'):
        return 'design_cfm'
    if text in {'OA CFM', 'OUTSIDE AIR CFM', 'OUTDOOR AIR CFM'}:
        return 'osa_cfm'
    if re.fullmatch(r'(?:ESTIMATED )?(?:EXT SP|EXTERNAL STATIC PRESSURE|ESP) (?:IN )?(?:WG|WC)', text):
        return 'esp'
    return None


def matching_columns(row, box):
    return [(cell, text) for cell, text in row
            if abs(cell[0] - box[0]) < 1 and abs(cell[2] - box[2]) < 1]


def row_readings(band, id_box, fields):
    values, evidence = {}, []
    for field, columns in fields.items():
        if len(columns) != 1:
            continue
        head_box, heading = columns[0]
        data = matching_columns(band, head_box)
        if len(data) != 1:
            continue
        cell, number = data[0]
        if (abs(cell[1] - id_box[1]) >= 1 or abs(cell[3] - id_box[3]) >= 1 or len(number) > 16
                or not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+', number)):
            continue
        value = float(number.replace(',', ''))
        if value <= 1_000_000:
            values[field] = value
            evidence.append(f'{" ".join(heading.split())} = {number}')
    return values, evidence


def table_records(table, name, page_number):
    """Require a shared title cell, explicit headers and identical ruled column edges."""
    if table.row_count * table.col_count > 12000:
        return []
    rows = [[(box, text.strip()) for box, text in zip(row.cells, strings) if box and text and text.strip()]
            for row, strings in zip(table.rows, table.extract())]
    result = []
    for index, row in enumerate(rows):
        if index == 0:
            continue
        for mark, text in row:
            if text.upper() != 'DESIGNATION':
                continue
            titles = [(box, families) for band in rows[:index] for box, title in band
                      if box[0] <= mark[0] + 1 and mark[2] < box[2] and abs(mark[1] - box[3]) < 1
                      for pattern, families in TITLES if re.fullmatch(pattern, label(title))]
            if len(titles) != 1:
                continue
            title, families = titles[0]
            header = [(box, heading) for band in rows[index:] for box, heading in band
                      if title[0]-1 <= box[0] and box[2] <= title[2]+1 and mark[1]-1 <= box[1] < mark[3]-1]
            if any(re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|FINAL|AS FOUND|AS LEFT)\b', label(h)) for _, h in header):
                continue
            fields = {}
            for box, heading in header:
                field = field_for(label(heading), families <= {'EF', 'KEF', 'SF', 'RF'})
                if field and abs(box[3] - mark[3]) < 1:
                    fields.setdefault(field, []).append((box, heading))
            expected_top = mark[3]
            for band in rows[index + 1:]:
                band = [(box, value) for box, value in band if title[0]-1 <= box[0] and box[2] <= title[2]+1
                        and box[1] >= expected_top - 1]
                if not band:
                    continue
                identifiers = matching_columns(band, mark)
                if len(identifiers) != 1:
                    break
                id_box, printed = identifiers[0]
                if abs(id_box[1] - expected_top) >= 1:
                    break
                expected_top = id_box[3]
                tag = UNIT.fullmatch(printed)
                if not tag or tag[1].upper() not in families:
                    # Indoor and outdoor split-system rows can alternate in the same grid.
                    if re.fullmatch(r'(?:AC|CU)-?\d+[A-Z]?', printed, re.I):
                        continue
                    break
                values, evidence = row_readings(band, id_box, fields)
                if values:
                    result.append({'tag': f'{tag[1].upper()}-{tag[2].upper()}', 'values': values,
                                   'source': name, 'reference': f'page {page_number}', 'basis': 'PLAN_SCHEDULE',
                                   'evidence': f'DESIGNATION {printed}. ' + ', '.join(evidence)})
    return result


def schedule_clip(words, page_rect):
    marks = [w for w in words if w[4].upper() == 'DESIGNATION']
    if not marks or len(marks) > 60:
        return None
    # Manufacturer selections and field reports may have similar grids. Require an
    # explicit drawing schedule title in addition to the equipment table's own title.
    blocks = {}
    for w in words:
        blocks.setdefault((w[5], w[6]), []).append(w)
    if not any(re.fullmatch(r'(?:MECHANICAL|HVAC)(?: EQUIPMENT)? SCHEDULES?(?: CONT\.?)?',
                            ' '.join(w[4].upper() for w in line))
               for line in blocks.values()):
        return None
    import pymupdf
    tags = [w for w in words if UNIT.fullmatch(w[4])]
    if len(tags) > 600:
        return None
    anchors = [(m, t) for m in marks for t in tags if 0 < t[1] - m[1] < 600
               and m[0] <= (t[0]+t[2])/2 <= m[2]]
    if not anchors:
        return None
    # Coordinates passed to find_tables are displayed-page coordinates. Include
    # the merged title and enough bottom margin to retain the last complete row.
    return pymupdf.Rect(min(m[0]-80 for m, _ in anchors), min(m[1]-100 for m, _ in anchors),
                        page_rect.x1, max(t[3]+25 for _, t in anchors)) & page_rect


def read_clip(page, clip, name):
    tables = page.find_tables(clip=clip, strategy='lines_strict').tables
    return [record for table in tables for record in table_records(table, name, page.number+1)]


def designation_records(page, words, name):
    clip = schedule_clip(words, page.rect)
    if clip:
        records = read_clip(page, clip, name)
        if records:
            return records
    rotation = page.rotation
    if rotation:
        # A sideways sheet can still have a horizontal grid in native PDF space.
        # Only adjust this open document, restoring its rotation before returning.
        clip = schedule_clip(page.get_text('words'), page.rect * page.derotation_matrix)
        if clip:
            try:
                page.set_rotation(0)
                return read_clip(page, clip, name)
            finally:
                page.set_rotation(rotation)
    return []
