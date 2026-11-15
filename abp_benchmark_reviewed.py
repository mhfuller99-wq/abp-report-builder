"""Independent acceptance of a reviewed inventory, separate from raw extraction.

This evaluator imports no scanner, review gate or workbook writer. It compares
the website export against frozen source answers. It never edits either export.
"""
import math,re
from abp_benchmark import same,page,point,same_annotation


# Independent copy of the report-input approval contract. Deliberately do not
# call the application's approval function while auditing that same function.
RECORD_INPUTS=('tag status template coil_template source reference instance_locations quantity design_cfm osa_cfm osa_min_cfm esp total_sp motor_hp motor_volts motor_phase motor_fla motor_rpm design_gpm cooling_edb cooling_ewb cooling_ldb cooling_lwb heating_cfm heating_edb heating_ldb heating_input_btu heating_output_btu cooling_total_btu cooling_sensible_btu electric_heating_edb electric_heating_ldb heater_volts heater_phase heater_amps heater_stages heater_kw heating_ewt heating_lwt water_dp_ft manufacturer model unit_type service equipment_location area_served heating_type').split()
COMPONENT_INPUTS='component_of component_kind component_source_sha256 component_note component_index component_count'.split()
RECORD_INPUTS+=COMPONENT_INPUTS
RECORD_INPUTS.append('supply_fan_count')
OUTLET_INPUTS='include type size system location design_cfm source reference position quantity quantity_unresolved quantity_candidates exclusion_note repeat_resolution repeat_instance manual_locator'.split()
AIR_PATH_INPUTS='tag kind status source source_sha256 reference location note'.split()
EXHAUST_INPUTS='include type size system location design_cfm source reference source_sha256 evidence position position_coordinate_space manual_locator quantity quantity_unresolved exclusion_note'.split()


def physical_quantity(record):
    value=record.get('quantity')
    return 1 if value is None or value=='' else value


def quantity_count(record):
    value=physical_quantity(record)
    if isinstance(value,bool):return 0
    try:number=float(value)
    except (ValueError,TypeError,OverflowError):return 0
    return int(number) if math.isfinite(number) and 1<=number<=500 and number.is_integer() else 0


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
    if review.get('air_paths'):expected['air_paths']=inputs(review['air_paths'],AIR_PATH_INPUTS)
    if review.get('exhaust_outlets'):expected['exhaust_outlets']=inputs(review['exhaust_outlets'],EXHAUST_INPUTS)
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
    component_tags={c['tag'] for c in known.get('report_components',[])}
    for expected in known.get('equipment',[])+known.get('report_components',[]):
        choices=[(i,r) for i,r in enumerate(records) if r.get('tag')==expected['tag']]
        if len(choices)!=1:error('missing_or_duplicate_reviewed_equipment',tag=expected['tag'],count=len(choices));continue
        index,record=choices[0];used_records.add(index)
        if expected['tag'] in component_tags:
            parent=expected.get('component_of')
            supply=expected.get('component_kind')=='integral_supply'
            kind='integral_supply' if supply else 'integral_exhaust'
            label=str(parent)+' SUPPLY FAN '+str(expected.get('component_index')) if supply else str(parent)+' EXHAUST'
            form='Air Moving Equipment.xlsx' if supply else 'Exhaust Fans _Std._.xlsx'
            parents=[r for r in records if r.get('tag')==parent and not any(k in r for k in COMPONENT_INPUTS)]
            if (record.get('component_of')!=parent or record.get('component_kind')!=kind
                    or expected.get('component_kind')!=kind or record['tag']!=label
                    or record.get('template')!=form or (record.get('coil_template')!='' if supply else record.get('coil_template') not in (None,''))
                    or record.get('instance_locations') not in (None,[])
                    or len(parents)!=1 or parents[0].get('template')!='Air Moving Equipment.xlsx'
                    or not same_reviewed(physical_quantity(parents[0]),1)):
                error('invalid_reviewed_component_parent',tag=record['tag'])
            if supply:
                count=expected.get('component_count');index=expected.get('component_index')
                if (type(count) is not int or not 2<=count<=20 or type(index) is not int or not 1<=index<=count
                        or type(record.get('component_index')) is not int or record.get('component_index')!=index
                        or type(record.get('component_count')) is not int or record.get('component_count')!=count
                        or len(parents)!=1 or not same_reviewed(parents[0].get('supply_fan_count'),count)):
                    error('invalid_reviewed_supply_fan_membership',tag=record['tag'])
                if len(parents)==1 and any(parents[0].get(k) not in (None,'') for k in ('motor_hp','motor_volts','motor_phase','motor_fla','motor_rpm')):
                    error('ambiguous_parent_motor_values',tag=parent)
                if any(record.get(k) not in (None,'') for k in ('design_cfm','osa_cfm','osa_min_cfm','esp','total_sp','heating_cfm','heating_edb','heating_ldb','cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb')):
                    error('whole_unit_data_on_motor_form',tag=record['tag'])
            if (record.get('source')!=expected['source'] or page(record)!=expected['page']
                    or record.get('component_source_sha256')!=sources.get(expected['source'])
                    or not isinstance(record.get('component_note'),str) or not 20<=len(record['component_note'].strip())<=500):
                error('unsupported_reviewed_component_source',tag=record['tag'])
        elif any(k in record for k in COMPONENT_INPUTS):error('unexpected_component_metadata',tag=record['tag'])
        if record.get('supply_fan_count') not in (None,'') and 'supply_fan_count' not in expected.get('reviewed_values',{}):error('unsupported_parent_fan_count',tag=record['tag'])
        for key,value in expected.get('reviewed_values',expected.get('values',{})).items():
            if not same_reviewed(record.get(key),value):error('wrong_reviewed_equipment_field',tag=expected['tag'],field=key,expected=value,actual=record.get(key))
        quantity=expected.get('quantity',1)
        if not same_reviewed(physical_quantity(record),quantity):error('wrong_physical_quantity',tag=expected['tag'],expected=quantity,actual=record.get('quantity'))
        if 'instance_locations' in expected and sorted(record.get('instance_locations',[]))!=sorted(expected['instance_locations']):error('wrong_physical_locations',tag=expected['tag'])
        for key in expected.get('must_withhold',[]):
            if record.get(key) not in (None,''):error('unsupported_reviewed_equipment_field',tag=expected['tag'],field=key)
    for index in set(range(len(records)))-used_records:error('unexpected_reviewed_equipment',tag=records[index].get('tag'))
    exhaust_rows=review.get('exhaust_outlets',[]);exhaust=[r for r in exhaust_rows if r.get('include') is True]
    used_exhaust=set();exhaust_matches=[];locators=set()
    for expected in known.get('exhaust_outlets',[]):
        choices=[i for i,item in enumerate(exhaust) if item.get('source')==expected['source']
                 and page(item)==expected['page'] and same_annotation(item,expected)]
        if len(choices)!=1:error('missing_or_duplicate_reviewed_exhaust',id=expected['id'],count=len(choices));continue
        index=choices[0]
        if index in used_exhaust:error('shared_physical_exhaust',id=expected['id']);continue
        used_exhaust.add(index);item=exhaust[index];exhaust_matches.append(expected['id'])
        for key,value in {**expected['values'],**expected.get('review_fields',{})}.items():
            if not same_reviewed(item.get(key),value):error('wrong_reviewed_exhaust_field',id=expected['id'],field=key,expected=value,actual=item.get(key))
        for key in expected.get('must_withhold',[]):
            if item.get(key) not in (None,''):error('unsupported_reviewed_exhaust_field',id=expected['id'],field=key)
    for index in set(range(len(exhaust)))-used_exhaust:error('unexpected_reviewed_exhaust',index=index)
    for item in exhaust_rows:
        if (set(item)-set(EXHAUST_INPUTS+['review_history','review_notice','latest_observation'])
                or type(item.get('include')) is not bool or type(item.get('quantity')) is not int
                or item.get('quantity')!=1 or item.get('quantity_unresolved') is not False):error('invalid_reviewed_exhaust_row')
        if (item.get('source_sha256')!=sources.get(item.get('source'))
                or not any(c['name']==item.get('source') and type(page(item)) is int and 1<=page(item)<=c.get('pages',0) for c in checkpoints)
                or not isinstance(item.get('evidence'),str) or not 20<=len(item['evidence'].strip())<=500):error('unsupported_reviewed_exhaust_source')
        locator=item.get('manual_locator')
        if not isinstance(locator,str) or not 1<=len(locator.strip())<=120:error('missing_exhaust_physical_locator')
        key=(item.get('source'),page(item),str(locator))
        if key in locators:error('duplicate_exhaust_physical_locator')
        locators.add(key)
        if item.get('include') is True:
            fans=[r for r in records if r.get('tag')==item.get('system') and r.get('template') in ('Exhaust Fans _Std._.xlsx','Exhaust Fans _Sm._.xlsx')]
            if len(fans)!=1:error('unverified_exhaust_connection',system=item.get('system'))
        elif not isinstance(item.get('exclusion_note'),str) or not 10<=len(item['exclusion_note'].strip())<=500:error('unresolved_exhaust_candidate')
    if exhaust and ('Exhaust Grills.xlsx' not in review.get('templates',[]) or known.get('exhaust_outlet_inventory_complete') is not True):error('exhaust_template_or_truth_missing')
    for item in exhaust:
        for supply in actual:
            a,b=point(item),point(supply)
            if item.get('source')==supply.get('source') and page(item)==page(supply) and a and b and math.dist(a,b)<1:error('outlet_in_both_supply_and_exhaust')
    # Passive components are frozen separately from physical powered units.
    # A path must be supported by independent component and outlet evidence.
    expected_paths={c['tag'] for c in known.get('associated_components',[]) if c.get('kind')=='PASSIVE SUPPLY INLET'}
    paths=review.get('air_paths',[]);seen_paths=set()
    for path in paths:
        tag=path.get('tag')
        if tag not in expected_paths or tag in seen_paths:error('unexpected_or_duplicate_passive_path',tag=tag)
        seen_paths.add(tag)
        if (set(path)-set(AIR_PATH_INPUTS) or path.get('kind')!='passive_supply' or path.get('status')!='VERIFIED'
                or path.get('source_sha256')!=sources.get(path.get('source'))
                or not isinstance(path.get('note'),str) or not 20<=len(path['note'].strip())<=500
                or not path.get('location')):error('unsupported_passive_path',tag=tag)
        if not any(c['name']==path.get('source') and type(page(path))==int and 1<=page(path)<=c.get('pages',0) for c in checkpoints):error('passive_path_page_missing',tag=tag)
    if seen_paths!=expected_paths:error('passive_path_inventory_mismatch')
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
    for gap in project.get('known_report_omissions',[]):error('unresolved_report_omission',detail=gap)
    return {'reviewed_inventory_pass':not errors,'errors':errors,'matched_outlets':len(matches),
            'included_outlets':len(actual),'verified_equipment_records':len(records),
            'matched_exhaust_outlets':len(exhaust_matches),'included_exhaust_outlets':len(exhaust),
            'physical_equipment_count':sum(quantity_count(r) for r in records if not any(k in r for k in COMPONENT_INPUTS)),
            'component_form_count':sum(1 for r in records if any(k in r for k in COMPONENT_INPUTS)),
            'manual_assignment_events':sum(len(r.get('review_history',[])) for r in actual),
            'scope':'Reviewed source inventory only. Raw extraction scores and exact website workbook audit remain separate.'}
