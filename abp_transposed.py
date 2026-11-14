"""Titled mechanical schedules with equipment across columns.

The same geometric reader accepts native and OCR word tuples. Its proposals
retain the title, tag, row label and value together; OCR checks all of them.
No plan-mark inference, model-based capacity inference or unit conversion from
electrical protection to motor ratings is performed here.
"""
import re
from abp_mechanical import SCHEDULE_TAG, center, rows

TITLE = re.compile(r'(?:GAS )?FURNACE SCHEDULE:?|(?:AIR HANDLING|ROOFTOP|FAN COIL|'
                   r'EXHAUST FAN|SUPPLY FAN|MECHANICAL EQUIPMENT)(?: UNIT)? SCHEDULE:?', re.I)
MARK = re.compile(r'(?:UNIT |EQUIPMENT )?(?:TAG|MARK|ID):?', re.I)
TAG = re.compile(r'(?:' + SCHEDULE_TAG + r'|F-\d+(?:\.\d+)*[A-Z]?)', re.I)
NUMBER = re.compile(r'(?:\d[\d,]*(?:\.\d+)?|\.\d+)')


def reread_requested(words):
    """Layout hint only: request clearer glyphs, never supply an ID or value."""
    if len(words)>30000:return False
    tuples=[(*w['box'],w['text']) for w in words]
    marks=[w for w in tuples if MARK.fullmatch(w[4])]
    for mark in marks:
        labels=[]
        for line in rows(tuples):
            left=[w for w in line if abs(w[0]-mark[0])<3]
            if not left or not 0<line[0][1]-mark[1]<300:continue
            phrase=[w for w in line if mark[0]-3<=w[0]<mark[0]+150]
            field=label_field(' '.join(w[4] for w in phrase))
            if field:labels.append(field[0])
        if 'design_cfm' in labels and len(set(labels))>=3:return True
    return False


def label_field(label):
    """Only explicit units and whole labels; no substring CFM/HP matching."""
    label = re.sub(r'\s+', ' ', label.upper()).strip(' :')
    patterns = [
        (r'(?:DESIGN |TOTAL |SUPPLY |SUPPLY AIR )?(?:CFM|AIRFLOW \(CFM\))', 'design_cfm', 'CFM', 1),
        (r'(?:OUTSIDE AIR|OUTDOOR AIR|O\.?A\.?|OSA) (?:CFM|\(CFM\))', 'osa_cfm', 'CFM', 1),
        (r'(?:ESP|E\.S\.P\.|EXTERNAL STATIC PRESSURE)(?: \((?:IN(?:\.|CHES)? ?(?:W\.?C\.?|WG|H2O)|IN)\))?', 'esp', 'IN W.C.', 1),
        (r'TOTAL (?:STATIC PRESSURE|S\.P\.)(?: \(IN W\.?C\.?\))?', 'total_sp', 'IN W.C.', 1),
        (r'MOTOR (?:HP|HORSEPOWER)', 'motor_hp', 'HP', 1),
        (r'MOTOR FLA(?: \(A\))?', 'motor_fla', 'A', 1),
        (r'MOTOR (?:VOLTS|VOLTAGE)(?: \(V\))?', 'motor_volts', 'V', 1),
        (r'FAN RPM', 'fan_rpm', 'RPM', 1),
        (r'(?:HEAT|HEATING) INPUT \(MBH\)', 'heating_input_btu', 'MBH', 1000),
        (r'(?:HEAT|HEATING) OUTPUT \(MBH\)', 'heating_output_btu', 'MBH', 1000),
        (r'TOTAL COOLING \(MBH\)', 'cooling_total_btu', 'MBH', 1000),
        (r'SENSIBLE COOLING \(MBH\)', 'cooling_sensible_btu', 'MBH', 1000),
        (r'MCA', 'unit_mca', 'A', 1),
        (r'MOCP|MOP', 'unit_mop', 'A', 1),
        (r'QTY\.?|QUANTITY', 'quantity', 'COUNT', 1),
    ]
    return next(((field, unit, scale) for pattern, field, unit, scale in patterns
                 if re.fullmatch(pattern, label)), None)


def _segments(row):
    result = [[]]
    for word in row:
        if result[-1] and word[0] - result[-1][-1][2] > 18:
            result.append([])
        result[-1].append(word)
    return result


def candidates(words, page_number, source):
    if len(words) > 30000:
        return []
    lines = rows(words)
    titles = [part for line in lines for part in _segments(line)
              if TITLE.fullmatch(' '.join(w[4] for w in part))]
    result = []
    for title in titles:
        left, top = title[0][:2]
        next_title = min((t[0][0] for t in titles if t[0][0] > title[-1][2]
                          and abs(t[0][1] - top) < 10), default=left + 1200)
        headers = []
        for line in lines:
            if not 0 < line[0][1] - top < 65:
                continue
            local = [w for w in line if left - 15 <= w[0] < next_title]
            marks = [part for part in _segments(local)
                     if MARK.fullmatch(' '.join(w[4] for w in part))
                     and abs(part[0][0] - left) < 25]
            if len(marks) != 1:
                continue
            mark = marks[0]
            # Another tag/mark header bounds a horizontally adjacent table.
            right = min((w[0] for w in local if w[0] > mark[-1][2]
                         and MARK.fullmatch(w[4])), default=next_title)
            axis = [w for w in local if mark[-1][2] < w[0] < right]
            if not axis or any(not TAG.fullmatch(w[4]) for w in axis):
                continue
            if len({w[4].upper() for w in axis}) != len(axis):
                continue
            if any(w[4].upper().startswith('F-') for w in axis) and 'FURNACE' not in ' '.join(w[4].upper() for w in title):
                continue
            headers.append((mark, axis, right))
        if len(headers) != 1:
            continue
        mark, axis, right = headers[0]
        centers = [center(w) for w in axis]
        spacing = min((b - a for a, b in zip(centers, centers[1:])), default=max(40, centers[0] - mark[-1][2]))
        if spacing < 15:
            continue
        bounds = [centers[0] - spacing / 2] + [(a + b) / 2 for a, b in zip(centers, centers[1:])] + [min(right, centers[-1] + spacing / 2)]
        bottom = min((t[0][1] for t in titles if t[0][1] > mark[0][1]
                      and left - 15 <= t[0][0] < bounds[-1]), default=mark[0][1] + 600)
        parsed = [dict(tag=w[4].upper(), values={}, text={}, value_words={}, text_words={},
                       field_evidence={}, source=source, reference=f'page {page_number}',
                       basis='PLAN_SCHEDULE', method='transposed_schedule',
                       evidence=' '.join(w[4] for w in title), identity_words=title + mark + [w]) for w in axis]
        rejected = [set() for _ in axis]
        previous_y = mark[0][1]
        for line in lines:
            if not mark[0][1] < line[0][1] < bottom:
                continue
            local = [w for w in line if left - 15 <= w[0] and w[2] <= bounds[-1]]
            labels = [w for w in local if w[2] < bounds[0]]
            if not labels:
                continue
            label = ' '.join(w[4] for w in labels).upper().strip(' :')
            if label in {'NOTES', 'NOTE'} or re.search(r'\b(?:ACTUAL|MEASURED|INITIAL|FINAL|TEST REPORT)\b', label):
                break
            if line[0][1] - previous_y > max(35, (mark[0][3] - mark[0][1]) * 5):
                break
            previous_y = line[0][1]
            field = label_field(label)
            for i, item in enumerate(parsed):
                cell = [w for w in local if bounds[i] <= w[0] and w[2] <= bounds[i+1]]
                if not cell:
                    continue
                printed = ' '.join(w[4] for w in cell).strip()
                evidence = item['identity_words'] + labels + cell
                if field and NUMBER.fullmatch(printed):
                    name, unit, scale = field
                    value = float(printed.replace(',', '')) * scale
                    if not 0 <= value <= 1000000 or (name == 'quantity' and (not value.is_integer() or not 1 <= value <= 100)):
                        continue
                    if name in rejected[i]:
                        continue
                    if name in item['values']:
                        item['values'].pop(name, None)
                        item['value_words'].pop(name, None)
                        item['field_evidence'].pop(name, None)
                        rejected[i].add(name)
                        continue
                    item['values'][name] = value
                    item['value_words'][name] = evidence
                    item['field_evidence'][name] = {'printed_label':label,'printed_value':printed,
                        'unit':unit,'basis':'DRAWING_DESIGN','page':page_number,
                        'box':[min(w[0] for w in cell),min(w[1] for w in cell),max(w[2] for w in cell),max(w[3] for w in cell)]}
                elif label in {'MANUFACTURER', 'MODEL NUMBER'} and len(printed) <= 120:
                    name = {'MANUFACTURER':'manufacturer','MODEL NUMBER':'model'}[label]
                    item['text'][name] = printed.upper()
                    item['text_words'][name] = evidence
        for item in parsed:
            if not item['values']:
                continue
            if 'FURNACE' in item['evidence'].upper():
                item['text']['unit_type'] = 'FURNACE'
                item['text_words']['unit_type'] = item['identity_words']
            result.append(item)
    return result
