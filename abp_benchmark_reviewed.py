"""Independent acceptance of a reviewed inventory, separate from raw extraction.

This evaluator imports no scanner, review gate or workbook writer. It compares
the website export against frozen source answers. It never edits either export.
"""
import math,re
from abp_benchmark import same,page,same_annotation


# Independent copy of the report-input approval contract. Deliberately do not
# call the application's approval function while auditing that same function.
RECORD_INPUTS=('tag status template coil_template source reference instance_locations quantity design_cfm osa_cfm osa_min_cfm esp total_sp motor_hp motor_volts motor_phase motor_fla motor_rpm design_gpm cooling_edb cooling_ewb cooling_ldb cooling_lwb heating_cfm heating_edb heating_ldb heating_input_btu heating_output_btu cooling_total_btu cooling_sensible_btu electric_heating_edb electric_heating_ldb heater_volts heater_phase heater_amps heater_stages heater_kw heating_ewt heating_lwt water_dp_ft manufacturer model unit_type service equipment_location area_served heating_type').split()
OUTLET_INPUTS='include type size system location design_cfm source reference position quantity quantity_unresolved quantity_candidates exclusion_note repeat_resolution repeat_instance manual_locator'.split()


def same_reviewed(actual,expected):
    """HTML number inputs are exported as strings; raw scans remain strict.

    Accept a finite decimal representation only when the independent expected
    value is numeric. Never coerce blanks, booleans, units or identifiers.
    """
    if type(expected) in (int,float) and isinstance(actual,str):
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',actual.strip()):return False
        try:actual=float(actual)
        except (ValueError,OverflowError):return False
    return same(actual,expected)


def approved_inventory_matches(review,approval):
    def inputs(rows,keys):return [{k:r[k] for k in keys if k in r} for r in rows]
    expected={'project':review.get('project',''),'location':review.get('location',''),
        'templates':review.get('templates',[]),'standard':review.get('standard','Commercial'),
        'records':inputs(review.get('records',[]),RECORD_INPUTS),
        'diffusers':inputs(review.get('diffusers',[]),OUTLET_INPUTS),
        'image_decisions':[{'accepted':r.get('accepted',False),'excluded':r.get('excluded',False),
            'exclusion_note':r.get('exclusion_note',''),'tag':r.get('tag',''),'source':r.get('source',''),
            'page':r.get('page'),'position':r.get('position')} for r in review.get('image_review',[])]}
    return approval.get('inventory')==expected


def evaluate_reviewed(project,review):
    errors=[];matches=[]
    def error(code,**extra):errors.append({'code':code,**extra})
    state=review.get('scan_state',{});sources={s['name']:s['sha256'] for s in project['sources']}
    checkpoints=state.get('source_checkpoints',[])
    if len(checkpoints)!=len(sources) or {s['name']:s.get('sha256') for s in checkpoints}!=sources:error('source_identity_mismatch')
    if state.get('complete_takeoff') is not False:error('automatic_coverage_was_upgraded')
    known=project['expected'];actual=[d for d in review.get('diffusers',[]) if d.get('include') is True];used=set()
    for expected in known.get('outlets',[]):
        choices=[i for i,item in enumerate(actual) if item.get('source')==expected['source'] and page(item)==expected['page']
            and same_annotation(item,expected)
            and (expected.get('instance_locator') is None or item.get('repeat_instance',{}).get('locator')==expected['instance_locator'])]
        if len(choices)!=1:error('missing_or_duplicate_reviewed_outlet',id=expected['id'],count=len(choices));continue
        index=choices[0]
        if index in used:error('shared_physical_outlet',id=expected['id']);continue
        used.add(index);item=actual[index];matches.append(expected['id'])
        for key,value in {**expected['values'],**expected.get('review_fields',{})}.items():
            if not same_reviewed(item.get(key),value):error('wrong_reviewed_outlet_field',id=expected['id'],field=key,expected=value,actual=item.get(key))
        for key in expected.get('must_withhold',[]):
            if item.get(key) not in (None,''):error('unsupported_reviewed_outlet_field',id=expected['id'],field=key)
    for index in set(range(len(actual)))-used:error('unexpected_reviewed_outlet',index=index)
    records=[r for r in review.get('records',[]) if r.get('status')=='VERIFIED'];used_records=set()
    for expected in known.get('equipment',[]):
        choices=[(i,r) for i,r in enumerate(records) if r.get('tag')==expected['tag']]
        if len(choices)!=1:error('missing_or_duplicate_reviewed_equipment',tag=expected['tag'],count=len(choices));continue
        index,record=choices[0];used_records.add(index)
        for key,value in expected.get('reviewed_values',expected.get('values',{})).items():
            if not same_reviewed(record.get(key),value):error('wrong_reviewed_equipment_field',tag=expected['tag'],field=key,expected=value,actual=record.get(key))
        quantity=expected.get('quantity',1)
        if not same_reviewed(record.get('quantity') or 1,quantity):error('wrong_physical_quantity',tag=expected['tag'],expected=quantity,actual=record.get('quantity'))
        if 'instance_locations' in expected and sorted(record.get('instance_locations',[]))!=sorted(expected['instance_locations']):error('wrong_physical_locations',tag=expected['tag'])
        for key in expected.get('must_withhold',[]):
            if record.get(key) not in (None,''):error('unsupported_reviewed_equipment_field',tag=expected['tag'],field=key)
    for index in set(range(len(records)))-used_records:error('unexpected_reviewed_equipment',tag=records[index].get('tag'))
    if any(r.get('status') not in ('VERIFIED','EXCLUDED') for r in review.get('records',[])):error('unresolved_equipment')
    for candidate in review.get('image_review',[]):
        if candidate.get('accepted') is not True and not (candidate.get('excluded') is True and len(str(candidate.get('exclusion_note','')).strip())>=10):error('unresolved_image_candidate')
    approval=review.get('source_review') or {}
    if (approval.get('version')!=1 or approval.get('approved') is not True or approval.get('scan_state')!=state
            or not approved_inventory_matches(review,approval)):error('human_source_approval_missing_or_stale')
    if state.get('status') not in ('incomplete','review_required'):error('invalid_source_scan_status')
    if not isinstance(approval.get('note'),str) or not 20<=len(approval['note'].strip())<=1000:error('human_review_basis_missing')
    reviewed_pages=approval.get('pages',[])
    expected_pages={(c['name'],c.get('sha256'),p) for c in checkpoints for p in range(1,c.get('pages',0)+1)}
    actual_pages={(p.get('source'),p.get('sha256'),p.get('page')) for p in reviewed_pages}
    if not expected_pages or actual_pages!=expected_pages or len(actual_pages)!=len(reviewed_pages):error('human_page_coverage_incomplete')
    if any(p.get('disposition') not in ('reviewed','not_applicable') or len(str(p.get('note','')).strip())<10 for p in reviewed_pages):error('human_page_decision_missing')
    truth_complete=project.get('truth_status')=='complete' and known.get('outlet_inventory_complete') is True and known.get('equipment_inventory_complete') is True
    if not truth_complete or project.get('unresolved_source_questions'):error('independent_source_truth_incomplete')
    return {'reviewed_inventory_pass':not errors,'errors':errors,'matched_outlets':len(matches),
            'included_outlets':len(actual),'verified_equipment_records':len(records),
            'physical_equipment_count':sum(int(r.get('quantity') or 1) for r in records),
            'manual_assignment_events':sum(len(r.get('review_history',[])) for r in actual),
            'scope':'Reviewed source inventory only. Raw extraction scores and exact website workbook audit remain separate.'}
