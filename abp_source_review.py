"""Human source review is distinct from automatic scan coverage.

A partial-scan acknowledgment never satisfies this contract. Approval requires
page accounting and a resolved inventory and is invalidated by any source,
inventory, template or project change. It does not certify field measurements.
"""
import copy,re
from abp_job import NUMERIC_FIELDS,TEXT_FIELDS
from abp_outlet_instances import outlet_instance_errors
from abp_components import COMPONENT_FIELDS,component_errors
from abp_exhaust import EXHAUST_FIELDS,exhaust_errors

AIR_PATH_FIELDS=('tag','kind','status','source','source_sha256','reference','location','note')
PASSIVE_TAG=re.compile(r'(?:L|LOUVER|LOUVRE|OA|INTAKE|TRANSFER|PASSIVE)-[A-Z0-9]+(?:[.-][A-Z0-9]+)*$')


def air_path_errors(payload, *, require_verified=True, check_sources=True):
    """Source-bound passive supply connections, never motorized unit records."""
    paths=payload.get('air_paths',[])
    if not isinstance(paths,list) or len(paths)>100:return ['Invalid passive supply paths']
    errors=[];seen=set()
    equipment={str(r.get('tag','')).strip().upper() for r in payload.get('records',[]) if isinstance(r,dict)}
    state=payload.get('scan_state') or {}
    checkpoints=state.get('source_checkpoints',[]) if isinstance(state,dict) else []
    for path in paths:
        if not isinstance(path,dict) or set(path)-set(AIR_PATH_FIELDS):
            errors.append('Invalid passive supply path fields');continue
        tag=path.get('tag')
        if not isinstance(tag,str) or len(tag)>80 or not PASSIVE_TAG.fullmatch(tag):
            errors.append('Use a passive inlet or transfer ID, such as L-1 or PASSIVE-1');continue
        if tag in seen or tag in equipment:errors.append('Passive path IDs must be unique and separate from equipment IDs')
        seen.add(tag)
        if path.get('kind')!='passive_supply' or path.get('status') not in ('UNVERIFIED','VERIFIED'):
            errors.append('Invalid passive supply path kind or status')
        if require_verified and path.get('status')!='VERIFIED':errors.append('Verify every passive supply path from its source')
        for field,minimum,maximum in [('source',1,160),('reference',1,80),('location',1,120),('note',20,500)]:
            value=path.get(field)
            if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum:
                errors.append('Passive paths need a source page, room / area and 20–500 character supply-path evidence')
        digest=path.get('source_sha256');reference=path.get('reference','')
        match=re.fullmatch(r'page ([1-9]\d{0,2})',reference) if isinstance(reference,str) else None
        if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest) or not match:
            errors.append('Invalid passive path source identity');continue
        if check_sources:
            sources=[s for s in checkpoints if isinstance(s,dict) and s.get('name')==path.get('source') and s.get('sha256')==digest]
            if len(sources)!=1 or type(sources[0].get('pages'))!=int or int(match[1])>sources[0]['pages']:
                errors.append('Passive path source changed or is missing; check and add it again from the current source')
    return list(dict.fromkeys(errors))


def inventory_snapshot(payload):
    record_keys=('tag','status','template','coil_template','source','reference','instance_locations',*NUMERIC_FIELDS,*TEXT_FIELDS,*COMPONENT_FIELDS)
    outlet_keys=('include','type','size','system','location','design_cfm','source','reference','position','quantity','quantity_unresolved','quantity_candidates','exclusion_note','repeat_resolution','repeat_instance','manual_locator')
    def project(rows,keys):return [{k:r[k] for k in keys if k in r} for r in rows]
    snapshot={'project':payload.get('project',''),'location':payload.get('location',''),
        'templates':payload.get('templates',[]),'standard':payload.get('standard','Commercial'),
        'records':project(payload.get('records',[]),record_keys),
        'diffusers':project(payload.get('diffusers',[]),outlet_keys),
        'image_decisions':[{'accepted':r.get('accepted',False),'excluded':r.get('excluded',False),
            'exclusion_note':r.get('exclusion_note',''),'tag':r.get('tag',''),'source':r.get('source',''),
            'page':r.get('page'),'position':r.get('position')} for r in payload.get('image_review',[])]}
    if payload.get('air_paths'):snapshot['air_paths']=project(payload['air_paths'],AIR_PATH_FIELDS)
    if payload.get('exhaust_outlets'):snapshot['exhaust_outlets']=project(payload['exhaust_outlets'],EXHAUST_FIELDS)
    return copy.deepcopy(snapshot)


def source_review_errors(payload):
    state=payload.get('scan_state') or {};review=payload.get('source_review')
    if not isinstance(review,dict):return ['Human source review has not been approved']
    if not isinstance(state,dict) or any(not isinstance(payload.get(key,[]),list) or
            any(not isinstance(row,dict) for row in payload.get(key,[])) for key in ('records','diffusers','image_review','air_paths','exhaust_outlets')):
        return ['Invalid source review inventory']
    if not isinstance(state.get('source_checkpoints',[]),list) or any(not isinstance(c,dict) for c in state.get('source_checkpoints',[])):
        return ['Invalid source checkpoints']
    errors=air_path_errors(payload)+component_errors(payload)+exhaust_errors(payload)
    if review.get('version')!=1 or review.get('approved') is not True:errors.append('Human source review has not been approved')
    if state.get('status') not in ('incomplete','review_required') or state.get('complete_takeoff') is not False:
        errors.append('Sources are unscanned, outdated or unknown')
    if review.get('scan_state')!=state:errors.append('Source scan changed after human review')
    if review.get('inventory')!=inventory_snapshot(payload):errors.append('Design inventory changed after human review')
    note=review.get('note')
    if not isinstance(note,str) or not 20<=len(note.strip())<=1000:errors.append('Record the review basis and deliberate blanks (20–1000 characters)')
    checkpoints=state.get('source_checkpoints',[]);pages=review.get('pages',[])
    if not checkpoints or not isinstance(pages,list) or len(pages)>30000:return errors+['Source pages have not been accounted for']
    expected=set()
    for source in checkpoints:
        count=source.get('pages');digest=source.get('sha256')
        if type(count)!=int or not 1<=count<=300 or not isinstance(digest,str) or len(digest)!=64:
            errors.append('Re-upload sources with page counts and content identities');continue
        expected.update((source['name'],digest,p) for p in range(1,count+1))
    actual=set()
    for page in pages:
        if not isinstance(page,dict):errors.append('Invalid human page review');continue
        key=(page.get('source'),page.get('sha256'),page.get('page'))
        if not all(isinstance(x,str) for x in key[:2]) or type(key[2])!=int:
            errors.append('Invalid human page identity');continue
        if key in actual:errors.append('Duplicate human page review')
        actual.add(key)
        if page.get('disposition') not in ('reviewed','not_applicable') or not isinstance(page.get('note'),str) or not 10<=len(page['note'].strip())<=500:
            errors.append('Every page needs a reviewed / not applicable disposition and source note')
    if actual!=expected:errors.append('Every uploaded page must be accounted for against its source hash')
    records=payload.get('records',[]);outlets=payload.get('diffusers',[])
    errors.extend(outlet_instance_errors(outlets))
    supply_units={str(r.get('tag','')).strip().upper() for r in records if r.get('status')=='VERIFIED'
                  and r.get('template') not in ('Exhaust Fans _Sm._.xlsx','Exhaust Fans _Std._.xlsx','Kitchen Hood.xlsx','Chiller - Air Cooled.xlsx','Chiller - Water Cooled.xlsx')}
    supply_units.update(p.get('tag','') for p in payload.get('air_paths',[]) if p.get('status')=='VERIFIED' and p.get('kind')=='passive_supply')
    if any(r.get('status') not in ('VERIFIED','EXCLUDED') for r in records):errors.append('Resolve every equipment review row')
    if any(c.get('accepted') is not True and not (c.get('excluded') is True and isinstance(c.get('exclusion_note'),str) and 10<=len(c['exclusion_note'].strip())<=500) for c in payload.get('image_review',[])):
        errors.append('Resolve every image candidate: add it or exclude it with a reason')
    if not any(r.get('status')=='VERIFIED' for r in records) and not any(o.get('include') is True for o in outlets):errors.append('The reviewed inventory is empty')
    if any(o.get('include') is True for o in outlets) and 'Supply Diffusers.xlsx' not in payload.get('templates',[]):
        errors.append('Include the Supply Diffusers worksheet for the included outlets')
    for outlet in outlets:
        if outlet.get('include') is not True:
            note=outlet.get('exclusion_note')
            if not isinstance(note,str) or not 10<=len(note.strip())<=500:
                errors.append('Every unchecked outlet needs a source-based exclusion reason; unchecked is not reviewed')
            continue
        if str(outlet.get('system','')).strip().upper() not in supply_units:
            errors.append('Every included supply outlet must belong to verified supply equipment or a source-reviewed passive supply path')
        if outlet.get('quantity_unresolved') or outlet.get('quantity',1)!=1:errors.append('Resolve repeated outlet quantities into physical rows before approval')
        if not all(outlet.get(k) not in (None,'') for k in ('source','reference','type','system','location','design_cfm')):
            errors.append('Included outlets need source, type, system, location and design CFM; document deliberate neck-size blanks in the review basis')
    return list(dict.fromkeys(errors))


def source_review_approved(payload):
    return not source_review_errors(payload)
