"""Source-reviewed test forms for a component inside a packaged air unit.

Component labels are derived display labels, never new printed equipment IDs.
Only explicitly supported exhaust and supply-motor roles are accepted. Values are
reviewed independently: parent airflow and motor ratings are never inherited.
"""
import re

COMPONENT_FIELDS=('component_of','component_kind','component_source_sha256','component_note','component_index','component_count')
MOTOR_FIELDS=('motor_hp','motor_volts','motor_phase','motor_fla','motor_rpm')
PARENT_TAG=re.compile(r'(?:RTU|AHU|MAU|MUA|DOAS|PKU|HP|AC|FCU|BCU)-[A-Z0-9]+(?:[.-][A-Z0-9]+)*$')
COMPONENT_FORM='Exhaust Fans _Std._.xlsx'


def is_component(record):
    return any(key in record for key in COMPONENT_FIELDS)


def fan_count(value):
    if type(value) is int and 2<=value<=20:return value
    if isinstance(value,str) and re.fullmatch(r'(?:[2-9]|1\d|20)',value.strip()):return int(value)
    return None


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
        if record.get('supply_fan_count') not in (None,''):errors.append('Only the parent air unit can declare a supply fan count')
        parent=record.get('component_of')
        if not isinstance(parent,str) or len(parent)>70 or not PARENT_TAG.fullmatch(parent):
            errors.append('Choose the printed ID of the parent air unit');continue
        supply=record.get('component_kind')=='integral_supply'
        index=record.get('component_index');count=record.get('component_count')
        if supply:
            if type(index) is not int or type(count) is not int or fan_count(count) is None or not 1<=index<=count:
                errors.append('Supply fan forms need a source-confirmed count from 2 to 20 and a distinct index')
            if record.get('tag')!=parent+' SUPPLY FAN '+str(index):errors.append('Supply fan labels must be derived from their parent and index')
            from abp_job import NUMERIC_FIELDS
            if any(record.get(k) not in (None,'') for k in NUMERIC_FIELDS if k not in ('quantity',*MOTOR_FIELDS)):
                errors.append('Internal supply motor forms cannot copy or divide whole-unit airflow, pressure or coil data')
        elif record.get('component_kind')!='integral_exhaust' or record.get('tag')!=parent+' EXHAUST' or any(k in record for k in ('component_index','component_count')):
            errors.append('Integral exhaust labels must be derived from their parent unit')
        identity=(parent,'supply' if supply else 'exhaust',str(index) if supply else '')
        if identity in seen:errors.append('Duplicate component role or supply fan index')
        seen.add(identity)
        parents=[r for r in records if r.get('tag')==parent]
        if (len(parents)!=1 or is_component(parents[0]) or parents[0].get('template')!='Air Moving Equipment.xlsx'
                or isinstance(parents[0].get('quantity'),bool) or parents[0].get('quantity') not in (None,'',1,'1')):
            errors.append('An integral exhaust component needs one unambiguous parent air unit')
        elif require_verified and record.get('status')!='EXCLUDED' and parents[0].get('status')!='VERIFIED':
            errors.append('Verify the parent air unit before its integral exhaust component')
        form='Air Moving Equipment.xlsx' if supply else COMPONENT_FORM
        if (record.get('template')!=form or (record.get('coil_template')!='' if supply else record.get('coil_template') not in (None,''))
                or isinstance(record.get('quantity'),bool) or record.get('quantity') not in (None,'',1,'1') or record.get('instance_locations') not in (None,[])):
            errors.append('Use one applicable original form without a companion coil for each linked component')
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
                errors.append(('Supply fan' if supply else 'Integral exhaust')+' source changed or is missing; review it against the current source')
    # The parent's declared fan count remains a witness even if all children
    # disappear during restore/retry. Missing groups cannot silently become complete.
    parents={r.get('tag'):r for r in records if not is_component(r) and isinstance(r.get('tag'),str)}
    groups={}
    for record in records:
        if record.get('component_kind')=='integral_supply':groups.setdefault(str(record.get('component_of')),[]).append(record)
    for parent in parents.values():
        if parent.get('supply_fan_count') not in (None,''):groups.setdefault(str(parent.get('tag')),[])
    for tag,children in groups.items():
        parent=parents.get(tag);count=fan_count(parent.get('supply_fan_count')) if parent else None
        if not parent or parent.get('template')!='Air Moving Equipment.xlsx' or count is None:
            errors.append('Record the source-confirmed supply fan count on one parent air unit');continue
        indices=[r.get('component_index') for r in children]
        if len(children)!=count or set(str(i) for i in indices)!={str(i) for i in range(1,count+1)} or any(r.get('component_count')!=count for r in children):
            errors.append('Supply fan motor forms are missing or duplicated; account for every declared fan')
        identities={(str(r.get('source')),str(r.get('reference')),str(r.get('component_source_sha256'))) for r in children}
        if len(identities)!=1:errors.append('Each supply fan group must retain the same original count source')
        if any(parent.get(k) not in (None,'') for k in MOTOR_FIELDS):errors.append('Put each motor rating on its own supply fan form; the parent has multiple motors')
        if require_verified:
            expected_status='EXCLUDED' if parent.get('status')=='EXCLUDED' else 'VERIFIED'
            if any(r.get('status')!=expected_status for r in children):errors.append('Verify every supply fan motor form or exclude its parent and the entire fan group')
    component_tags={r.get('tag') for r in records if is_component(r) and isinstance(r.get('tag'),str)}
    outlets=payload.get('diffusers',[])
    if isinstance(outlets,list) and any(isinstance(o,dict) and o.get('include') is True and isinstance(o.get('system'),str) and o['system'] in component_tags for o in outlets):
        errors.append('Assign supply outlets to the parent air unit, not its internal motor-test forms')
    return list(dict.fromkeys(errors))
