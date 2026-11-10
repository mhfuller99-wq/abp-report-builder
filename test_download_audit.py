import io,unittest,zipfile,xml.etree.ElementTree as ET
from copy import copy
from unittest.mock import patch
from openpyxl import load_workbook
import abp_server as app
from abp_audit import audit_report
from abp_fidelity import sheet_paths,NS

class DownloadAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real=audit_report
        def capture(data,origins):cls.origins=origins;return real(data,origins)
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1),patch('abp_audit.audit_report',side_effect=capture):
            cls.good=app.build({'project':'Audit fixture','templates':['Supply Diffusers.xlsx','Exhaust Fans _Sm._.xlsx'],
                'records':[{'tag':'EF-1','status':'VERIFIED','template':'Exhaust Fans _Sm._.xlsx','design_cfm':75,'esp':.5}],
                'diffusers':[{'system':'RTU-1','location':'Room','type':'A','size':'10','design_cfm':400,'include':True},
                             {'system':'RTU-2','location':'Room','type':'B','size':'12','design_cfm':500,'include':True}]})
    def changed(self,edit):
        # Mutate only the intended XML part; a library round-trip would also
        # discard legacy header artwork and obscure the failure under test.
        with zipfile.ZipFile(io.BytesIO(self.good)) as z:files={n:z.read(n) for n in z.namelist()}
        paths=sheet_paths(files);edit(files,paths);out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for name,value in files.items():z.writestr(name,value)
        return out.getvalue()
    def cell_change(self,address,kind,value):
        def edit(files,paths):
            path=paths['SUPPLY DIFFUSERS'];root=ET.fromstring(files[path]);cell=next(c for c in root.iter('{'+NS+'}c') if c.get('r')==address)
            if kind=='style':
                other=next(c for c in root.iter('{'+NS+'}c') if c.get('r')=='A2');cell.set('s',other.get('s'))
            else:
                child=cell.find('{'+NS+'}'+kind)
                if child is None:child=ET.SubElement(cell,'{'+NS+'}'+kind)
                child.text=value;cell.attrib.pop('t',None)
            files[path]=ET.tostring(root)
        return edit
    def test_valid_download_and_translated_page_formulas(self):
        result=audit_report(self.good,self.origins);self.assertGreater(result['formulas'],60);self.assertGreater(result['measurement_inputs'],40)
    def test_changed_formula_blocks_download(self):
        with self.assertRaisesRegex(ValueError,'formula changed'):
            audit_report(self.changed(self.cell_change('I48','f','H6/G6')),self.origins)
    def test_actual_input_blocks_download(self):
        with self.assertRaisesRegex(ValueError,'measurement'):
            audit_report(self.changed(self.cell_change('H6','v','400')),self.origins)
    def test_changed_format_blocks_download(self):
        with self.assertRaisesRegex(ValueError,'formatting changed'):audit_report(self.changed(self.cell_change('G6','style','')),self.origins)
    def test_missing_traverse_blocks_download(self):
        def edit(files,paths):
            root=ET.fromstring(files['xl/workbook.xml']);sheets=root.find('{'+NS+'}sheets')
            sheets.remove(next(s for s in sheets if s.get('name')=='DUCT TRAVERSE RND'));files['xl/workbook.xml']=ET.tostring(root)
        with self.assertRaisesRegex(ValueError,'worksheet grouping changed'):audit_report(self.changed(edit),self.origins)

if __name__=='__main__':unittest.main()
