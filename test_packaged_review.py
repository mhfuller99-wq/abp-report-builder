"""Invented source layouts only; no client text or documents."""
import copy, unittest
from unittest.mock import patch
import pymupdf
import abp_server as app
from abp_design import inferred_form
from abp_mechanical import packaged_submittals
from abp_ocr import equipment_candidates, word


class PackagedReviewTests(unittest.TestCase):
    def selection(self, lines):
        with pymupdf.open() as doc:
            page=doc.new_page()
            for i,line in enumerate(lines):page.insert_text((20,30+20*i),line,fontsize=9)
            return packaged_submittals(doc,'synthetic.pdf')

    def test_shared_product_tags_no_heat_and_motor_not_drive(self):
        found=self.selection(['Product Data - Packaged Rooftop Units',
            'Item: B3 Qty: 2 Tag(s): PU-7, PU-8','DX Cooling, no heat',
            '7.5 hp supply motor / 850 RPM Fan Drive','460 Volt 60 Hertz 3 Phase'])
        self.assertEqual([r['tag'] for r in found],['PU-7','PU-8'])
        self.assertEqual(found[0]['values'],{'motor_hp':7.5})
        self.assertEqual(found[0]['text']['unit_type'],'PACKAGED / DX COOLING ONLY')
        self.assertEqual(inferred_form('PU-7'),'Air Moving Equipment.xlsx')

    def test_identity_survives_image_only_performance(self):
        found=self.selection(['Product Report - Packaged Rooftop Units','Tag(s): PU-9'])
        self.assertEqual(found[0]['values'],{})
        self.assertEqual(found[0]['tag'],'PU-9')

    def test_ambiguous_and_mixed_identity_not_expanded(self):
        for text in ['Tag(s): PU-9 / PU-10','Tag(s): PU-9, RTU-10','Tag(s): PU-9, PAHU-10',
                     'Tag(s): PU-9, PU-10 (typical)']:
            self.assertEqual(self.selection(['Packaged Rooftop Units',text,'Airflow 1750 cfm']),[])

    def test_measurements_are_not_product_design(self):
        self.assertEqual(self.selection(['Packaged Rooftop Units','Tag(s): PU-9',
            'ACTUAL TEST REPORT','Airflow 1750 cfm']),[])

    def test_unreviewed_images_keep_identity_without_invented_flow(self):
        words=[word(10,10,100,20,'FAN SCHEDULE',95),word(10,40,40,49,'MARK',95),
               word(10,65,50,74,'HVLS–7',65)]
        result=equipment_candidates(words,'synthetic.pdf',1,'ocr')
        self.assertEqual(result[0]['tag'],'HVLS-7')
        self.assertEqual(result[0]['review_values'],{})
        self.assertEqual(result[0]['status'],'UNVERIFIED')
        self.assertFalse(result[0]['include'])

    def test_empty_source_report_rejected_even_with_partial_ack(self):
        state={'status':'incomplete','complete_takeoff':False,'warnings':[],
            'source_checkpoints':[{'name':'synthetic.pdf','native_status':'completed_native_stage','image_status':'incomplete'}]}
        payload={'scan_state':state,'records':[],'diffusers':[],
            'scan_acknowledgement':{'acknowledged':True,'note':'Manually reviewed all incomplete source pages.','scan_state':copy.deepcopy(state)}}
        with self.assertRaisesRegex(ValueError,'takeoff is empty'):app.validate_api_scan_state(payload)
        payload['records']=[{'tag':'PU-7','template':'Air Moving Equipment.xlsx','status':'VERIFIED'}]
        app.validate_api_scan_state(payload)


if __name__=='__main__':unittest.main()
