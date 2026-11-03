import io, unittest
from openpyxl import Workbook, load_workbook
from abp_design import extract_design_rows
from abp_server import TAGS, read_sources, build, validate_payload

def packed(wb):
    out=io.BytesIO();wb.save(out);return out.getvalue()

class DesignTests(unittest.TestCase):
    def test_design_and_actual_schedule_columns_are_separate(self):
        result=read_sources([('schedule.csv',b'Tag,Design CFM,Actual CFM,OA CFM,Measured GPM\nRTU-1,1200,9999,100,8888\n')])
        r=result['records'][0]
        self.assertIsNone(r['design_cfm']);self.assertEqual(r['status'],'UNVERIFIED')
        found=[v for c in r['candidates'] for v in c['values'].values()]
        self.assertEqual(found,[1200,100])
        self.assertTrue(all(c['reference'].startswith('schedule.csv!') for c in r['candidates']))

    def test_repeated_grouped_panels_only_read_design_cells(self):
        wb=Workbook();ws=wb.active;ws.title='FAN COIL UNITS WTR'
        for off in (0,44):
            for c,v in {'A3':'UNIT DESIGNATION','C3':f'FCU-{1+off}','E3':f'FCU-{2+off}',
                        'C9':'DESIGN','D9':'ACTUAL','E9':'DESIGN','F9':'ACTUAL','A11':'TOTAL CFM',
                        'C11':700,'D11':9999,'E11':900,'F11':8888,'A12':'OSA CFM','C12':0}.items():
                import re
                col,row=re.fullmatch(r'([A-Z]+)(\d+)',c).groups();ws[f'{col}{int(row)+off}']=v
        result=read_sources([('report.xlsx',packed(wb))])
        for rec in result['records']:
            vals=[v for c in rec['candidates'] for v in c['values'].values()]
            self.assertNotIn(9999,vals);self.assertNotIn(8888,vals)
        r=next(r for r in result['records'] if r['tag']=='FCU-45')
        self.assertIn(700,[v for c in r['candidates'] for v in c['values'].values()])
        self.assertIn(0,[v for c in r['candidates'] for v in c['values'].values()])

    def test_conflicting_revisions_are_not_silently_resolved(self):
        result=read_sources([('rev0.csv',b'Tag,Design CFM\nAHU-1,1000'),('rev1.csv',b'Tag,Design CFM\nAHU-1,1500')])
        r=result['records'][0]
        self.assertEqual([c['values']['design_cfm'] for c in r['candidates']],[1000,1500])
        self.assertIsNone(r['design_cfm'])

    def test_unlabeled_field_notes_not_treated_as_design(self):
        result=read_sources([('notes.csv',b'RTU-1,Measured 9999 CFM\n')])
        self.assertEqual(result['records'][0]['candidates'],[])

    def test_bare_flow_heading_requires_schedule_context(self):
        rows=[['Tag','CFM'],['AHU-1',1234]]
        self.assertEqual(extract_design_rows(rows,'Field Readings',TAGS),[])
        self.assertEqual(extract_design_rows(rows,'AHU Schedule',TAGS)[0]['values'],{'design_cfm':1234})

    def test_formula_design_cells_are_not_guessed_from_old_cache(self):
        wb=Workbook();ws=wb.active;ws.append(['Tag','Design CFM']);ws.append(['RTU-1','=1000+250'])
        self.assertEqual(read_sources([('schedule.xlsx',packed(wb))])['records'][0]['candidates'],[])

    def test_verified_units_populate_selected_master_forms(self):
        forms=[('FCU-1','Fan Coil Units WTR.xlsx','design_cfm',800,'C11','D11'),
               ('IDU-2','Fan Coil Units DX.xlsx','design_cfm',650,'C11','D11'),
               ('TEF-1','Exhaust Fans _Sm._.xlsx','design_cfm',90,'C10','D10'),
               ('KH-1','Kitchen Hood.xlsx','design_cfm',2000,'D6','D7'),
               ('CH-1','Chiller - Air Cooled.xlsx','design_gpm',100,'C17','D17')]
        payload={'project':'Synthetic regression','templates':[x[1] for x in forms],
                 'records':[{'tag':tag,'template':form,field:value,'status':'VERIFIED'} for tag,form,field,value,_,_ in forms]}
        out=load_workbook(io.BytesIO(build(payload)))
        for tag,form,field,value,cell,actual in forms:
            self.assertIn(tag,out.sheetnames);self.assertEqual(out[tag][cell].value,value)
            self.assertTrue(out[tag][actual].value is None or out[tag][actual].data_type=='f')
        self.assertTrue(out['KH-1']['D7'].value.startswith('=IF('))

    def test_unsupported_verified_unit_cannot_disappear(self):
        with self.assertRaisesRegex(ValueError,'select a unit report form'):
            validate_payload({'project':'Test','templates':['Air Moving Equipment.xlsx'],
                              'records':[{'tag':'P-1','design_gpm':30,'status':'VERIFIED'}]})
        with self.assertRaisesRegex(ValueError,'supported by its form'):
            validate_payload({'project':'Test','templates':['Chiller - Air Cooled.xlsx'],
                              'records':[{'tag':'CH-1','template':'Chiller - Air Cooled.xlsx','design_cfm':1000,'status':'VERIFIED'}]})

    def test_corpus_observed_tag_families(self):
        for tag in ('IDU-1','MSFC-2','PTAC-3','CEF-4','SEF-5','IHP-6','HPBC-7','ACC-1','PCP-1','SCP-1','B-1'):
            self.assertIsNotNone(TAGS.fullmatch(tag),tag)

    def test_decimal_and_letter_tags_remain_distinct(self):
        tags=['IU-1.01','IU-1.02','IU-2.11A','KH-5.1','KH-5.2','AH-1.2','ACU-1','PAC-1.1','KSF-1','RTU-1A']
        data=('Tag,Design CFM,Actual CFM\n'+'\n'.join(f'{tag},100,9999' for tag in tags)).encode()
        result=read_sources([('schedule.csv',data)])
        self.assertEqual(result['tags'],tags)
        for record in result['records']:
            self.assertEqual(record['candidates'][0]['values'],{'design_cfm':100})
            self.assertEqual(record['status'],'UNVERIFIED')

    def test_ambiguous_archive_alias_requires_unit_form(self):
        with self.assertRaisesRegex(ValueError,'select a unit report form'):
            validate_payload({'project':'Test','templates':['Air Moving Equipment.xlsx'],
                              'records':[{'tag':'AH-1.2','design_cfm':100,'status':'VERIFIED'}]})

if __name__=='__main__':unittest.main()
