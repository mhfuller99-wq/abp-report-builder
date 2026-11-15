import copy,json,tempfile,unittest
from pathlib import Path
from abp_benchmark import evaluate,run_suite,digest


def example():
    p={'id':'synthetic','split':'holdout','truth_status':'complete','sources':[{'name':'plan.pdf','sha256':'abc'}],
       'expected':{'outlet_inventory_complete':True,'equipment_inventory_complete':True,'outlets':[
           {'id':'a','source':'plan.pdf','page':1,'position':[100,100],'values':{'type':'S1','design_cfm':100}},
           {'id':'b','source':'plan.pdf','page':1,'position':[200,100],'values':{'type':'S1','design_cfm':200}}],
           'equipment':[{'tag':'RTU-1','source':'plan.pdf','page':2,'values':{'design_cfm':300,'esp':.5}}],
           'excluded_equipment':['CU-1']}}
    r={'scan_state':{'status':'incomplete','complete_takeoff':False,'source_checkpoints':[{'name':'plan.pdf','sha256':'abc'}]},
       'records':[{'tag':'RTU-1','status':'UNVERIFIED','candidates':[
           {'source':'plan.pdf','reference':'page 2','values':{'design_cfm':300,'esp':.5}}]}],
       'diffusers':[{'type':'S1','design_cfm':v,'source':'plan.pdf','page':1,'position':[x,100],
                    'position_coordinate_space':'displayed_pdf_points','include':False} for x,v in [(100,100),(200,200)]],
       'image_review':[]}
    return p,r


class BenchmarkTests(unittest.TestCase):
    def test_raw_candidate_pass_is_not_workbook_pass(self):
        p,r=example();result=evaluate(p,r)
        self.assertTrue(result['candidate_checks_pass']);self.assertFalse(result['workbook_verified'])
    def test_manual_source_rows_cannot_be_counted_as_raw_extraction(self):
        for key in ('records','diffusers'):
            p,r=example();r[key][0]['review_history']=[{'kind':'manual_source_entry','note':'Source checked by reviewer'}]
            self.assertIn('manual_source_entry_in_raw',[e['code'] for e in evaluate(p,r)['errors']])
    def test_same_total_wrong_physical_values_fails(self):
        p,r=example();r['diffusers'][0]['design_cfm'],r['diffusers'][1]['design_cfm']=200,100
        self.assertEqual(len(evaluate(p,r)['errors']),2)
    def test_type_corner_and_airflow_center_share_only_a_bounded_annotation(self):
        p,r=example();r['diffusers'][0].update(position=[95,80],evidence_box=[95,80,108,105])
        self.assertTrue(evaluate(p,r)['candidate_checks_pass'])
        for box in ([0,0,1200,1200],[95,80,108,98],[95,float('nan'),108,105]):
            changed=copy.deepcopy(r);changed['diffusers'][0]['evidence_box']=box
            self.assertFalse(evaluate(p,changed)['candidate_checks_pass'])
        r['diffusers'][0]['type']='WRONG';self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_annotation_box_never_turns_one_candidate_into_two_physical_outlets(self):
        p,r=example();p['expected']['outlets'][1]['position']=[102,100]
        r['diffusers']=r['diffusers'][:1];r['diffusers'][0].update(position=[95,80],evidence_box=[95,80,108,105])
        self.assertIn('shared_physical_candidate',[e['code'] for e in evaluate(p,r)['errors']])
    def test_missing_extra_duplicate_and_wrong_page_fail(self):
        for mutation in ('missing','extra','duplicate','page','coordinates'):
            p,r=example()
            if mutation=='missing':r['diffusers'].pop()
            elif mutation=='extra':r['diffusers'].append({**r['diffusers'][0],'position':[300,100]})
            elif mutation=='duplicate':r['diffusers'].append(copy.deepcopy(r['diffusers'][0]))
            elif mutation=='page':r['diffusers'][0]['page']=9
            else:r['diffusers'][0]['position_coordinate_space']='unrotated'
            self.assertFalse(evaluate(p,r)['candidate_checks_pass'],mutation)
    def test_blanks_are_not_correct_values_and_manual_work_is_counted(self):
        p,r=example();p['expected']['outlets'][0]['review_fields']={'system':'RTU-1'}
        result=evaluate(p,r);self.assertTrue(result['candidate_checks_pass']);self.assertFalse(result['automatic_report_ready'])
        r['diffusers'][0]['design_cfm']=None
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_wrong_room_system_or_size_is_a_failure_not_a_manual_blank(self):
        for field in ('location','system','size'):
            p,r=example();p['expected']['outlets'][0]['review_fields']={field:'EXPECTED'}
            r['diffusers'][0][field]='WRONG'
            self.assertFalse(evaluate(p,r)['candidate_checks_pass'],field)
    def test_unknown_candidate_schema_and_accepted_candidates_fail_closed(self):
        for item in ({'kind':'unknown'},{'kind':'diffuser','accepted':True}):
            p,r=example();r['image_review'].append(item)
            self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_source_changes_auto_acceptance_and_completeness_claims_fail(self):
        for key in ('source','include','verified','complete','conflict'):
            p,r=example()
            if key=='source':r['scan_state']['source_checkpoints'][0]['sha256']='wrong'
            elif key=='include':r['diffusers'][0]['include']=True
            elif key=='verified':r['records'][0]['status']='VERIFIED'
            elif key=='complete':r['scan_state']['complete_takeoff']=True
            else:p['expected']['outlets'][0]['must_withhold']=['size'];r['diffusers'][0]['size']='8'
            self.assertFalse(evaluate(p,r)['candidate_checks_pass'],key)
    def test_image_and_native_candidates_use_same_spatial_checks(self):
        p,r=example();item=r['diffusers'].pop()
        r['image_review'].append({**item,'kind':'diffuser','status':'UNVERIFIED','values':{},'review_values':{'design_cfm':item['design_cfm']}})
        self.assertTrue(evaluate(p,r)['candidate_checks_pass'])
        r['image_review'][0]['review_values']['design_cfm']=None
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_excluded_image_equipment_and_unexpected_units_fail(self):
        p,r=example();r['image_review'].append({'kind':'equipment','tag':'CU-1','status':'UNVERIFIED','values':{},'review_values':{}})
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
        p,r=example();p['expected']['equipment_inventory_complete']=True
        r['records'].append({'tag':'RTU-99','status':'UNVERIFIED','candidates':[]})
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_missing_and_conflicting_equipment_fields_are_failures(self):
        p,r=example();r['records'][0]['candidates'][0]['values'].pop('esp')
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
        r['records'][0]['candidates'][0]['values']['esp']=.8
        self.assertFalse(evaluate(p,r)['candidate_checks_pass'])
    def test_stale_missing_and_modified_evidence_cannot_pass_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p,r=example()
            source=root/'source';source.write_text('synthetic')
            p['sources'][0].update(path=str(source),sha256=digest(source))
            r['scan_state']['source_checkpoints'][0]['sha256']=digest(source)
            truth=root/'truth';truth.write_text('independent synthetic truth')
            p['truth_artifacts']=[{'path':str(truth),'sha256':digest(truth)}]
            suite=root/'suite.json';suite.write_text(json.dumps({'version':1,'projects':[p]}))
            report=root/'report.json';report.write_text(json.dumps(r))
            index=root/'index.json';entry={'project_id':p['id'],'path':str(report),'sha256':digest(report),
                'suite_sha256':digest(suite),'commit':'current','mode':'live_raw'}
            index.write_text(json.dumps({'version':1,'reports':[entry]}))
            result=run_suite(suite,index,'current')
            self.assertFalse(result['release_gate_pass'])
            self.assertEqual(result['blockers'][0]['reason'],'workbook_not_verified')
            self.assertEqual(run_suite(suite,index,'new')['blockers'][0]['reason'],'stale_code_revision')
            report.write_text('{}')
            self.assertEqual(run_suite(suite,index,'current')['blockers'][0]['reason'],'invalid_report')
            source.write_text('changed')
            self.assertEqual(run_suite(suite,index,'current')['blockers'][0]['reason'],'source_or_truth_changed')
    def test_empty_or_duplicate_suite_not_a_success(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Path(temp)/'s';i=Path(temp)/'i';i.write_text('{"version":1,"reports":[]}')
            s.write_text('{"version":1,"projects":[]}')
            self.assertFalse(run_suite(s,i,'commit')['release_gate_pass'])
            p,_=example();s.write_text(json.dumps({'version':1,'projects':[p,p]}))
            with self.assertRaises(ValueError):run_suite(s,i,'commit')
    def test_partial_inventory_cannot_claim_complete_truth(self):
        p,r=example();p['expected']['equipment_inventory_complete']=False
        self.assertFalse(evaluate(p,r)['truth_complete'])
        self.assertFalse(evaluate(p,r)['automatic_report_ready'])
    def test_workbook_pass_is_bound_to_actual_book_templates_and_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p,r=example()
            def file(name,content):
                path=root/name;path.write_text(content)
                return {'path':str(path),'sha256':digest(path)}
            source=file('source','synthetic source')
            p['sources']=[{'name':'plan.pdf',**source}]
            r['scan_state']['source_checkpoints'][0]['sha256']=source['sha256']
            p['truth_artifacts']=[file('truth','independent answers')]
            suite=file('suite',json.dumps({'version':1,'projects':[p]}))
            entry={'project_id':'synthetic',**file('review',json.dumps(r)),
                   'commit':'current','suite_sha256':suite['sha256'],'mode':'live_raw'}
            book=file('workbook','synthetic workbook bytes');template=file('template','original template bytes')
            audit={'commit':'current','review_sha256':entry['sha256'],'workbook':book,'original_templates':[template]}
            audit.update({k:True for k in ('original_formulas_preserved','blank_actuals','original_layout_preserved','grouped_equipment','required_traverses')})
            entry['workbook_audit']={'commit':'current','review_sha256':entry['sha256'],**file('audit',json.dumps(audit))}
            index=file('index',json.dumps({'version':1,'reports':[entry]}))
            self.assertTrue(run_suite(suite['path'],index['path'],'current')['release_gate_pass'])
            for target in (book,template):
                old=Path(target['path']).read_bytes();Path(target['path']).write_text('changed after audit')
                self.assertFalse(run_suite(suite['path'],index['path'],'current')['release_gate_pass'])
                Path(target['path']).write_bytes(old)
            audit['review_sha256']='another review'
            entry['workbook_audit'].update(file('audit',json.dumps(audit)))
            index=file('index',json.dumps({'version':1,'reports':[entry]}))
            self.assertFalse(run_suite(suite['path'],index['path'],'current')['release_gate_pass'])
