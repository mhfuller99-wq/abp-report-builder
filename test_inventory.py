import io,unittest
from copy import deepcopy,copy
from openpyxl import load_workbook
from abp_inventory import validate_inventory,expand_instances
from abp_server import build,LOOKUP,validate_payload


class InventoryTests(unittest.TestCase):
    def record(self):
        return {'tag':'EF-9','status':'VERIFIED','template':'Exhaust Fans _Sm._.xlsx',
                'quantity':2,'instance_locations':['ROOM A','ROOM B'],'manufacturer':'SYNTHETIC',
                'model':'FAN MODEL','service':'CEILING','design_cfm':90,'esp':.3}

    def test_missing_quantity_and_locations_cannot_silently_drop_units(self):
        r=self.record();r.pop('quantity');r.pop('instance_locations')
        r['candidates']=[{'values':{'quantity':2}}]
        with self.assertRaisesRegex(ValueError,'review the source quantity'):validate_inventory([r])
        r=self.record();r['instance_locations']=['ROOM A']
        with self.assertRaisesRegex(ValueError,'one distinct'):validate_inventory([r])
        r['instance_locations']=['ROOM A','room a']
        with self.assertRaisesRegex(ValueError,'one distinct'):validate_inventory([r])
        for bad in [0,1.5,101,True,float('inf'),'two']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_inventory([{**self.record(),'quantity':bad}])

    def test_expansion_preserves_printed_tag_and_source_record(self):
        r=self.record();original=deepcopy(r);result=expand_instances([r])
        self.assertEqual([x['tag'] for x in result],['EF-9','EF-9'])
        self.assertEqual([x['area_served'] for x in result],['ROOM A','ROOM B'])
        self.assertEqual(r,original)
        self.assertEqual(len(expand_instances([{**r,'status':'UNVERIFIED'}])),1)

    def test_grouped_original_form_contains_each_physical_unit(self):
        r=self.record();other={**r,'tag':'EF-10','quantity':1,'instance_locations':['ROOM C'],'design_cfm':140}
        output=build({'project':'QUANTITY REGRESSION','templates':[r['template']],'records':[r,other]})
        source=load_workbook(LOOKUP[r['template']]).active
        workbook=load_workbook(io.BytesIO(output));sheet=workbook[source.title]
        self.assertEqual([sheet[f'{c}3'].value for c in 'CEG'],['EF-9','EF-9','EF-10'])
        self.assertEqual([sheet[f'{c}7'].value for c in 'CEG'],['ROOM A','ROOM B','ROOM C'])
        self.assertEqual([sheet[f'{c}10'].value for c in 'CEG'],[90,90,140])
        self.assertEqual([sheet[f'{c}4'].value for c in 'CEG'],['SYNTHETIC']*3)
        self.assertTrue(all(sheet[f'{c}10'].value is None for c in 'DFH'))
        for row in source:
            for cell in row:
                target=sheet[cell.coordinate]
                if cell.data_type=='f':self.assertEqual(target.value,cell.value)
                for attr in ('font','fill','border','alignment','number_format','protection'):
                    self.assertEqual(copy(getattr(target,attr)),copy(getattr(cell,attr)))
        self.assertTrue(any('RECT' in name.upper() for name in workbook.sheetnames))
        self.assertTrue(any('RND' in name.upper() or 'ROUND' in name.upper() for name in workbook.sheetnames))

    def test_reviewed_nameplate_speed_does_not_populate_measured_fan_speed(self):
        record={'tag':'AHU-7','status':'VERIFIED','template':'Air Moving Equipment.xlsx',
                'motor_rpm':1075,'motor_hp':.5,'motor_volts':120,'motor_phase':1,'design_cfm':800,'fan_rpm':854}
        book=load_workbook(io.BytesIO(build({'project':'NAMEPLATE','templates':[record['template']],'records':[record]})))
        original=load_workbook(LOOKUP[record['template']]).active;sheet=book[original.title]
        self.assertEqual(sheet['T7'].value,1075)
        self.assertEqual(sheet['T5'].value,120)
        self.assertEqual(sheet['X5'].value,1)
        self.assertIsNone(sheet['T18'].value)
        self.assertIsNone(sheet['T22'].value)
        for bad_phase in (0,2,True,1.5):
            with self.subTest(bad_phase=bad_phase),self.assertRaisesRegex(ValueError,'motor phase'):
                validate_payload({'project':'NAMEPLATE','templates':[record['template']],
                                  'records':[{**record,'motor_phase':bad_phase}]})
        for row in original:
            for cell in row:
                if cell.data_type=='f':self.assertEqual(sheet[cell.coordinate].value,cell.value)


if __name__=='__main__':unittest.main()
