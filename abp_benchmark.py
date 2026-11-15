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


def outlets(review):
    result=[]
    for item in review.get('diffusers',[]):result.append({**item,'lane':'native'})
    for item in review.get('image_review',[]):
        if item.get('kind')=='diffuser':
            result.append({**item,**item.get('review_values',{}),'lane':'image'})
    return result


def evaluate(project,review):
    """Score per physical outlet/field, not aggregate totals; never waive omissions."""
    errors=[];manual=[];matches=[]
    def error(code,**kw):errors.append({'code':code,**kw})
    for item in review.get('records',[])+review.get('diffusers',[]):
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
    for expected in known.get('outlets',[]):
        choices=[]
        for i,item in enumerate(actual):
            pos=point(item)
            if (item.get('source')==expected['source'] and page(item)==expected['page'] and pos is not None
                    and math.dist(pos,expected['position'])<=expected.get('tolerance_points',6)):
                choices.append(i)
        if len(choices)!=1:
            error('missing_outlet' if not choices else 'duplicate_or_ambiguous_outlet',id=expected['id'],candidates=choices)
            continue
        i=choices[0]
        if i in used:error('shared_physical_candidate',id=expected['id']);continue
        used.add(i);item=actual[i];matches.append({'id':expected['id'],'candidate':i})
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
        for i in set(range(len(actual)))-used:error('unexpected_outlet',candidate=i)
    for item in actual:
        if item.get('include'):error('raw_outlet_auto_included')
        if item['lane']=='image' and (item.get('values') or item.get('status')!='UNVERIFIED'):error('image_outlet_auto_verified')
    equipment=[]
    for r in review.get('records',[]):
        if r.get('status')!='UNVERIFIED':error('raw_equipment_auto_verified',tag=r.get('tag'))
        equipment.extend({**c,'tag':r['tag']} for c in r.get('candidates',[]))
    for c in review.get('image_review',[]):
        if c.get('kind')=='equipment':
            if c.get('include') or c.get('values') or c.get('status')!='UNVERIFIED':error('image_equipment_auto_verified',tag=c.get('tag'))
            equipment.append({**c,'values':c.get('review_values',{})})
    for expected in known.get('equipment',[]):
        found=[c for c in equipment if c.get('tag')==expected['tag'] and c.get('source')==expected['source'] and page(c)==expected['page']]
        for field,value in expected['values'].items():
            values=[c.get('values',{}).get(field) for c in found if field in c.get('values',{})]
            if not values:error('missing_equipment_field',tag=expected['tag'],field=field)
            elif any(not same(v,value) for v in values):error('wrong_equipment_field',tag=expected['tag'],field=field,expected=value,actual=values)
    tags={r.get('tag') for r in review.get('records',[])} | {c.get('tag') for c in review.get('image_review',[]) if c.get('kind')=='equipment'}
    for tag in known.get('excluded_equipment',[]):
        if tag in tags:error('associated_or_existing_unit_counted',tag=tag)
    if known.get('equipment_inventory_complete'):
        for tag in tags-{c['tag'] for c in known.get('equipment',[])}:
            error('unexpected_equipment',tag=tag)
    state=review.get('scan_state',{})
    if state.get('complete_takeoff') is not False:error('unsupported_complete_claim')
    if state.get('status') not in ('incomplete','review_required'):error('missing_review_status')
    for need in project.get('unresolved_source_questions',[]):manual.append({'source_question':need})
    truth_complete=(project.get('truth_status')=='complete'
                    and known.get('outlet_inventory_complete') is True
                    and known.get('equipment_inventory_complete') is True)
    return {'project_id':project['id'],'split':project['split'],'candidate_checks_pass':not errors,
            'truth_complete':truth_complete,'errors':errors,'manual_review':manual,'physical_matches':matches,
            'outlet_counts':{'expected':len(known.get('outlets',[])),'actual':len(actual),'matched':len(matches)},
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
