"""Locate printed airflow examples inside a native PDF symbol schedule."""
import re
from collections import defaultdict


def symbol_examples(words):
    if len(words) > 30000 or not any(w[4].upper() in ('SYMBOL', 'SYMBOLS') for w in words):
        return []
    blocks = defaultdict(list)
    labels = defaultdict(list)
    for w in words:
        if len(w) >= 8:
            blocks[w[5]].append(w)
            labels[w[4].upper()].append(w)
    headings = []
    descriptions = []
    for block in blocks.values():
        if len(block) > 140:
            continue
        ordered = sorted(block, key=lambda w: (w[6], w[7]))
        text = ' '.join(w[4].upper() for w in ordered)
        if re.fullmatch(r'(?:\d+ )?(?:(?:HVAC|MECHANICAL) )?SYMBOLS? (?:SCHEDULE|LEGEND)', text):
            headings.append((min(w[0] for w in block), max(w[3] for w in block)))
        elif 'BALANCE TO' in text and re.search(r'\b(?:DIFFUSER|REGISTER|GRILLE)\b', text):
            types = re.findall(r'\bTYPE\s+["“]?([A-Z][A-Z0-9-]{0,6})["”]?(?=[\s,.]|$)', text)
            flows = re.findall(r'\bBALANCE TO ([\d,]+) CFM\b', text)
            if len(types) == len(flows) == 1 and re.fullmatch(r'\d{1,4}|\d{1,2},\d{3}', flows[0]):
                descriptions.append((types[0], int(flows[0].replace(',', '')), block))
    if not headings or len(headings) > 16 or len(descriptions) > 64:
        return []
    examples = []
    for mark, flow, block in descriptions:
        # CAD exporters can place the sample glyph in the prose block too.
        # Measure the description using its words, excluding standalone marks and numbers.
        prose = [w for w in block if len(w[4])>2 and re.search('[a-zA-Z]', w[4])]
        left = min(w[0] for w in prose)
        top = min(w[1] for w in prose)
        bottom = max(w[3] for w in prose)
        h = max(w[3] - w[1] for w in prose)
        if not any(0 <= top-y <= 60*h and -2*h <= left-x <= 24*h for x,y in headings):
            continue
        marks = [w for w in labels[mark] if 0 < left-w[2] <= 15*h and top <= w[1] <= bottom]
        if len(marks) != 1:
            continue
        label = marks[0]
        numbers = labels[str(flow)] + (labels[f'{flow:,}'] if flow >= 1000 else [])
        matches = [w for w in numbers if abs((w[0]+w[2]-label[0]-label[2])/2) <= .5*h
                   and 0 <= w[1]-label[3] <= 2*h]
        if len(matches) == 1:
            n = matches[0]
            examples.append((mark, flow, (min(label[0],n[0])-2, label[1]-2,
                                          max(label[2],n[2])+2, n[3]+2)))
    if examples:
        from abp_grille_service import exhaust_sample
        sample = exhaust_sample(words)
        if sample:
            mark, number = sample
            examples.append((mark[4], int(number[4]),
                             (min(mark[0],number[0])-2, mark[1]-2, max(mark[2],number[2])+2, number[3]+2)))
    return examples


def is_symbol_example(candidate, examples):
    pos = candidate.get('position')
    if not examples or not pos or len(pos) != 2:
        return False
    actual_flow = candidate.get('design_cfm', candidate.get('review_values', {}).get('design_cfm'))
    return any(candidate.get('type') == mark and actual_flow == flow and
               x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1
               for mark, flow, (x0,y0,x1,y1) in examples)
