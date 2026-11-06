import io,unittest
from copy import copy
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
import abp_server as app

class DiffuserTemplateTests(unittest.TestCase):
    def test_excluded_exhaust_and_system_numbering(self):
        outlets=[{'type':'A','size':'8"','system':'EF-1','design_cfm':225,'include':False},
                 {'type':'A','size':'6"','system':'DOAS-1','design_cfm':25,'include':True},
                 {'type':'A','size':'8"','system':'DOAS-2','design_cfm':100,'include':True}]
        w=load_workbook(io.BytesIO(app.build({'project':'Duct review','templates':['Supply Diffusers.xlsx'],'diffusers':outlets})))
        s=w['SUPPLY DIFFUSERS']
        self.assertEqual(s.max_row,84)
        self.assertEqual((s['A5'].value,s['C6'].value,s['G6'].value),('DOAS-1',1,25))
        self.assertEqual((s['A47'].value,s['C48'].value,s['G48'].value),('DOAS-2',1,100))
        self.assertEqual(s['G69'].value,'=SUM(G48:G68)')

    def test_overflow_uses_original_forms_without_losing_outlets(self):
        outlets=[{'type':'A','size':'6"','system':'DOAS-1','location':'Room '+str(i),'design_cfm':i} for i in range(1,117)]
        data=app.build({'project':'Overflow','templates':['Supply Diffusers.xlsx'],'diffusers':outlets})
        w=load_workbook(io.BytesIO(data));s=w['SUPPLY DIFFUSERS'];master=load_workbook(app.LOOKUP['Supply Diffusers.xlsx']).active
        self.assertEqual(s.max_row,42*6)
        values=[]
        for page in range(6):
            off=42*page
            for row in range(6,27):
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
        self.assertEqual(s['A5'].value,'DOAS-1')
        self.assertEqual(s['A6'].value,'Room 1')
        self.assertEqual(s['E6'].value,6)
        self.assertEqual(s['G27'].value,'=SUM(G6:G26)')
        self.assertEqual(s['I6'].value,'=IF(H6=0,"",H6/G6)')

if __name__=='__main__':unittest.main()
