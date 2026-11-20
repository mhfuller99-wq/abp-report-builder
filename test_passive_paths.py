"""Passive supply inventory is source-bound and never a motorized form."""
import copy,io,unittest
from openpyxl import load_workbook
from abp_source_review import air_path_errors,inventory_snapshot,source_review_approved
from abp_server import build,validate_payload
from test_source_review import payload

def passive_payload():
    p=payload();p['records']=[]
    p['templates']=['Supply Diffusers.xlsx','Duct Traverse Rect..xlsx','Duct Traverse RND.xlsx']
    p['air_paths']=[{'tag':'L-7','kind':'passive_supply','status':'VERIFIED','source':'synthetic.pdf',
        'source_sha256':'a'*64,'reference':'page 1','location':'STORAGE',
        'note':'Plan keynote identifies a passive louver supply duct; separate exhaust drives makeup flow.'}]
    p['diffusers']=[{'include':True,'type':'SAG-9','size':'20X16','system':'L-7','location':'STORAGE',
        'design_cfm':640,'source':'synthetic.pdf','reference':'page 1'}]
    p['source_review']['inventory']=inventory_snapshot(p)
    return p

class PassivePathTests(unittest.TestCase):
    def test_verified_passive_inventory_builds_only_original_outlet_form(self):
        p=passive_payload();self.assertTrue(source_review_approved(p));validate_payload(p)
        wb=load_workbook(io.BytesIO(build(p)))
        try:
            ws=next(s for s in wb if 'SUPPLY DIFFUSER' in s.title.upper())
            self.assertEqual(ws['A5'].value,'L-7');self.assertEqual(ws['G6'].value,640)
            self.assertEqual(ws['A6'].value,'STORAGE');self.assertEqual(ws['D6'].value,'SAG-9')
            self.assertIsNone(ws['F6'].value);self.assertIsNone(ws['H6'].value)
            self.assertEqual(ws['G27'].data_type,'f');self.assertTrue(ws.row_dimensions[7].hidden)
            self.assertTrue(any('RECT' in s.title.upper() for s in wb))
            self.assertTrue(any('RND' in s.title.upper() or 'ROUND' in s.title.upper() for s in wb))
            self.assertFalse(any('AIR MOVING' in s.title.upper() or 'EXHAUST' in s.title.upper() for s in wb))
        finally:wb.close()
        self.assertEqual(p['scan_state']['status'],'incomplete')

    def test_fake_powered_units_changed_sources_and_unverified_paths_block(self):
        changes=[lambda p:p['air_paths'][0].update(tag='EF-7'),
            lambda p:p['air_paths'][0].update(tag='RTU-7'),
            lambda p:p['air_paths'][0].update(kind='exhaust'),
            lambda p:p['air_paths'][0].update(status='UNVERIFIED'),
            lambda p:p['air_paths'][0].update(source_sha256='b'*64),
            lambda p:p['air_paths'][0].update(reference='page 3'),
            lambda p:p['air_paths'][0].update(motor_hp=1),
            lambda p:p['air_paths'][0].update(note='ok'),
            lambda p:p['air_paths'].append(copy.deepcopy(p['air_paths'][0]))]
        for change in changes:
            p=passive_payload();change(p);p['source_review']['inventory']=inventory_snapshot(p)
            self.assertTrue(air_path_errors(p));self.assertFalse(source_review_approved(p))
            with self.assertRaises(ValueError):validate_payload(p)

    def test_every_path_field_binds_approval_and_unknown_systems_do_not_pass(self):
        for field,value in [('note','Different human evidence that needs another review.'),('location','OTHER ROOM'),('reference','page 2')]:
            p=passive_payload();p['air_paths'][0][field]=value
            self.assertFalse(source_review_approved(p))
        p=passive_payload();p['diffusers'][0]['system']='L-99';p['source_review']['inventory']=inventory_snapshot(p)
        self.assertFalse(source_review_approved(p))

    def test_shape_errors_fail_without_crashing_and_partial_ack_cannot_bypass_path_validation(self):
        for value in (None,{},[None],[{'kind':'passive_supply','status':'VERIFIED'}]):
            p=passive_payload();p['air_paths']=value;self.assertFalse(source_review_approved(p))
        p=passive_payload();p.pop('source_review');p['air_paths'][0]['source_sha256']='b'*64
        p['scan_acknowledgement']={'acknowledged':True,'note':'I accept an incomplete partial report.','scan_state':p['scan_state']}
        with self.assertRaisesRegex(ValueError,'Passive path source'):validate_payload(p)

if __name__=='__main__':unittest.main()
