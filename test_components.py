"""Linked component safety and the actual original-template writer contract."""
import copy,io,unittest
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from abp_components import component_errors
from abp_source_review import inventory_snapshot,source_review_approved
from abp_server import build,validate_payload,LOOKUP
from test_source_review import payload


def component_payload():
    p=payload();p['templates']=['Air Moving Equipment.xlsx','Exhaust Fans _Std._.xlsx']
    p['records']=[{'tag':'RTU-9','template':'Air Moving Equipment.xlsx','status':'VERIFIED',
        'design_cfm':2400,'motor_hp':3,'motor_volts':460,'motor_phase':3,'motor_fla':8},
        {'tag':'RTU-9 EXHAUST','template':'Exhaust Fans _Std._.xlsx','status':'VERIFIED',
        'component_of':'RTU-9','component_kind':'integral_exhaust','component_source_sha256':'a'*64,
        'component_note':'The rooftop schedule identifies one integral exhaust fan with separate design data.',
        'source':'synthetic.pdf','reference':'page 2','design_cfm':630,'esp':0.4,'motor_hp':2,
        'unit_type':'AIRFOIL','service':'EXHAUST','equipment_location':'ROOF'},
        {'tag':'EF-3','template':'Exhaust Fans _Std._.xlsx','status':'VERIFIED','design_cfm':80}]
    p['source_review']['inventory']=inventory_snapshot(p)
    return p


class ComponentTests(unittest.TestCase):
    def test_original_fan_forms_group_below_each_other_without_a_second_rooftop(self):
        p=component_payload();before=copy.deepcopy(p)
        self.assertTrue(source_review_approved(p));validate_payload(p)
        wb=load_workbook(io.BytesIO(build(p)));master=load_workbook(LOOKUP['Exhaust Fans _Std._.xlsx'])
        try:
            source=master.active;sheet=wb[source.title]
            self.assertEqual(sheet.max_row,84)
            self.assertEqual([sheet[f'H{r}'].value for r in (3,45)],['EF-3','RTU-9 EXHAUST'])
            self.assertEqual(sheet['H59'].value,630);self.assertEqual(sheet['H63'].value,.4)
            self.assertEqual(sheet['U46'].value,2);self.assertEqual(sheet['H51'].value,'AIRFOIL')
            # Parent motor ratings must not silently fill the component form.
            for cell in ('U47','Y47','U48','U49','K59','U60','U64'):
                self.assertIsNone(sheet[cell].value,cell)
            self.assertEqual(sheet['K63'].data_type,'f') # Original calculated actual pressure stays a formula.
            for row in source:
                for original in row:
                    for offset in (0,42):
                        target=sheet.cell(original.row+offset,original.column)
                        if original.data_type=='f':
                            self.assertEqual(target.value,Translator(original.value,origin=original.coordinate).translate_formula(target.coordinate))
                        for attr in ('font','fill','border','alignment','number_format','protection'):
                            self.assertEqual(copy.copy(getattr(target,attr)),copy.copy(getattr(original,attr)),target.coordinate)
            air=next(s for s in wb if 'AIR MOVING' in s.title.upper())
            self.assertEqual(air.max_row,42);self.assertEqual(air['G3'].value,'RTU-9')
            self.assertTrue(any('RECT' in s.title.upper() for s in wb))
            self.assertTrue(any('RND' in s.title.upper() or 'ROUND' in s.title.upper() for s in wb))
        finally:wb.close();master.close()
        self.assertEqual(p,before)

    def test_parent_source_role_and_quantity_cannot_be_forged_even_with_new_approval(self):
        cases=[lambda p:p['records'][1].update(component_of='RTU-88'),
            lambda p:p['records'][1].update(component_kind='return'),
            lambda p:p['records'][1].update(tag='EF-99'),
            lambda p:p['records'][1].update(component_source_sha256='b'*64),
            lambda p:p['records'][1].update(reference='page 3'),
            lambda p:p['records'][1].update(component_note='ok'),
            lambda p:p['records'][1].update(quantity=2),
            lambda p:p['records'][1].update(quantity=True),
            lambda p:p['records'][1].update(template='Air Moving Equipment.xlsx'),
            lambda p:p['records'][1].update(coil_template='COIL DX HP ELE.xlsx'),
            lambda p:p['records'][1].update(instance_locations=['ROOM A']),
            lambda p:p['records'][0].update(quantity=2,instance_locations=['ROOM A','ROOM B']),
            lambda p:p['records'][0].update(status='EXCLUDED'),
            lambda p:p['records'][0].update(status='UNVERIFIED'),
            lambda p:p['records'].append(copy.deepcopy(p['records'][1]))]
        for mutate in cases:
            p=component_payload();mutate(p);p['source_review']['inventory']=inventory_snapshot(p)
            self.assertTrue(component_errors(p));self.assertFalse(source_review_approved(p))
            with self.assertRaises(ValueError):validate_payload(p)

    def test_component_relationship_evidence_and_values_bind_approval(self):
        for key,value in [('component_of','RTU-8'),('component_kind','other'),('component_source_sha256','b'*64),
                          ('component_note','Another human note which requires fresh approval.'),('design_cfm',631)]:
            p=component_payload();p['records'][1][key]=value
            self.assertFalse(source_review_approved(p),key)
        p=component_payload();p.pop('source_review');p['records'][1]['component_source_sha256']='b'*64
        p['scan_acknowledgement']={'acknowledged':True,'note':'I accept an incomplete partial report.','scan_state':p['scan_state']}
        with self.assertRaisesRegex(ValueError,'Integral exhaust source'):validate_payload(p)
        for bad in (None,{},[None]):self.assertTrue(component_errors({'records':bad}))


if __name__=='__main__':unittest.main()
