import copy,unittest
from abp_source_review import inventory_snapshot,source_review_errors,source_review_approved
from abp_server import validate_api_scan_state,validate_payload


def payload():
    state={'status':'incomplete','complete_takeoff':False,'warnings':['Image page 2 incomplete'],
        'source_checkpoints':[{'name':'synthetic.pdf','sha256':'a'*64,'pages':2,'native_status':'completed_native_stage','image_status':'incomplete'}]}
    p={'project':'SYNTHETIC','location':'TEST','standard':'Commercial','templates':['Exhaust Fans _Sm._.xlsx'],
        'records':[{'tag':'EF-7','template':'Exhaust Fans _Sm._.xlsx','status':'VERIFIED','design_cfm':90}],
        'diffusers':[],'image_review':[],'scan_state':state}
    p['source_review']={'version':1,'approved':True,'scan_state':copy.deepcopy(state),'inventory':inventory_snapshot(p),
        'note':'Checked all schedule values and relevant drawings; unspecified motor ratings remain blank.',
        'pages':[{'source':'synthetic.pdf','sha256':'a'*64,'page':n,'disposition':'reviewed','note':'Checked the complete source page.'} for n in (1,2)]}
    return p


class SourceReviewTests(unittest.TestCase):
    def test_human_review_does_not_change_automatic_coverage(self):
        p=payload();original=copy.deepcopy(p)
        self.assertEqual(source_review_errors(p),[]);validate_api_scan_state(p);validate_payload(p)
        self.assertEqual(p,original);self.assertEqual(p['scan_state']['status'],'incomplete')
        self.assertFalse(p['scan_state']['complete_takeoff'])

    def test_partial_ack_is_not_source_approval(self):
        p=payload();p.pop('source_review');p['scan_acknowledgement']={'acknowledged':True,'note':'I accept an incomplete partial report.','scan_state':p['scan_state']}
        self.assertFalse(source_review_approved(p));validate_api_scan_state(p)
        p.pop('scan_acknowledgement')
        with self.assertRaisesRegex(ValueError,'incomplete'):validate_api_scan_state(p)

    def test_missing_duplicate_wrong_hash_and_unreviewed_pages_block(self):
        cases=[lambda p:p['source_review']['pages'].pop(),
            lambda p:p['source_review']['pages'].append(copy.deepcopy(p['source_review']['pages'][0])),
            lambda p:p['source_review']['pages'][0].update(sha256='b'*64),
            lambda p:p['source_review']['pages'][0].update(disposition='skipped'),
            lambda p:p['source_review']['pages'][0].update(note='ok')]
        for change in cases:
            p=payload();change(p);self.assertFalse(source_review_approved(p))
            with self.assertRaises(ValueError):validate_api_scan_state(p)

    def test_inventory_source_or_template_changes_invalidate_approval(self):
        for change in [lambda p:p['records'][0].update(design_cfm=91),lambda p:p.update(project='NEW JOB'),
                       lambda p:p['templates'].append('Air Moving Equipment.xlsx'),
                       lambda p:p['scan_state']['warnings'].append('New coverage omission')]:
            p=payload();change(p);self.assertFalse(source_review_approved(p))

    def test_pending_images_and_unresolved_quantities_block_even_new_snapshot(self):
        p=payload();p['image_review']=[{'kind':'equipment','tag':'EF-8','source':'synthetic.pdf','page':1}]
        p['source_review']['inventory']=inventory_snapshot(p);self.assertFalse(source_review_approved(p))
        p['image_review'][0].update(excluded=True,exclusion_note='Duplicate reference on the equipment detail.')
        p['source_review']['inventory']=inventory_snapshot(p);self.assertTrue(source_review_approved(p))
        p['diffusers']=[{'include':True,'type':'A','size':'','system':'AHU-7','location':'ROOM A','design_cfm':100,'source':'synthetic.pdf','reference':'page 1','quantity_unresolved':True}]
        p['source_review']['inventory']=inventory_snapshot(p);self.assertFalse(source_review_approved(p))
        p['diffusers'][0]['quantity_unresolved']=False;p['source_review']['inventory']=inventory_snapshot(p)
        self.assertFalse(source_review_approved(p))
        p['records'].append({'tag':'AHU-7','status':'VERIFIED','template':'Air Moving Equipment.xlsx','design_cfm':100})
        p['templates'].append('Supply Diffusers.xlsx')
        p['source_review']['inventory']=inventory_snapshot(p)
        self.assertTrue(source_review_approved(p))

    def test_unchecked_outlets_require_a_reason_and_included_outlets_require_the_sheet(self):
        p=payload();p['diffusers']=[{'include':False,'type':'A','source':'synthetic.pdf','reference':'page 1'}]
        p['source_review']['inventory']=inventory_snapshot(p)
        self.assertFalse(source_review_approved(p))
        p['diffusers'][0]['exclusion_note']='Confirmed return grille on the original plan, not supply.'
        p['source_review']['inventory']=inventory_snapshot(p)
        self.assertTrue(source_review_approved(p))
        p['diffusers'][0].update(include=True,system='AHU-7',location='ROOM A',design_cfm=100)
        p['records'].append({'tag':'AHU-7','status':'VERIFIED','template':'Air Moving Equipment.xlsx','design_cfm':100})
        p['templates'].append('Air Moving Equipment.xlsx')
        p['source_review']['inventory']=inventory_snapshot(p)
        self.assertFalse(source_review_approved(p))
        p['templates'].append('Supply Diffusers.xlsx');p['source_review']['inventory']=inventory_snapshot(p)
        self.assertTrue(source_review_approved(p));validate_payload(p)
        p['templates'].remove('Supply Diffusers.xlsx')
        p.pop('scan_state');p.pop('source_review')
        with self.assertRaisesRegex(ValueError,'Supply Diffusers'):validate_payload(p)


if __name__=='__main__':unittest.main()
