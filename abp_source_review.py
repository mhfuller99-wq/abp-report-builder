"""Human source review is distinct from automatic scan coverage.

A partial-scan acknowledgment never satisfies this contract. Approval requires
page accounting and a resolved inventory and is invalidated by any source,
inventory, template or project change. It does not certify field measurements.
"""
import copy
from abp_job import NUMERIC_FIELDS,TEXT_FIELDS
from abp_outlet_instances import outlet_instance_errors


def inventory_snapshot(payload):
    record_keys=('tag','status','template','coil_template','source','reference','instance_locations',*NUMERIC_FIELDS,*TEXT_FIELDS)
    outlet_keys=('include','type','size','system','location','design_cfm','source','reference','position','quantity','quantity_unresolved','quantity_candidates','exclusion_note','repeat_resolution','repeat_instance')
    def project(rows,keys):return [{k:r[k] for k in keys if k in r} for r in rows]
    return copy.deepcopy({'project':payload.get('project',''),'location':payload.get('location',''),
        'templates':payload.get('templates',[]),'standard':payload.get('standard','Commercial'),
        'records':project(payload.get('records',[]),record_keys),
        'diffusers':project(payload.get('diffusers',[]),outlet_keys),
        'image_decisions':[{'accepted':r.get('accepted',False),'excluded':r.get('excluded',False),
            'exclusion_note':r.get('exclusion_note',''),'tag':r.get('tag',''),'source':r.get('source',''),
            'page':r.get('page'),'position':r.get('position')} for r in payload.get('image_review',[])]})


def source_review_errors(payload):
    state=payload.get('scan_state') or {};review=payload.get('source_review')
    if not isinstance(review,dict):return ['Human source review has not been approved']
    if not isinstance(state,dict) or any(not isinstance(payload.get(key,[]),list) or
            any(not isinstance(row,dict) for row in payload.get(key,[])) for key in ('records','diffusers','image_review')):
        return ['Invalid source review inventory']
    if not isinstance(state.get('source_checkpoints',[]),list) or any(not isinstance(c,dict) for c in state.get('source_checkpoints',[])):
        return ['Invalid source checkpoints']
    errors=[]
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
            errors.append('Every included supply outlet must belong to a verified supply unit in this inventory')
        if outlet.get('quantity_unresolved') or outlet.get('quantity',1)!=1:errors.append('Resolve repeated outlet quantities into physical rows before approval')
        if not all(outlet.get(k) not in (None,'') for k in ('source','reference','type','system','location','design_cfm')):
            errors.append('Included outlets need source, type, system, location and design CFM; document deliberate neck-size blanks in the review basis')
    return list(dict.fromkeys(errors))


def source_review_approved(payload):
    return not source_review_errors(payload)
