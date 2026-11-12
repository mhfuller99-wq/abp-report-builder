"""Synthetic native/image disagreements; no client readings or PDFs."""
import copy
import json
import unittest

from abp_ocr_candidates import reconcile_diffuser_sources, merge_diffuser_candidate


def native(flow=180,*,x=100,page=1,source='plan.pdf',size='10x6',kind='SAR'):
    return {'source':source,'reference':f'page {page}','position':[x,100],
            'page_rotation':0,'design_cfm':flow,'size':size,'type':kind,
            'include':False,'system':'','location':'','evidence':'native source words'}


def image(flow=480,*,x=101,page=1,source='plan.pdf',size='10x6',kind='SAR'):
    return {'kind':'diffuser','source':source,'page':page,'position':[x,100],
            'page_rotation':0,'type':kind,'size':size,'status':'UNVERIFIED','include':False,
            'review_values':{} if flow is None else {'design_cfm':flow},'values':{},
            'evidence_text':f'{size} {kind} / {flow} CFM; raw image reading','review_reasons':[]}


class NativeImageOutletTests(unittest.TestCase):
    def test_conflicting_flow_is_blank_and_both_observations_survive(self):
        originals=[native()];before=copy.deepcopy(originals);items=[image()]
        self.assertIs(reconcile_diffuser_sources(originals,items),items)
        c=items[0]
        self.assertEqual(originals,before)
        self.assertEqual(c['review_values'],{})
        self.assertEqual(c['field_conflicts']['design_cfm'],[480,180])
        self.assertEqual(c['ocr_readings'][0]['review_values'],{'design_cfm':480})
        self.assertEqual(c['native_readings'][0]['design_cfm'],180)
        self.assertTrue(c['native_outlet_match'])
        self.assertTrue(any('480' in r and '180' in r for r in c['review_reasons']))
        self.assertEqual((c['status'],c['include'],c['system'],c['location']),('UNVERIFIED',False,'',''))

    def test_conflicting_size_and_type_blank_without_digit_repair(self):
        c=image(180,size='1x6',kind='SXR')
        reconcile_diffuser_sources([native()],[c])
        self.assertEqual((c['size'],c['type']),('',''))
        self.assertEqual(c['review_values'],{'design_cfm':180})
        self.assertEqual(c['field_conflicts']['size'],['1x6','10x6'])
        self.assertEqual(c['ocr_readings'][0]['size'],'1x6')
        self.assertEqual(c['field_conflicts']['type'],['SXR','SAR'])

    def test_agreement_flags_duplicate_without_filling_blank_or_changing_native(self):
        c=image(None,size=' 10 X 6 ',kind='sar');rows=[native()];before=copy.deepcopy(rows)
        reconcile_diffuser_sources(rows,[c])
        self.assertTrue(c['native_outlet_match']);self.assertEqual(c['review_values'],{})
        self.assertNotIn('field_conflicts',c);self.assertEqual(rows,before)

    def test_saved_raw_values_and_reference_page_shape_are_checked(self):
        c=image(None);c.pop('page');c['reference']='page 1';c['values']={'design_cfm':480}
        c['design_cfm']=480
        reconcile_diffuser_sources([native()],[c])
        self.assertEqual(c['values'],{});self.assertIsNone(c['design_cfm'])
        self.assertEqual(c['field_conflicts']['design_cfm'],[480,180])

    def test_serialized_repeated_reconciliation_is_idempotent(self):
        c=image(size='1x6');reconcile_diffuser_sources([native()],[c])
        restored=json.loads(json.dumps(c));before=copy.deepcopy(restored)
        reconcile_diffuser_sources([native()],[restored])
        self.assertEqual(restored,before)

    def test_later_ocr_merge_cannot_repopulate_conflicting_fields(self):
        c=image(size='1x6',kind='SXR');reconcile_diffuser_sources([native()],[c])
        self.assertTrue(merge_diffuser_candidate([c],image(180,kind='SAR')))
        self.assertEqual(c['review_values'],{})
        self.assertEqual((c['type'],c['size']),('',''))

    def test_persisted_conflict_survives_missing_witness_on_later_retry(self):
        c=image();reconcile_diffuser_sources([native()],[c])
        c['review_values']['design_cfm']=580
        reconcile_diffuser_sources([],[c])
        self.assertEqual(c['review_values'],{})
        self.assertEqual(c['field_conflicts']['design_cfm'],[480,180,580])
        self.assertTrue(any(r['review_values']=={'design_cfm':580} for r in c['ocr_readings']))

    def test_distinct_equal_flow_devices_and_other_sources_pages_do_not_match(self):
        for c in (image(180,x=120),image(180,page=2),image(180,source='other.pdf')):
            before=copy.deepcopy(c);reconcile_diffuser_sources([native()],[c]);self.assertEqual(c,before)

    def test_six_point_boundary_is_included_and_multiple_neighbors_are_ambiguous(self):
        c=image(x=106);reconcile_diffuser_sources([native()],[c]);self.assertTrue(c['native_outlet_match'])
        c=image(x=100);reconcile_diffuser_sources([native(x=97),native(x=103)],[c])
        self.assertTrue(c['native_outlet_ambiguous']);self.assertNotIn('native_outlet_match',c)
        self.assertEqual(c['review_values'],{'design_cfm':480})
        self.assertNotIn('native_readings',c)

    def test_missing_invalid_coordinates_and_inconsistent_page_ids_do_not_match(self):
        for alteration in ({'position':None},{'position':[True,100]},{'position':[float('nan'),100]},
                           {'position':[100]},{'position':[-1,100]},{'position':[1e300,100]},
                           {'page':True},{'page':1,'reference':'page 2'}):
            c=image();c.update(alteration);before=copy.deepcopy(c)
            reconcile_diffuser_sources([native()],[c])
            self.assertNotIn('native_outlet_match',c)
            self.assertEqual(c['review_values'],before['review_values'])

    def test_missing_or_mismatched_coordinate_metadata_fails_closed(self):
        c=image();c.pop('page_rotation');reconcile_diffuser_sources([native()],[c])
        self.assertNotIn('native_outlet_match',c);self.assertTrue(c['native_reconciliation_unavailable'])
        c=image();c['position_coordinate_space']='unrotated_pdf_points'
        reconcile_diffuser_sources([native()],[c]);self.assertNotIn('native_outlet_match',c)
        c=image();rows=[native()];c['page_rotation']=90;rows[0]['page_rotation']=90
        reconcile_diffuser_sources(rows,[c]);self.assertNotIn('native_outlet_match',c)
        c['position_coordinate_space']=rows[0]['position_coordinate_space']='displayed_pdf_points'
        reconcile_diffuser_sources(rows,[c]);self.assertTrue(c['native_outlet_match'])
        c=image();rows=[native()];c['page_rotation']=90
        c['position_coordinate_space']=rows[0]['position_coordinate_space']='displayed_pdf_points'
        reconcile_diffuser_sources(rows,[c]);self.assertNotIn('native_outlet_match',c)

    def test_user_accepted_verified_or_selected_choices_are_untouched(self):
        for alteration in ({'include':True},{'accepted':True},{'status':'VERIFIED'}):
            c=image();c.update(alteration);before=copy.deepcopy(c)
            reconcile_diffuser_sources([native()],[c]);self.assertEqual(c,before)

    def test_input_and_tolerance_limits_fail_closed(self):
        for rows,items in (([native()]*501,[image()]),([native()],[image()]*501)):
            with self.assertRaises(ValueError):reconcile_diffuser_sources(rows,items)
        for tolerance in (0,7,True,float('nan')):
            with self.assertRaises(ValueError):reconcile_diffuser_sources([native()],[image()],tolerance=tolerance)


if __name__=='__main__':unittest.main()
