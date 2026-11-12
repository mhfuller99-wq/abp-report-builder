"""Merge repeat OCR observations without inventing a resolved outlet reading.

This module operates on the unverified image-review queue only. A physical
position, not matching airflow or a shared OCR crop, identifies a repeat.
"""
import copy
import math
import re


def _position(candidate):
    point = candidate.get('position')
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
        return None
    return point


def _printed(candidate):
    # Parser explanations follow a semicolon. Do not repair OCR characters,
    # remove digits, or treat two different printed flows as corroboration.
    text = candidate.get('evidence_text', '')
    return ' '.join(str(text).split(';', 1)[0].upper().split())


def _reason(candidate, text):
    reasons = candidate.setdefault('review_reasons', [])
    if text not in reasons:
        reasons.append(text)


def _reading(candidate):
    result = {key: copy.deepcopy(candidate[key]) for key in
            ('type', 'type_confidence', 'position', 'region', 'review_values', 'evidence_text')
            if key in candidate}
    if 'type_confidence' in result:
        result['type_confidence'] = _confidence(candidate)
    return result


def _remember(existing, incoming):
    readings = existing.setdefault('ocr_readings', [_reading(existing)])
    observation = _reading(incoming)
    if observation not in readings:
        # Production OCR has a smaller per-page region cap. Keep this helper
        # bounded even if another caller supplies an excessive number of reads.
        if len(readings) < 32:
            readings.append(observation)
        else:
            existing['ocr_readings_truncated'] = True
            _reason(existing, 'Additional OCR readings were omitted from the review log; inspect the source.')


def _confidence(reading):
    value = reading.get('type_confidence')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if 0 <= value <= 100 else None


def _flow_text(candidate):
    """A literal final airflow line; never repair uncertain characters."""
    parts = _printed(candidate).split('/')
    if len(parts) < 2:
        return ''
    flow = parts[-1].strip()
    return flow if re.fullmatch(r'(?:\d{2,4}|\d{1,2},\d{3})\s*(?:CFM)?', flow) else ''


def _merge_type(old, incoming):
    first = str(old.get('type', '')).strip().upper()
    second = str(incoming.get('type', '')).strip().upper()
    if first == second and not old.get('type_conflicts'):
        confidence = _confidence(incoming)
        if confidence is not None and confidence > (_confidence(old) or 0):
            old['type_confidence'] = confidence
        return
    types = old.setdefault('type_conflicts', [])
    for value in (first, second):
        if value and value not in types:
            if len(types) < 32:
                types.append(value)
            else:
                old['type_conflict_unresolved'] = True
                old['ocr_readings_truncated'] = True
    readings = old.get('ocr_readings', [])
    strong = {str(r.get('type', '')).strip().upper() for r in readings
              if r.get('type') and _confidence(r) is not None and _confidence(r) >= 80}
    unknown = {str(r.get('type', '')).strip().upper() for r in readings
               if r.get('type') and _confidence(r) is None}
    # Unknown confidence is not evidence that an alternative is weaker. Once
    # strong/strong or unscored disagreement exists, later repeats cannot settle it.
    if (len(strong) == 1 and not (unknown - strong)
            and not old.get('type_conflict_unresolved') and not old.get('ocr_readings_truncated')):
        selected = next(iter(strong))
        witness = max((r for r in readings if str(r.get('type', '')).strip().upper() == selected),
                      key=lambda r: _confidence(r) if _confidence(r) is not None else -1)
        old['type'] = selected
        old['type_confidence'] = _confidence(witness)
        if first != selected and witness.get('evidence_text'):
            old['evidence_text'] = witness['evidence_text']
    else:
        old['type'] = ''
        old['type_confidence'] = None
        old['type_conflict_unresolved'] = True
    _reason(old, 'Different OCR types were read at this physical outlet; alternatives are retained. Confirm the printed type before including. Unresolved type conflicts are blank.')


def merge_diffuser_candidate(existing, incoming, *, tolerance=6):
    """Return True when an unverified repeat was merged; otherwise append it.

    Same-position type conflicts remain one explicitly flagged physical candidate.
    A strong type may supersede a weak reading; equally strong or unscored
    disagreements leave the type blank until a person resolves it.
    Numeric conflicts are retained in ``field_conflicts`` and removed from the
    proposed review fields. A later matching read cannot erase that conflict.
    Blank-to-valued upgrades require matching literal field evidence. Nothing here
    verifies an outlet, selects it, assigns its room/system, or changes a report.
    """
    point = _position(incoming)
    if incoming.get('kind') != 'diffuser' or point is None:
        return False
    if incoming.get('include') or incoming.get('status', 'UNVERIFIED') != 'UNVERIFIED':
        return False
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or not 0 < tolerance <= 6:
        raise ValueError('OCR duplicate tolerance must be positive and no greater than six PDF points')
    matches = []
    for old in existing:
        other = _position(old)
        if (old.get('kind') != 'diffuser' or other is None or old.get('include')
                or old.get('status', 'UNVERIFIED') != 'UNVERIFIED'
                or old.get('source') != incoming.get('source')
                or old.get('page') != incoming.get('page')
                or math.dist(point, other) >= tolerance):
            continue
        matches.append(old)
    # Ambiguous adjacency must not make one observation overwrite two devices.
    if len(matches) != 1:
        if len(matches) > 1:
            _reason(incoming, 'OCR position overlaps multiple outlet candidates; confirm distinct physical devices before including.')
        return False
    old = matches[0]
    _remember(old, incoming)
    agrees = bool(_printed(old)) and _printed(old) == _printed(incoming)
    flow_agrees = bool(_flow_text(old)) and _flow_text(old) == _flow_text(incoming)
    old_lines, new_lines = _printed(old).split('/'), _printed(incoming).split('/')
    if len(old_lines) > 1 and len(new_lines) > 1 and old_lines[-1].strip() != new_lines[-1].strip():
        old['printed_flow_conflict'] = True
        _reason(old, 'Printed airflow readings disagree; a blank airflow remains blank until source review resolves the alternatives.')
    values = old.setdefault('review_values', {})
    additions = incoming.get('review_values') or {}
    conflicts = old.get('field_conflicts', {})
    for field, value in additions.items():
        if field in conflicts:
            if value not in conflicts[field] and len(conflicts[field]) < 32:
                conflicts[field].append(copy.deepcopy(value))
            values.pop(field, None)
        elif field in values and values[field] != value:
            conflicts[field] = [copy.deepcopy(values.pop(field)), copy.deepcopy(value)]
        elif (field not in values and (agrees or (field == 'design_cfm' and flow_agrees))
              and not (field == 'design_cfm' and old.get('printed_flow_conflict'))):
            values[field] = copy.deepcopy(value)
    if conflicts:
        old['field_conflicts'] = conflicts
        _reason(old, 'OCR readings disagree on numeric values at this outlet; conflicting fields are blank and alternative readings are retained for source review.')
    if not agrees:
        old['printed_evidence_conflict'] = True
        _reason(old, 'OCR readings at this outlet have different printed evidence; a blank airflow is filled only when its literal printed flow agrees. Review the original source.')
    _merge_type(old, incoming)
    if agrees and not old.get('size') and incoming.get('size'):
        old['size'] = incoming['size']
    for reason in incoming.get('review_reasons', []):
        _reason(old, reason)
    return True
