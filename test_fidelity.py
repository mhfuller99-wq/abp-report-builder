import io,unittest,zipfile
from copy import copy
from openpyxl import load_workbook
from abp_server import build,LOOKUP
from abp_reference import build_reference
from abp_fidelity import sheet_paths,NS
import xml.etree.ElementTree as ET

def formulas(data,title):
    with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(files[sheet_paths(files)[title]])
    return {c.attrib['r']:(c.find('{'+NS+'}f').text,c.find('{'+NS+'}f').attrib) for c in root.iter('{'+NS+'}c') if c.find('{'+NS+'}f') is not None}

class FidelityTests(unittest.TestCase):
    def test_every_master_preserves_formula_xml_and_formatting(self):
        for name,path in LOOKUP.items():
            with self.subTest(template=name):
                original=path.read_bytes();src=load_workbook(io.BytesIO(original))
                generated=build({'project':'Template fidelity','templates':[name]})
                dst=load_workbook(io.BytesIO(generated))
                for s in src:
                    d=dst[s.title]
                    self.assertEqual(formulas(original,s.title),formulas(generated,d.title))
                    self.assertEqual(set(map(str,s.merged_cells.ranges)),set(map(str,d.merged_cells.ranges)))
                    for row in s:
                        for c in row:
                            for attr in ('font','fill','border','alignment','number_format','protection'):
                                self.assertEqual(copy(getattr(c,attr)),copy(getattr(d[c.coordinate],attr)),(name,c.coordinate,attr))
                    for attr in ('page_setup','page_margins','print_options','HeaderFooter','row_breaks','col_breaks','sheet_format','protection','data_validations'):
                        self.assertEqual(ET.tostring(getattr(s,attr).to_tree()),ET.tostring(getattr(d,attr).to_tree()),(name,attr))
                    self.assertEqual(str(s.print_area),str(d.print_area))
                    for key,dim in s.row_dimensions.items():
                        self.assertEqual({k:v for k,v in dict(dim).items() if k!='s'},{k:v for k,v in dict(d.row_dimensions[key]).items() if k!='s'},(name,'row',key))
                        for attr in ('font','fill','border','alignment','number_format','protection'):
                            self.assertEqual(copy(getattr(dim,attr)),copy(getattr(d.row_dimensions[key],attr)),(name,'row',key,attr))
                    for key,dim in s.column_dimensions.items():
                        self.assertEqual({k:v for k,v in dict(dim).items() if k!='style'},{k:v for k,v in dict(d.column_dimensions[key]).items() if k!='style'},(name,'column',key))
                        for attr in ('font','fill','border','alignment','number_format','protection'):
                            self.assertEqual(copy(getattr(dim,attr)),copy(getattr(d.column_dimensions[key],attr)),(name,'column',key,attr))

    def test_populated_forms_do_not_replace_calculations(self):
        payload={'project':'Test','layout':'grouped','templates':['Air Moving Equipment.xlsx','Coil DX GAS HT.xlsx'],
                 'records':[{'tag':'RTU-1','status':'VERIFIED','template':'Air Moving Equipment.xlsx','design_cfm':9500,'osa_cfm':2500,'osa_min_cfm':750,'cooling_total_btu':300900}]}
        data=build(payload);w=load_workbook(io.BytesIO(data))
        for name,sheet in [('Air Moving Equipment.xlsx','RTU-1'),('Coil DX GAS HT.xlsx','COIL DX GAS 1')]:
            source=LOOKUP[name].read_bytes();s=load_workbook(io.BytesIO(source)).worksheets[0]
            self.assertEqual(formulas(source,s.title),formulas(data,sheet))
        self.assertEqual(w['RTU-1']['G18'].value,750)
        self.assertEqual(w['RTU-1']['G19'].value,'=G17-G18')
        self.assertEqual(w['COIL DX GAS 1']['D19'].data_type,'f')

if __name__=='__main__':unittest.main()
