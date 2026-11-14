import copy,json,tempfile,unittest
from pathlib import Path
from abp_benchmark import evaluate,run_suite,digest
from abp_benchmark_reviewed import evaluate_reviewed
from test_benchmark import example


def reviewed_example():
    project,raw=example()
    project['sources'][0]['sha256']='a'*64
    raw['scan_state']['source_checkpoints'][0].update(sha256='a'*64,pages=2)
    for outlet in project['expected']['outlets']:
        outlet['review_fields']={'system':'RTU-1','location':'ROOM A','size':'8'}
    review=copy.deepcopy(raw)
    review.update(project='SYNTHETIC',location='TEST',templates=['Air Moving Equipment.xlsx'])
    review['records'][0].update(status='VERIFIED',design_cfm=300,esp=.5,template='Air Moving Equipment.xlsx')
    for outlet in review['diffusers']:outlet.update(include=True,system='RTU-1',location='ROOM A',size='8',reference='page 1')
    # Explicit synthetic approval fixture, not the application's gate or writer.
    approval={'version':1,'approved':True,'scan_state':copy.deepcopy(review['scan_state']),
        'note':'Reviewed all source pages and confirmed the complete design inventory.',
        'pages':[{'source':'plan.pdf','sha256':'a'*64,'page':p,'disposition':'reviewed',
                  'note':'Checked schedule and physical plan connections.'} for p in (1,2)]}
    approval['inventory']={'project':'SYNTHETIC','location':'TEST','templates':['Air Moving Equipment.xlsx'],'standard':'Commercial',
        'records':[{k:v for k,v in review['records'][0].items() if k!='candidates'}],
        'diffusers':[{k:v for k,v in d.items() if k not in ('page','position_coordinate_space')} for d in review['diffusers']],
        'image_decisions':[]}
    review['source_review']=approval
    return project,raw,review


class ReviewedBenchmarkTests(unittest.TestCase):
    def test_reviewed_success_does_not_erase_missing_raw_fields(self):
        project,raw,review=reviewed_example()
        raw['records'][0]['candidates'][0]['values'].pop('esp')
        self.assertFalse(evaluate(project,raw)['candidate_checks_pass'])
        before=copy.deepcopy((project,raw,review))
        self.assertTrue(evaluate_reviewed(project,review)['reviewed_inventory_pass'])
        self.assertEqual((project,raw,review),before)

    def test_changed_approval_input_fails_even_when_not_an_expected_numeric_field(self):
        for mutate in (lambda r:r.update(project='OTHER JOB'),
                       lambda r:r['records'][0].update(manufacturer='UNSUPPORTED'),
                       lambda r:r['diffusers'][0].update(quantity_unresolved=True),
                       lambda r:r['source_review'].update(note='ok')):
            project,_,review=reviewed_example();mutate(review)
            self.assertFalse(evaluate_reviewed(project,review)['reviewed_inventory_pass'])

    def test_wrong_values_quantities_duplicate_rows_and_coverage_fail(self):
        for mutate in (lambda r:r['diffusers'][0].update(design_cfm=200),
                       lambda r:r['records'][0].update(quantity=2),
                       lambda r:r['diffusers'].append(copy.deepcopy(r['diffusers'][0])),
                       lambda r:r['source_review']['pages'].pop(),
                       lambda r:r['scan_state'].update(complete_takeoff=True)):
            project,_,review=reviewed_example();mutate(review)
            self.assertFalse(evaluate_reviewed(project,review)['reviewed_inventory_pass'])

    def test_reviewed_release_requires_exact_bound_workbook_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def file(name,value):
                path=root/name;path.write_text(value if isinstance(value,str) else json.dumps(value))
                return {'path':str(path),'sha256':digest(path)}
            project,raw,review=reviewed_example();source=file('source','SYNTHETIC SOURCE')
            project['sources']=[{'name':'plan.pdf',**source}]
            for r in (raw,review):r['scan_state']['source_checkpoints'][0]['sha256']=source['sha256']
            review['source_review']['scan_state']=copy.deepcopy(review['scan_state'])
            for p in review['source_review']['pages']:p['sha256']=source['sha256']
            raw['records'][0]['candidates'][0]['values'].pop('esp')
            project['truth_artifacts']=[file('truth','INDEPENDENT SYNTHETIC ANSWERS')]
            suite=file('suite',{'version':1,'projects':[project]})
            entry={'project_id':'synthetic',**file('raw',raw),'commit':'current','suite_sha256':suite['sha256'],
                'mode':'live_raw','acceptance_mode':'reviewed_workflow'}
            entry['reviewed_review']={**file('reviewed',review),'commit':'current','raw_review_sha256':entry['sha256'],'mode':'website_reviewed'}
            audit={'commit':'current','raw_review_sha256':entry['sha256'],'review_sha256':entry['reviewed_review']['sha256'],
                'website_job_id':'b'*48,'workbook':file('book','WORKBOOK BYTES'),
                'original_templates':[file('template','ORIGINAL TEMPLATE BYTES')]}
            audit.update({k:True for k in ('original_formulas_preserved','blank_actuals','original_layout_preserved',
                'grouped_equipment','required_traverses','exact_design_values','all_caps','diffuser_totals_adjacent',
                'no_unnecessary_comments','no_unexplained_omissions')})
            def check():
                entry['workbook_audit']={**file('audit',audit),'commit':'current','review_sha256':entry['reviewed_review']['sha256']}
                index=file('index',{'version':1,'reports':[entry]})
                return run_suite(suite['path'],index['path'],'current')
            result=check()
            self.assertTrue(result['release_gate_pass'],result['blockers'])
            self.assertFalse(result['all_raw_candidate_checks_pass'])
            audit['website_job_id']='missing';self.assertFalse(check()['release_gate_pass'])
            audit['website_job_id']='b'*48;audit['exact_design_values']=False
            self.assertFalse(check()['release_gate_pass'])
            audit['exact_design_values']=True;entry['reviewed_review']['raw_review_sha256']='wrong'
            self.assertFalse(check()['release_gate_pass'])


if __name__=='__main__':unittest.main()
