import io,unittest
from copy import copy
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
import abp_server as app

class DiffuserTemplateTests(unittest.TestCase):
    def test_overflow_uses_original_forms_without_losing_outlets(self):
        outlets=[{'type':'A','size':'6"','system':'DOAS-1','location':'Room '+str(i),'design_cfm':i} for i in range(1,117)]
        data=app.build({'project':'Overflow','templates':['Supply Diffusers.xlsx'],'diffusers':outlets})
        w=load_workbook(io.BytesIO(data));s=w['SUPPLY DIFFUSERS'];master=load_workbook(app.LOOKUP['Supply Diffusers.xlsx']).active
        self.assertEqual(s.max_row,42*5)
        values=[]
        for page in range(5):
            off=42*page
            for row in range(6,34):
                if s.cell(row+off,3).value is not None:values.append(s.cell(row+off,7).value)
                self.assertIsNone(s.cell(row+off,6).value);self.assertIsNone(s.cell(row+off,8).value)
            for row in master:
                for cell in row:
                    dst=s.cell(cell.row+off,cell.column)
                    if cell.data_type=='f':self.assertEqual(dst.value,Translator(cell.value,origin=cell.coordinate).translate_formula(row_delta=off))
                    for attr in ('font','fill','border','alignment','number_format','protection'):
                        self.assertEqual(copy(getattr(cell,attr)),copy(getattr(dst,attr)))
        self.assertEqual(values,list(range(1,117)))
        self.assertEqual(len([x for x in w.sheetnames if x.startswith('SUPPLY DIFFUSERS')]),1)
        self.assertEqual(s['I6'].value,'=IF(H6=0,"",H6/G6)')

if __name__=='__main__':unittest.main()
