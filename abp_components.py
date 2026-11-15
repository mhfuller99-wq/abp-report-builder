"""Source-reviewed test forms for a component inside a packaged air unit.

Component labels are derived display labels, never new printed equipment IDs.
Only the explicitly supported integral exhaust role is accepted. Values are
reviewed independently: parent airflow and motor ratings are never inherited.
"""
import re

COMPONENT_FIELDS=('component_of','component_kind','component_source_sha256','component_note')
PARENT_TAG=re.compile(r'(?:RTU|AHU|MAU|MUA|DOAS|PKU|HP|AC|FCU|BCU)-[A-Z0-9]+(?:[.-][A-Z0-9]+)*$')
COMPONENT_FORM='Exhaust Fans _Std._.xlsx'


def is_component(record):
    return any(key in record for key in COMPONENT_FIELDS)


def component_errors(payload, *, require_verified=True, check_sources=True):
    records=payload.get('records',[])
    if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):
        return ['Invalid equipment component inventory']
    state=payload.get('scan_state') or {}
    checkpoints=state.get('source_checkpoints',[]) if isinstance(state,dict) else []
    if not isinstance(checkpoints,list):checkpoints=[]
    errors=[];seen=set()
    for record in records:
        if not is_component(record):continue
        parent=record.get('component_of')
        if not isinstance(parent,str) or len(parent)>70 or not PARENT_TAG.fullmatch(parent):
            errors.append('Choose the printed ID of the parent air unit');continue
        if record.get('component_kind')!='integral_exhaust' or record.get('tag')!=parent+' EXHAUST':
            errors.append('Integral exhaust labels must be derived from their parent unit')
        if parent in seen:errors.append('Only one integral exhaust review is allowed per parent unit')
        seen.add(parent)
        parents=[r for r in records if r.get('tag')==parent]
        if (len(parents)!=1 or is_component(parents[0]) or parents[0].get('template')!='Air Moving Equipment.xlsx'
                or isinstance(parents[0].get('quantity'),bool) or parents[0].get('quantity') not in (None,'',1,'1')):
            errors.append('An integral exhaust component needs one unambiguous parent air unit')
        elif require_verified and record.get('status')!='EXCLUDED' and parents[0].get('status')!='VERIFIED':
            errors.append('Verify the parent air unit before its integral exhaust component')
        if (record.get('template')!=COMPONENT_FORM or record.get('coil_template') not in (None,'')
                or isinstance(record.get('quantity'),bool) or record.get('quantity') not in (None,'',1,'1') or record.get('instance_locations') not in (None,[])):
            errors.append('Use one original standard exhaust form for the linked component')
        if record.get('status') not in ('UNVERIFIED','VERIFIED','EXCLUDED'):
            errors.append('Invalid equipment component review status')
        if require_verified and record.get('status') not in ('VERIFIED','EXCLUDED'):
            errors.append('Verify or exclude every integral exhaust component')
        note=record.get('component_note')
        if not isinstance(note,str) or not 20<=len(note.strip())<=500:
            errors.append('Record 20–500 characters of source evidence for the integral exhaust component')
        source=record.get('source');reference=record.get('reference');digest=record.get('component_source_sha256')
        match=re.fullmatch(r'page ([1-9]\d{0,2})',reference) if isinstance(reference,str) else None
        if (not isinstance(source,str) or not 1<=len(source)<=160 or not match
                or not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest)):
            errors.append('Integral exhaust components need their original source hash and page');continue
        if check_sources:
            sources=[s for s in checkpoints if isinstance(s,dict) and s.get('name')==source and s.get('sha256')==digest]
            if len(sources)!=1 or type(sources[0].get('pages'))!=int or int(match[1])>sources[0]['pages']:
                errors.append('Integral exhaust source changed or is missing; review it against the current source')
    return list(dict.fromkeys(errors))
