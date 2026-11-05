import io,unittest,zipfile
from copy import copy
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from abp_server import build,LOOKUP
from abp_fidelity import sheet_paths,NS,REL,DOCREL,relpath,resolve
import xml.etree.ElementTree as ET

class GroupedTests(unittest.TestCase):
    def test_repeated_pages_keep_styles_formulas_artwork_and_print_breaks(self):
        records=[{'tag':f'RTU-{i}','status':'VERIFIED','design_cfm':i*1000,'osa_cfm':i*100} for i in range(1,4)]
        data=build({'project':'Grouped','templates':['Air Moving Equipment.xlsx'],'records':records})
        w=load_workbook(io.BytesIO(data));s=load_workbook(LOOKUP['Air Moving Equipment.xlsx']).active;d=w[s.title]
        self.assertEqual(d.max_row,126)
        self.assertEqual([b.id for b in d.row_breaks.brk],[42,84])
        self.assertIn('$Y$126',str(d.print_area))
        for off in (0,42,84):
            for row in s:
                for c in row:
                    target=d.cell(c.row+off,c.column)
                    if c.data_type=='f':self.assertEqual(target.value,Translator(c.value,origin=c.coordinate).translate_formula(row_delta=off))
                    for attr in ('font','fill','border','alignment','number_format','protection'):
                        self.assertEqual(copy(getattr(c,attr)),copy(getattr(target,attr)),(off,c.coordinate,attr))
            self.assertEqual(d[f'G{3+off}'].value,'RTU-'+str(off//42+1))
            self.assertIsNone(d[f'J{17+off}'].value)
        with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
        path=sheet_paths(files)[s.title];root=ET.fromstring(files[path]);rid=root.find('{'+NS+'}drawing').attrib['{'+DOCREL+'}id']
        links={r.attrib['Id']:r for r in ET.fromstring(files[relpath(path)])}
        drawing=ET.fromstring(files[resolve(path,links[rid].attrib['Target'])])
        with zipfile.ZipFile(LOOKUP['Air Moving Equipment.xlsx']) as z:original={n:z.read(n) for n in z.namelist()}
        op=sheet_paths(original)[s.title];root=ET.fromstring(original[op]);rid=root.find('{'+NS+'}drawing').attrib['{'+DOCREL+'}id']
        links={r.attrib['Id']:r for r in ET.fromstring(original[relpath(op)])}
        source_drawing=ET.fromstring(original[resolve(op,links[rid].attrib['Target'])])
        self.assertEqual(len(drawing),len(source_drawing)*3)
        rows=[int(e.text) for e in drawing.iter() if e.tag.endswith('}row')]
        n=len([e for e in source_drawing.iter() if e.tag.endswith('}row')])
        self.assertEqual(rows[n:2*n],[v+42 for v in rows[:n]])

    def test_existing_multi_unit_slots_then_new_page(self):
        for name,prefix,capacity,height,tagcell in [('Exhaust Fans _Sm._.xlsx','EF',8,36,'C3'),('Fan Coil Units DX.xlsx','FCU',4,41,'C3'),('Fan Coil Units WTR.xlsx','BCU',4,43,'C3')]:
            with self.subTest(name=name):
                source=load_workbook(LOOKUP[name]).active;height=source.max_row
                records=[{'tag':f'{prefix}-{i}','template':name,'status':'VERIFIED','design_cfm':i*100} for i in range(1,capacity+2)]
                w=load_workbook(io.BytesIO(build({'project':'Packed','templates':[name],'records':records})))
                s=w[source.title]
                self.assertEqual(s['C3'].value,prefix+'-1');self.assertEqual(s['I3'].value,prefix+'-4')
                if capacity==8:self.assertEqual(s['I16'].value,prefix+'-8')
                self.assertEqual(s[f'C{height+3}'].value,prefix+'-'+str(capacity+1))
                self.assertEqual(s.max_row,height*2)
                self.assertIsNone(s['D10'].value if capacity==8 else s['D11'].value)

if __name__=='__main__':unittest.main()
