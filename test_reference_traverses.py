import io,unittest
from openpyxl import load_workbook
from abp_reference import reset_measurements,family
from abp_server import LOOKUP

class ReferenceTraverseTests(unittest.TestCase):
    def test_round_and_oval_actuals_clear_without_changing_geometry_or_formulas(self):
        for filename,point in [('Duct Traverse RND.xlsx','H10'),('Duct Traverse Oval.xlsx','H14')]:
            ws=load_workbook(LOOKUP[filename]).active
            formulas={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}
            ws['D3']='RTU-1';ws['L7']=12;ws[point]=850;ws['D7']=-.25;ws['D6']='PITOT TUBE'
            self.assertTrue(family(ws).startswith('DUCT TRAVERSE'))
            reset_measurements(ws)
            self.assertIsNone(ws[point].value);self.assertIsNone(ws['D7'].value);self.assertIsNone(ws['D6'].value)
            self.assertEqual(ws['D3'].value,'RTU-1');self.assertEqual(ws['L7'].value,12)
            self.assertEqual({c.coordinate:c.value for row in ws for c in row if c.data_type=='f'},formulas)

if __name__=='__main__':unittest.main()
