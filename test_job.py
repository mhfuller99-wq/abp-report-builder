import io, unittest
from openpyxl import Workbook, load_workbook
from abp_server import TAGS, build, read_sources, validate_payload
from abp_job import performance_candidates, canonical_tag
from abp_reference import reset_measurements

class JobTests(unittest.TestCase):
    def test_spaced_shared_submittal_tags(self):
        text='''Performance Summary
Tag: RTU - 1, 3     Model No: EXAMPLE-300
Airflow (CFM) - CFM: 9,500
External Static Pressure (inches WG) - ESP: 1
System Entering Air (F) - Dry Bulb: 77.2 Wet Bulb: 65.4
Design Net Cooling Capacity(btuh) - Total: 300,900 Sensible: 218,800
Gas Heating Values(btuh) - Input: 400,000 Output: 324,000'''
        result=performance_candidates(text,TAGS)
        self.assertEqual([r['tag'] for r in result],['RTU-1','RTU-3'])
        self.assertEqual(result[1]['values']['model'],'EXAMPLE-300')
        self.assertEqual(result[0]['values']['cooling_total_btu'],300900)
        self.assertEqual(performance_candidates(text+'\nTag: RTU-2',TAGS),[])
        self.assertEqual(canonical_tag('RTU - 12A'),'RTU-12A')

    def test_postal_addresses_not_equipment(self):
        result=read_sources([('notes.csv',b'Tupelo MS 38802\nMS-1\nTupelo, MS 38804\nRTU - 2\n')])
        self.assertEqual(result['tags'],['MS-1','RTU-2'])

    def test_original_style_design_panels_and_blank_readings(self):
        records=[{'tag':f'RTU-{i}','template':'Air Moving Equipment.xlsx','status':'VERIFIED',
                  'design_cfm':9500,'osa_cfm':2500,'osa_min_cfm':750,'esp':1,
                  'model':'EXAMPLE','cooling_edb':77.2,'cooling_ldb':55.9,
                  'cooling_total_btu':300900,'heating_output_btu':324000} for i in range(1,5)]
        payload={'project':'Regression','templates':['Air Moving Equipment.xlsx','Coil DX GAS HT.xlsx','Duct Traverse Rect..xlsx'],
                 'records':records,'layout':'grouped'}
        wb=load_workbook(io.BytesIO(build(payload)))
        for i in range(1,5):
            s=wb[f'RTU-{i}']
            self.assertEqual(s['G18'].value,750)
            self.assertEqual(s['G19'].value,'=G17-G18')
            self.assertEqual(s['G21'].value,1)
            self.assertEqual(s['G6'].value,'EXAMPLE')
            self.assertIsNone(s['J17'].value)
            t=wb[f'RTU-{i} OSA TRAVERSE']
            self.assertEqual(t['L3'].value,2500)
            self.assertEqual(t['L25'].value,750)
            self.assertIsNone(t['B32'].value)
        c=wb['COIL DX GAS 1']
        self.assertEqual(c['D4'].value,'RTU-1')
        self.assertEqual(c['D19'].data_type,'f')
        self.assertEqual(c['D28'].data_type,'f')
        self.assertEqual(wb['COIL DX GAS 2']['D4'].value,'RTU-4')

    def test_every_reference_traverse_panel_is_cleared(self):
        wb=Workbook();s=wb.active;s.title='DUCT TRAVERSE RECT.'
        for off in (0,22,43,65,86,108,129,151):
            s[f'A{3+off}']='UNIT DESIGNATION';s[f'D{3+off}']='RTU-1'
            s[f'L{3+off}']=750;s[f'B{10+off}']=555;s[f'D{7+off}']=.5
        reset_measurements(s)
        for off in (0,22,43,65,86,108,129,151):
            self.assertIsNone(s[f'B{10+off}'].value);self.assertIsNone(s[f'D{7+off}'].value)
            self.assertEqual(s[f'L{3+off}'].value,750)

    def test_outside_air_ranges_are_validated(self):
        for low,high in [(1000,900),(100,None)]:
            with self.assertRaisesRegex(ValueError,'minimum outside air'):
                validate_payload({'project':'Test','templates':['Air Moving Equipment.xlsx'],
                   'records':[{'tag':'RTU-1','status':'VERIFIED','design_cfm':1200,'osa_cfm':high,'osa_min_cfm':low}]})

if __name__=='__main__':unittest.main()
