"""Independent, read-only evaluation of private source truth and website exports.

No extraction imports: the scanner cannot manufacture its own expected answers.
Client documents, fixtures and reports stay outside the repository.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def same(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return a is b
    if isinstance(b,(float,int)):
        return isinstance(a,(float,int)) and math.isfinite(a) and math.isclose(a,b,rel_tol=0,abs_tol=1e-6)
    return a==b


def page(item):
    if type(item.get('page')) is int:return item['page']
    m=re.fullmatch(r'page\s+(\d+)',str(item.get('reference','')),re.I)
    return int(m[1]) if m else None


def point(item):
    p=item.get('position')
    space=item.get('position_coordinate_space',item.get('coordinate_space',item.get('region_coordinate_space')))
    if space!='displayed_pdf_points' or not isinstance(p,list) or len(p)!=2:return None
    return p if all(type(v) in (int,float) and math.isfinite(v) for v in p) else None


def same_annotation(item,expected):
    """Compare a point anchor or its bounded, same-coordinate callout box.

    Native readers can anchor the type's corner while independent reviewers
    mark the airflow center. Both must belong to one small annotation. This
    never accepts a whole-page region or expands a repeated physical count.
    """
    pos=point(item)
    if pos is None:return False
    target=expected['position']
    if math.dist(pos,target)<=expected.get('tolerance_points',6):return True
    box=item.get('evidence_box')
    if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):return False
    x0,y0,x1,y1=box
    if not (0<x1-x0<=120 and 0<y1-y0<=120):return False
    return (x0-1<=pos[0]<=x1+1 and y0-1<=pos[1]<=y1+1
            and x0<=target[0]<=x1 and y0<=target[1]<=y1)


def outlets(review):
    result=[]
    for item in review.get('diffusers',[]):result.append({**item,'lane':'native'})
    for item in review.get('image_review',[]):
        if item.get('kind')=='diffuser':
            result.append({**item,**item.get('review_values',{}),'lane':'image'})
    return result


def outlet_anchor(row):
    """Require an explicit common frame before treating two readings as one."""
    source=row.get('source')
    number=page(row)
    pos=point(row)
    if not isinstance(source,str) or not source or not number or number<1 or pos is None:
        return None
    if 'page' in row and type(row['page']) is not int:
        return None
    if 'reference' in row and page({'reference':row['reference']})!=number:
        return None
    if any(row.get(k) not in (None,'displayed_pdf_points') for k in
           ('coordinate_space','position_coordinate_space','region_coordinate_space')):
        return None
    return source,number


def linked_outlet_observations(rows,expected):
    """Verify the scanner's link against both the exported native row and the frozen plan."""
    native={}
    proposed={}
    for index,row in enumerate(rows):
        anchor=outlet_anchor(row)
        if row['lane']=='native' and anchor:
            native.setdefault(anchor,[]).append(index)
    for index,image in enumerate(rows):
        if (image['lane']!='image' or image.get('native_outlet_match') is not True
                or image.get('native_reconciled') is not True or image.get('native_outlet_ambiguous')):
            continue
        anchor=outlet_anchor(image)
        nearby=[i for i in native.get(anchor,[]) if math.dist(point(image),point(rows[i]))<=6]
        if len(nearby)!=1:
            continue
        parent=nearby[0]
        row=rows[parent]
        if (image.get('page_rotation') is not None and row.get('page_rotation') is not None
                and image['page_rotation']!=row['page_rotation']):
            continue
        # Old exports without a native witness and stale links stay separate.
        if not any(isinstance(w,dict) and w.get('source')==anchor[0] and w.get('page')==anchor[1]
                   and w.get('position')==row.get('position') for w in image.get('native_readings') or []):
            continue
        if any(same_annotation(image,e) and not same_annotation(row,e) for e in expected
               if (e['source'],e['page'])==anchor):
            continue
        proposed.setdefault(parent,[]).append(index)
    # Multiple independent image rows near one label could be adjacent outlets.
    return {images[0]:parent for parent,images in proposed.items() if len(images)==1}


def evaluate(project,review):
    """Score per physical outlet/field, not aggregate totals; never waive omissions."""
    errors=[];manual=[];matches=[]
    def error(code,**kw):errors.append({'code':code,**kw})
    if review.get('air_paths'):error('manual_air_paths_in_raw')
    for item in review.get('records',[])+review.get('diffusers',[])+review.get('exhaust_outlets',[]):
        if item.get('manual_locator') or any(h.get('kind')=='manual_source_entry' for h in item.get('review_history',[]) if isinstance(h,dict)):
            error('manual_source_entry_in_raw',tag=item.get('tag'),source=item.get('source'))
    sources={s['name']:s['sha256'] for s in project['sources']}
    checkpoints=review.get('scan_state',{}).get('source_checkpoints',[])
    observed={s['name']:s.get('sha256') for s in checkpoints}
    if len(observed)!=len(checkpoints) or observed!=sources:error('source_identity_mismatch')
    for item in review.get('image_review',[]):
        if item.get('kind') not in ('diffuser','equipment','kitchen_hood'):
            error('unknown_image_candidate_kind',kind=item.get('kind'))
        if item.get('accepted'):error('manually_accepted_raw_candidate')
    known=project['expected'];actual=outlets(review);used=set()
    linked=linked_outlet_observations(actual,known.get('outlets',[]))
    physical=[i for i in range(len(actual)) if i not in linked]
    expected_for={}
    for expected in known.get('outlets',[]):
        choices=[]
        for i in physical:
            item=actual[i]
            if (item.get('source')==expected['source'] and page(item)==expected['page'] and same_annotation(item,expected)):
                choices.append(i)
        if len(choices)!=1:
            error('missing_outlet' if not choices else 'duplicate_or_ambiguous_outlet',id=expected['id'],candidates=choices)
            continue
        i=choices[0]
        if i in used:error('shared_physical_candidate',id=expected['id']);continue
        used.add(i);item=actual[i];matches.append({'id':expected['id'],'candidate':i})
        expected_for[i]=expected
        for field,value in expected['values'].items():
            if not same(item.get(field),value):
                code='missing_field' if item.get(field) in (None,'') else 'wrong_field'
                error(code,id=expected['id'],field=field,expected=value,actual=item.get(field))
        for field,value in expected.get('review_fields',{}).items():
            if item.get(field) in (None,''):
                manual.append({'id':expected['id'],'field':field,'expected':value,'actual':item.get(field)})
            elif not same(item.get(field),value):
                error('wrong_review_field',id=expected['id'],field=field,expected=value,actual=item.get(field))
        for field in expected.get('must_withhold',[]):
            if item.get(field) not in (None,''):error('unresolved_conflict_populated',id=expected['id'],field=field)
    if known.get('outlet_inventory_complete'):
        for i in sorted(set(physical)-used):error('unexpected_outlet',candidate=i)
    for index,parent in linked.items():
        image=actual[index]
        target=expected_for.get(parent,{})
        wanted={**target.get('values',{}),**target.get('review_fields',{})}
        conflicts=set(image.get('native_conflict_fields') or [])|set(image.get('field_conflicts') or {})
        withheld=set(target.get('must_withhold',[]))
        for field in {'type','size','design_cfm','quantity','location','system'}|wanted.keys()|withheld:
            value=image.get(field)
            if value in (None,''):
                continue
            if (field in withheld or
                    any(v not in (None,'') and not same(value,v) for v in (actual[parent].get(field),wanted.get(field)))):
                conflicts.add(field)
        if image.get('type_conflict_unresolved'):conflicts.add('type')
        if image.get('printed_flow_conflict'):conflicts.add('design_cfm')
        if conflicts:
            error('conflicting_outlet_observations',candidate=index,native_candidate=parent,fields=sorted(conflicts))
        if image.get('quantity_unresolved') or image.get('ocr_readings_truncated') or image.get('native_reconciliation_log_truncated'):
            manual.append({'candidate':index,'native_candidate':parent,'reason':'Review repeat quantity or incomplete observation history'})
    for item in actual:
        if item.get('include'):error('raw_outlet_auto_included')
        if item['lane']=='image' and (item.get('values') or item.get('status')!='UNVERIFIED'):error('image_outlet_auto_verified')
    # Exhaust inlets are an independent physical inventory, never supply matches.
    exhaust=review.get('exhaust_outlets',[]);used_exhaust=set();exhaust_matches=[]
    for expected in known.get('exhaust_outlets',[]):
        choices=[i for i,item in enumerate(exhaust) if item.get('source')==expected['source']
                 and page(item)==expected['page'] and same_annotation(item,expected)]
        if len(choices)!=1:error('missing_or_duplicate_exhaust_outlet',id=expected['id'],candidates=choices);continue
        i=choices[0]
        if i in used_exhaust:error('shared_physical_exhaust_candidate',id=expected['id']);continue
        used_exhaust.add(i);item=exhaust[i];exhaust_matches.append(expected['id'])
        for field,value in expected['values'].items():
            if not same(item.get(field),value):error('wrong_exhaust_field',id=expected['id'],field=field,expected=value,actual=item.get(field))
        for field,value in expected.get('review_fields',{}).items():
            if item.get(field) in (None,''):manual.append({'id':expected['id'],'field':field,'expected':value,'actual':item.get(field)})
            elif not same(item.get(field),value):error('wrong_exhaust_review_field',id=expected['id'],field=field,expected=value,actual=item.get(field))
        for field in expected.get('must_withhold',[]):
            if item.get(field) not in (None,''):error('unsupported_exhaust_field',id=expected['id'],field=field)
    for i,item in enumerate(exhaust):
        if item.get('include'):error('raw_exhaust_auto_included',candidate=i)
        if i not in used_exhaust:error('unexpected_exhaust_outlet',candidate=i)
    equipment=[]
    for r in review.get('records',[]):
        if r.get('status')!='UNVERIFIED':error('raw_equipment_auto_verified',tag=r.get('tag'))
        equipment.extend({**c,'tag':r['tag']} for c in r.get('candidates',[]))
    for c in review.get('image_review',[]):
        if c.get('kind')=='equipment':
            if c.get('include') or c.get('values') or c.get('status')!='UNVERIFIED':error('image_equipment_auto_verified',tag=c.get('tag'))
            equipment.append({**c,'values':c.get('review_values',{})})
    for expected in known.get('equipment',[])+known.get('report_components',[]):
        found=[c for c in equipment if c.get('tag')==expected['tag'] and c.get('source')==expected['source'] and page(c)==expected['page']]
        # Deliberately unknown design values do not waive the physical unit.
        if not found:error('missing_equipment',tag=expected['tag'],source=expected['source'],page=expected['page'])
        for field,value in expected['values'].items():
            values=[c.get('values',{}).get(field) for c in found if field in c.get('values',{})]
            if not values:error('missing_equipment_field',tag=expected['tag'],field=field)
            elif any(not same(v,value) for v in values):error('wrong_equipment_field',tag=expected['tag'],field=field,expected=value,actual=values)
    tags={r.get('tag') for r in review.get('records',[])} | {c.get('tag') for c in review.get('image_review',[]) if c.get('kind')=='equipment'}
    for tag in known.get('excluded_equipment',[]):
        if tag in tags:error('associated_or_existing_unit_counted',tag=tag)
    if known.get('equipment_inventory_complete'):
        for tag in tags-{c['tag'] for c in known.get('equipment',[])+known.get('report_components',[])}:
            error('unexpected_equipment',tag=tag)
    state=review.get('scan_state',{})
    if state.get('complete_takeoff') is not False:error('unsupported_complete_claim')
    if state.get('status') not in ('incomplete','review_required'):error('missing_review_status')
    for need in project.get('unresolved_source_questions',[]):manual.append({'source_question':need})
    for gap in project.get('known_report_omissions',[]):manual.append({'report_omission':gap})
    truth_complete=(project.get('truth_status')=='complete'
                    and known.get('outlet_inventory_complete') is True
                    and known.get('equipment_inventory_complete') is True)
    return {'project_id':project['id'],'split':project['split'],'candidate_checks_pass':not errors,
            'truth_complete':truth_complete,'errors':errors,'manual_review':manual,'physical_matches':matches,
            'outlet_counts':{'expected':len(known.get('outlets',[])),'actual':len(physical),'matched':len(matches)},
            'outlet_observations':{'total':len(actual),'linked_to_native':[
                {'image_candidate':i,'native_candidate':parent} for i,parent in linked.items()]},
            'exhaust_outlet_counts':{'expected':len(known.get('exhaust_outlets',[])),'actual':len(exhaust),'matched':len(exhaust_matches)},
            'equipment_tags':sorted(tags),
            'automatic_report_ready':not errors and truth_complete and not manual,
            'workbook_verified':False,'scope':'Raw extraction only; workbook/formula acceptance is a separate required stage.'}


def run_suite(suite_path,index_path,commit):
    suite=read(suite_path);index=read(index_path);results=[];gate=[]
    if suite.get('version')!=1 or index.get('version')!=1:raise ValueError('Unsupported benchmark version')
    ids=[p['id'] for p in suite['projects']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate project IDs')
    entries=index['reports']
    if len(entries)!=len({r['project_id'] for r in entries}):raise ValueError('Duplicate report IDs')
    if set(r['project_id'] for r in entries)-set(ids):raise ValueError('Unknown project in report index')
    for project in suite['projects']:
        pid=project['id']
        if project.get('split') not in ('regression','holdout'):raise ValueError('Invalid project split')
        if not project.get('sources') or not project.get('truth_artifacts'):
            gate.append({'project_id':pid,'reason':'source_truth_not_frozen'});continue
        changed=[]
        for artifact in project['sources']+project.get('references',[])+project['truth_artifacts']:
            try:valid=digest(artifact['path'])==artifact['sha256']
            except OSError:valid=False
            if not valid:changed.append(artifact['path'])
        if changed:gate.append({'project_id':pid,'reason':'source_or_truth_changed','paths':changed});continue
        entry=next((r for r in entries if r['project_id']==pid),None)
        if not entry:gate.append({'project_id':pid,'reason':'missing_test'});continue
        if entry.get('commit')!=commit:gate.append({'project_id':pid,'reason':'stale_code_revision'});continue
        if entry.get('suite_sha256')!=digest(suite_path):gate.append({'project_id':pid,'reason':'stale_expected_answers'});continue
        if entry.get('mode')!='live_raw':gate.append({'project_id':pid,'reason':'not_a_live_raw_test'});continue
        try:
            if digest(entry['path'])!=entry['sha256']:raise ValueError('Report changed')
            result=evaluate(project,read(entry['path']))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            gate.append({'project_id':pid,'reason':'invalid_report','detail':str(exc)});continue
        results.append(result)
        acceptance=entry.get('acceptance_mode','automatic')
        if acceptance not in ('automatic','reviewed_workflow'):raise ValueError('Invalid acceptance mode')
        result['acceptance_mode']=acceptance
        reviewed_hash=entry['sha256']
        if acceptance=='automatic' and not result['candidate_checks_pass']:gate.append({'project_id':pid,'reason':'extraction_failure'})
        if not result['truth_complete']:gate.append({'project_id':pid,'reason':'incomplete_expected_answers'})
        if acceptance=='automatic' and not result['automatic_report_ready']:gate.append({'project_id':pid,'reason':'manual_review_remaining'})
        if acceptance=='reviewed_workflow':
            from abp_benchmark_reviewed import evaluate_reviewed
            try:
                reviewed=entry['reviewed_review']
                if (reviewed.get('commit')!=commit or reviewed.get('raw_review_sha256')!=entry['sha256']
                        or reviewed.get('mode')!='website_reviewed' or digest(reviewed['path'])!=reviewed['sha256']):
                    raise ValueError('Reviewed export is not bound to this raw scan and revision')
                result['reviewed_workflow']=evaluate_reviewed(project,read(reviewed['path']))
                reviewed_hash=reviewed['sha256']
                if not result['reviewed_workflow']['reviewed_inventory_pass']:gate.append({'project_id':pid,'reason':'reviewed_inventory_failed'})
            except (OSError,KeyError,ValueError,TypeError):gate.append({'project_id':pid,'reason':'reviewed_export_missing_or_invalid'})
        # An extraction pass is never a workbook acceptance pass.
        audit=entry.get('workbook_audit')
        if not isinstance(audit,dict) or audit.get('commit')!=commit or audit.get('review_sha256')!=reviewed_hash:
            gate.append({'project_id':pid,'reason':'workbook_not_verified'})
        else:
            try:
                if digest(audit['path'])!=audit['sha256']:raise ValueError('Workbook audit changed')
                report=read(audit['path'])
                if report.get('commit')!=commit or report.get('review_sha256')!=reviewed_hash:
                    raise ValueError('Workbook audit belongs to another review or revision')
                book=report['workbook'];templates=report['original_templates']
                if not templates or digest(book['path'])!=book['sha256']:
                    raise ValueError('Workbook or original template evidence missing or changed')
                if any(digest(t['path'])!=t['sha256'] for t in templates):
                    raise ValueError('Original template changed after audit')
                exhaust_master=project['expected'].get('required_exhaust_template')
                if exhaust_master and not any(str(t['path']).replace('\\','/').rsplit('/',1)[-1]==exhaust_master['name']
                        and t['sha256']==exhaust_master['sha256'] for t in templates):
                    raise ValueError('Required original exhaust grille template is missing or changed')
                required=('original_formulas_preserved','blank_actuals','original_layout_preserved','grouped_equipment','required_traverses')
                if acceptance=='reviewed_workflow':
                    required+=('exact_design_values','all_caps','diffuser_totals_adjacent','no_unnecessary_comments','no_unexplained_omissions')
                    if report.get('raw_review_sha256')!=entry['sha256'] or not re.fullmatch(r'[a-f0-9]{48}',report.get('website_job_id','')):
                        raise ValueError('Website build provenance missing')
                if not all(report.get(k) is True for k in required):raise ValueError('Workbook acceptance incomplete')
                result['workbook_verified']=True
            except (OSError,KeyError,ValueError,TypeError):gate.append({'project_id':pid,'reason':'workbook_audit_failed'})
    required_holdouts=suite.get('required_holdouts',1)
    if type(required_holdouts)!=int or not 1<=required_holdouts<=100:raise ValueError('Invalid required holdout count')
    if sum(p['split']=='holdout' for p in suite['projects'])<required_holdouts:gate.append({'reason':'no_holdout_projects' if required_holdouts==1 else 'insufficient_holdout_projects'})
    return {'commit':commit,'suite_sha256':digest(suite_path),'results':results,'release_gate_pass':not gate,'blockers':gate,
            'all_raw_candidate_checks_pass':bool(results) and len(results)==len(suite['projects']) and all(r['candidate_checks_pass'] for r in results),
            'scope':'Acceptance uses each declared automatic or reviewed workflow; reviewed acceptance never changes raw extraction scores.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',required=True);parser.add_argument('--reports',required=True)
    parser.add_argument('--commit',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=run_suite(args.suite,args.reports,args.commit)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'projects_evaluated':len(result['results']),'release_gate_pass':result['release_gate_pass'],
                      'blocker_count':len(result['blockers'])}))
    raise SystemExit(0 if result['release_gate_pass'] else 1)
