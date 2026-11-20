"""Multiple motors preserve one unit, original forms and unsupported blanks."""
import copy,io,unittest
from unittest.mock import patch
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
import abp_server as app
from abp_components import component_errors
from abp_source_review import inventory_snapshot,source_review_approved
from test_source_review import payload


def fan_payload():
    p=payload();p['templates']=['Air Moving Equipment.xlsx','Coil DX GAS HT.xlsx','Exhaust Fans _Std._.xlsx']
    p['records']=[{'tag':'RTU-6','template':'Air Moving Equipment.xlsx','coil_template':'Coil DX GAS HT.xlsx',
        'status':'VERIFIED','design_cfm':2700,'osa_cfm':550,'cooling_edb':81,'supply_fan_count':2}]
    for index in (1,2):
        p['records'].append({'tag':'RTU-6 SUPPLY FAN '+str(index),'component_of':'RTU-6','component_kind':'integral_supply',
            'component_index':index,'component_count':2,'component_source_sha256':'a'*64,
            'component_note':'Original schedule lists two supply fans and separate horsepower per fan.',
            'source':'synthetic.pdf','reference':'page 2','template':'Air Moving Equipment.xlsx','coil_template':'',
            'status':'VERIFIED','motor_hp':2,'unit_type':'AIRFOIL','service':'SUPPLY','equipment_location':'ROOF'})
    p['records'].append({'tag':'RTU-6 EXHAUST','component_of':'RTU-6','component_kind':'integral_exhaust',
        'component_source_sha256':'a'*64,'component_note':'Original schedule separately lists this integral exhaust fan.',
        'source':'synthetic.pdf','reference':'page 2','template':'Exhaust Fans _Std._.xlsx','status':'VERIFIED','design_cfm':400})
    p['source_review']['inventory']=inventory_snapshot(p);return p


class SupplyFanTests(unittest.TestCase):
    def test_original_motor_forms_do_not_duplicate_parent_airflow_coils_or_traverses(self):
        p=fan_payload();before=copy.deepcopy(p)
        self.assertTrue(source_review_approved(p));app.validate_payload(p)
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):data=app.build(p)
        wb=load_workbook(io.BytesIO(data));master=load_workbook(app.LOOKUP['Air Moving Equipment.xlsx'])
        try:
            ws=wb['AIR MOVING EQUIPMENT'];src=master.active;self.assertEqual(ws.max_row,126)
            self.assertEqual([ws[f'G{r}'].value for r in (3,45,87)],['RTU-6','RTU-6 SUPPLY FAN 1','RTU-6 SUPPLY FAN 2'])
            self.assertEqual(ws['G17'].value,2700);self.assertIsNone(ws['T4'].value)
            for off in (42,84):
                self.assertEqual(ws.cell(4+off,20).value,2)
                for cell in ('G17','G18','G20','G21','T5','X5','T6','T7','G7','J17','T17','T20'):
                    anchor=src[cell];self.assertIsNone(ws.cell(anchor.row+off,anchor.column).value,cell)
            for off in (0,42,84):
                for row in src:
                    for cell in row:
                        target=ws.cell(cell.row+off,cell.column)
                        if cell.data_type=='f':self.assertEqual(target.value,Translator(cell.value,origin=cell.coordinate).translate_formula(target.coordinate))
                        for attr in ('font','fill','border','alignment','number_format','protection'):
                            self.assertEqual(copy.copy(getattr(target,attr)),copy.copy(getattr(cell,attr)),target.coordinate)
            coil=wb['COIL DX GAS HT'];self.assertEqual(coil['D4'].value,'RTU-6');self.assertEqual(coil['D8'].value,2700)
            self.assertIsNone(coil['F4'].value);self.assertIsNone(coil['H4'].value)
            rect=wb['DUCT TRAVERSE RECT.'];self.assertEqual(rect['D3'].value,'RTU-6');self.assertEqual(rect['L3'].value,550)
            self.assertEqual(sum(c.value=='RTU-6' for row in rect for c in row),2)
            self.assertFalse(any(isinstance(c.value,str) and 'SUPPLY FAN' in c.value for row in rect for c in row))
            self.assertTrue(any('RND' in s.title for s in wb))
            self.assertEqual(wb['EXHAUST FAN']['H3'].value,'RTU-6 EXHAUST')
        finally:wb.close();master.close()
        self.assertEqual(p,before)

    def test_missing_changed_or_mixed_fan_membership_blocks_even_partial_builds(self):
        cases=[lambda p:p['records'].pop(1),lambda p:p['records'].__setitem__(slice(1,3),[]),
            lambda p:p['records'][0].update(supply_fan_count=3),lambda p:p['records'][0].update(supply_fan_count=True),
            lambda p:p['records'][0].pop('supply_fan_count'),lambda p:p['records'][0].update(motor_hp=2),
            lambda p:p['records'][1].update(component_index=2),lambda p:p['records'][1].update(component_count=3),
            lambda p:p['records'][1].update(component_index=True),lambda p:p['records'][1].update(component_source_sha256='b'*64),
            lambda p:p['records'][1].update(reference='page 1'),lambda p:p['records'][1].update(status='EXCLUDED'),
            lambda p:p['records'][1].update(design_cfm=1350),lambda p:p['records'][1].update(osa_cfm=275),
            lambda p:p['records'][1].update(esp=.5),lambda p:p['records'][1].update(cooling_edb=81),
            lambda p:p['records'][1].update(coil_template='Coil DX GAS HT.xlsx'),
            lambda p:p['records'][1].update(template='Exhaust Fans _Std._.xlsx'),
            lambda p:p['diffusers'].append({'include':True,'system':'RTU-6 SUPPLY FAN 1','design_cfm':100})]
        for change in cases:
            p=fan_payload();change(p);p['source_review']['inventory']=inventory_snapshot(p)
            self.assertTrue(component_errors(p));self.assertFalse(source_review_approved(p))
            p.pop('source_review');p['scan_acknowledgement']={'acknowledged':True,'note':'Reviewed incomplete source coverage for this job.','scan_state':p['scan_state']}
            with self.assertRaises(ValueError):app.validate_payload(p)

    def test_complete_drafts_restore_but_require_individual_reverification(self):
        p=fan_payload();p['records'][0]['supply_fan_count']='2'
        self.assertFalse(component_errors(p))
        for record in p['records']:record['status']='UNVERIFIED'
        self.assertFalse(component_errors(p,require_verified=False))
        self.assertTrue(component_errors(p));self.assertFalse(source_review_approved(p))
        for record in p['records']:record['status']='EXCLUDED'
        self.assertFalse(component_errors(p))
        for key,value in [('component_index',2),('component_count',3),('component_note','Different evidence requires a new approval.')]:
            p=fan_payload();p['records'][1][key]=value;self.assertFalse(source_review_approved(p))


if __name__=='__main__':unittest.main()
