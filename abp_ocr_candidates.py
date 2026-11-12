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
            ('type', 'size', 'shape', 'type_confidence', 'position', 'region',
             'review_values', 'values', 'design_cfm', 'evidence_text')
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
    _withhold_native_conflicts(old)
    return True


def _withhold_native_conflicts(candidate):
    """Later OCR repeats cannot undo a prior native/image disagreement."""
    fields=candidate.get('native_conflict_fields', [])
    if not isinstance(fields,list):return
    for field in ('design_cfm','size','type'):
        if field not in fields:continue
        for key in ('review_values','values'):
            if isinstance(candidate.get(key),dict):candidate[key].pop(field,None)
        if field in ('size','type'):candidate[field]=''
        elif field in candidate:candidate[field]=None
    if 'type' in fields:
        candidate['type_conflict_unresolved']=True
        candidate['type_confidence']=None


def _source_page(candidate):
    source=candidate.get('source')
    if not isinstance(source,str) or not source or len(source)>1024:return None
    page=candidate.get('page')
    reference=candidate.get('reference')
    match=re.fullmatch(r'page\s+([1-9]\d*)',reference.strip(),re.I) if isinstance(reference,str) else None
    referenced=int(match[1]) if match else None
    if page is not None:
        if type(page) is not int or page<1:return None
        if referenced is not None and page!=referenced:return None
    else:page=referenced
    return (source,page) if page is not None else None


def _position_space(candidate):
    fields=('position_coordinate_space','coordinate_space','region_coordinate_space')
    spaces=[candidate[key] for key in fields if candidate.get(key) is not None]
    allowed={'displayed_pdf_points','unrotated_pdf_points'}
    if spaces:
        if any(not isinstance(value,str) or value not in allowed for value in spaces):return None
        if len(set(spaces))!=1:return None
        return spaces[0]
    # At zero rotation displayed/unrotated PDF coordinates coincide. Legacy
    # records without either explicit space or rotation have unknown geometry.
    rotation=candidate.get('page_rotation')
    return 'displayed_pdf_points' if type(rotation) is int and rotation==0 else None


def _reconciliation_position(candidate):
    point=_position(candidate)
    # Scan coordinates are displayed, nonnegative PDF points. Extreme finite
    # values from malformed saved records cannot establish a physical match.
    return point if point is not None and all(0<=value<=1_000_000 for value in point) else None


def _numeric_reading(value):
    if isinstance(value,bool):return None
    if isinstance(value,str):
        if not re.fullmatch(r'\d+(?:\.\d+)?',value.strip()):return None
        value=float(value)
    if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=10000:return None
    return float(value)


def _text_reading(value):
    # Casing and whitespace are presentation differences, not evidence that a
    # missing digit or reversed dimensions can be repaired.
    return ''.join(value.upper().split()) if isinstance(value,str) and value.strip() else None


def reconcile_diffuser_sources(native_outlets,image_candidates,*,tolerance=6):
    """Flag native/image duplicates and withhold conflicting raw OCR fields.

    Native rows are never mutated, and matching native values never fill an
    image blank. Only unique same-source/page positions in a confirmed common
    coordinate space qualify. The returned list is the input image list; no
    observations are removed or merged into native rows. Accepted/verified
    user choices are untouched. Call on raw scan results before UI acceptance.
    """
    if (not isinstance(native_outlets,list) or not isinstance(image_candidates,list)
            or len(native_outlets)>500 or len(image_candidates)>500):
        raise ValueError('Native/image reconciliation requires at most 500 candidates per queue')
    if (isinstance(tolerance,bool) or not isinstance(tolerance,(int,float))
            or not math.isfinite(tolerance) or not 0<tolerance<=6):
        raise ValueError('Native/image tolerance must be positive and no greater than six PDF points')
    groups={}
    for native in native_outlets:
        if not isinstance(native,dict):continue
        key=_source_page(native)
        if key is not None:groups.setdefault(key,[]).append(native)

    def reason(candidate,text):
        reasons=candidate.setdefault('review_reasons',[])
        if not isinstance(reasons,list):return
        text=text[:1000]
        if text not in reasons:
            if len(reasons)<20:reasons.append(text)
            else:candidate['native_reconciliation_log_truncated']=True

    def alternatives(candidate,field,values):
        conflicts=candidate.setdefault('field_conflicts',{})
        if not isinstance(conflicts,dict):return
        readings=conflicts.setdefault(field,[])
        if not isinstance(readings,list):return
        for value in values:
            if value not in readings:
                if len(readings)<32:readings.append(copy.deepcopy(value))
                else:candidate['native_reconciliation_log_truncated']=True

    def raw_values(candidate,field):
        found=[]
        for key in ('review_values','values'):
            values=candidate.get(key)
            if isinstance(values,dict) and field in values:found.append(values[field])
        if field in candidate:found.append(candidate[field])
        return found

    for candidate in image_candidates:
        if (not isinstance(candidate,dict) or candidate.get('kind')!='diffuser'
                or candidate.get('include') or candidate.get('accepted')
                or candidate.get('status','UNVERIFIED')!='UNVERIFIED'):continue
        # Persisted disagreements remain unresolved even if a later retry no
        # longer contains the native witness. Retain new raw alternatives,
        # then reapply the guard; never revive a previously withheld value.
        previous=candidate.get('native_conflict_fields',[])
        if isinstance(previous,list):
            for field in ('design_cfm','size','type'):
                if field not in previous:continue
                normalize=_numeric_reading if field=='design_cfm' else _text_reading
                for value in raw_values(candidate,field):
                    if normalize(value) is None:continue
                    _remember(candidate,candidate)
                    alternatives(candidate,field,[value])
            _withhold_native_conflicts(candidate)
        point=_reconciliation_position(candidate);key=_source_page(candidate);space=_position_space(candidate)
        if point is None or key is None:continue
        nearby=groups.get(key,[])
        if not nearby:continue
        if space is None:
            candidate['native_reconciliation_unavailable']=True
            reason(candidate,'Native/image position comparison is unavailable because the saved coordinate space is unknown. Compare the original source before adding another outlet.')
            continue
        matches=[]
        for native in nearby:
            other=_reconciliation_position(native)
            if other is None or _position_space(native)!=space:continue
            native_rotation,image_rotation=native.get('page_rotation'),candidate.get('page_rotation')
            if (native_rotation is not None and image_rotation is not None
                    and native_rotation!=image_rotation):continue
            if math.dist(point,other)<=tolerance:matches.append(native)
        if not matches:continue
        candidate['status']='UNVERIFIED';candidate['include']=False
        candidate['system']='';candidate['location']=''
        if len(matches)>1:
            candidate['native_outlet_ambiguous']=True
            candidate.pop('native_outlet_match',None)
            reason(candidate,'Image position overlaps multiple native outlet candidates. No outlet was selected as the match; compare distinct physical locations before adding or including anything.')
            continue
        native=matches[0]
        candidate['native_outlet_match']=True
        reason(candidate,'Native text already contains an outlet at this source/page position. Review the existing native outlet instead of adding this image reading as another device; compare all alternative evidence with the source.')
        # Capture the raw image before blanks are imposed, once. Reconciliation
        # can safely run again after serialization without adding blank readings.
        if not candidate.get('native_reconciled'):_remember(candidate,candidate)
        snapshot={'source':key[0],'page':key[1],'position':list(native['position']),
                  'type':native.get('type'),'size':native.get('size'),
                  'design_cfm':native.get('design_cfm'),
                  'evidence_text':str(native.get('evidence',''))[:1000]}
        observations=candidate.setdefault('native_readings',[])
        if isinstance(observations,list) and snapshot not in observations:
            if len(observations)<8:observations.append(snapshot)
            else:candidate['native_reconciliation_log_truncated']=True
        fields=candidate.setdefault('native_conflict_fields',[])
        if not isinstance(fields,list):continue
        for field in ('design_cfm','size','type'):
            normalize=_numeric_reading if field=='design_cfm' else _text_reading
            native_value=native.get(field);normalized=normalize(native_value)
            if normalized is None:continue
            for image_value in raw_values(candidate,field):
                image_normalized=normalize(image_value)
                if image_normalized is None or image_normalized==normalized:continue
                alternatives(candidate,field,[image_value,native_value])
                if field not in fields:fields.append(field)
                label={'design_cfm':'design CFM','size':'register size','type':'outlet type'}[field]
                reason(candidate,f'Image {label}: {image_value}; native text: {native_value}. The conflicting image field is blank. Compare the original source; neither reading was automatically accepted.')
        fields.sort()
        _withhold_native_conflicts(candidate)
        candidate['native_reconciled']=True
    return image_candidates
