"""Heater integration tests using original supplied templates and synthetic values."""
import hashlib,io,json,subprocess,unittest,zipfile
from copy import copy
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter
from abp_design import HEATER_FORMS,UNIT_FORMS,inferred_form,extract_design_rows
from abp_mechanical import schedule_candidates
from abp_schedule import annotate
from abp_reference import reset_measurements,inspect_reference,build_reference
import abp_server as app
from test_general_extraction import word

HASHES={'ELE':'6003e11cd5236168ce3d9e07464cc4a1d1fdcb1d33716bc018741bd36acfc28f',
        'GAS':'65a6b27e4ec54ca6e0499b9f5bf637ce4df80766583d74f9cea35ca64d8f68aa',
        'WTR':'418aa487fb2569753db5b03ae67761f0536e1f85bd989b56b364ca70cdf719be'}

class HeaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=[]
        for kind,count,prefix,heat in [('ELE',4,'EUH','ELECTRIC'),('GAS',5,'GUH','GAS'),('WTR',5,'UH','HOT WATER')]:
            for n in range(1,count+1):
                cls.records.append({'tag':f'{prefix}-{n}','status':'VERIFIED','template':f'Unit Heater {kind}.xlsx',
                                    'heating_type':heat,'area_served':f'Test room {n}',
                                    'heating_cfm':200+n,'heating_edb':65,'heating_ldb':95,
                                    'heater_volts':240,'heater_phase':1,'heater_amps':8.3,'heater_stages':2,
                                    'heater_kw':2,'heating_output_btu':6800,
                                    'heating_ewt':180,'heating_lwt':160,'design_gpm':2.5,'water_dp_ft':4})
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):
            cls.output=app.build({'project':'Synthetic heater integration','templates':list(HEATER_FORMS.values()),'records':cls.records})
        cls.wb=load_workbook(io.BytesIO(cls.output))

    def test_original_template_bytes_match_supplied_attachments(self):
        for kind,sha in HASHES.items():
            self.assertEqual(hashlib.sha256(app.LOOKUP[f'Unit Heater {kind}.xlsx'].read_bytes()).hexdigest(),sha)

    def test_correct_types_and_unknown_type_requires_review(self):
        self.assertEqual(inferred_form('EUH-1'),'Unit Heater ELE.xlsx')
        self.assertEqual(inferred_form('GUH-1'),'Unit Heater GAS.xlsx')
        for prefix in ['UH','CUH']:
            self.assertIsNone(inferred_form(prefix+'-1'))
            for heat,form in HEATER_FORMS.items():self.assertEqual(inferred_form(prefix+'-1',{'heating_type':heat}),form)
        self.assertIsNone(inferred_form('EUH-1',{'heating_type':'GAS'}))
        self.assertIsNone(inferred_form('UH-1',{'candidates':[{'text':{'heating_type':'GAS'}},{'text':{'heating_type':'HOT WATER'}}]}))

    def test_typed_recommendations_do_not_select_all_heaters(self):
        def picked(tags,signals=[]):return {r['name'] for r in app.suggested_templates(tags,signals)['recommended']} & set(HEATER_FORMS.values())
        self.assertEqual(picked(['EUH-1']),{'Unit Heater ELE.xlsx'})
        self.assertEqual(picked(['GUH-1']),{'Unit Heater GAS.xlsx'})
        self.assertEqual(picked(['UH-1']),set())
        self.assertEqual(picked(['UH-1'],['unit_heater_hot_water']),{'Unit Heater WTR.xlsx'})

    def test_units_fill_original_slots_then_repeat_pages(self):
        for kind,slots,height,prefix in [('ELE',[3,7,11],40,'EUH'),('GAS',[3,5,7,9],41,'GUH'),('WTR',[3,5,7,9],41,'UH')]:
            ws=self.wb['UNIT HEATER '+kind]
            self.assertEqual(ws.max_row,height*2)
            for n in range(1,len(slots)+2):
                off=(n-1)//len(slots)*height;col=slots[(n-1)%len(slots)]
                self.assertEqual(ws.cell(off+3,col).value,f'{prefix}-{n}')
                self.assertEqual(ws.cell(off+10,col).value,200+n)
                self.assertEqual(ws.cell(off+4,col).value,f'Test room {n}')
                self.assertEqual(ws.cell(off+9,col).value,{'ELE':'ELECTRIC','GAS':'GAS','WTR':'HOT WATER'}[kind])
            self.assertEqual(sum(s.title.startswith('UNIT HEATER '+kind) for s in self.wb),1)
        self.assertEqual(self.wb['UNIT HEATER ELE']['C18'].value,240)
        self.assertEqual(self.wb['UNIT HEATER ELE']['C19'].value,1)
        self.assertEqual(self.wb['UNIT HEATER ELE']['C20'].value,8.3)
        for addr,value in [('C17',180),('C18',160),('C20',2.5),('C21',4)]:self.assertEqual(self.wb['UNIT HEATER WTR'][addr].value,value)

    def test_all_formulas_preserved_and_translated(self):
        for kind in HASHES:
            src=load_workbook(app.LOOKUP[f'Unit Heater {kind}.xlsx']).active;dst=self.wb[src.title]
            expected={}
            for off in [0,src.max_row]:
                for row in src:
                    for c in row:
                        if c.data_type=='f':expected[dst.cell(c.row+off,c.column).coordinate]=Translator(c.value,origin=c.coordinate).translate_formula(row_delta=off)
            self.assertEqual({c.coordinate:c.value for row in dst for c in row if c.data_type=='f'},expected)
        self.assertEqual(self.wb['UNIT HEATER ELE']['C21'].value,'=IF(C18="","",C18*C20*SQRT(C19)/1000)')
        self.assertEqual(self.wb['UNIT HEATER ELE']['C17'].value,'=IF(C21="","",C21*3413)')

    def test_actual_inputs_blank_in_all_phase_legs_and_slots(self):
        for kind in HASHES:
            src=load_workbook(app.LOOKUP[f'Unit Heater {kind}.xlsx']).active;dst=self.wb[src.title]
            cols=[4,5,6,8,9,10,12,13,14] if kind=='ELE' else [4,6,8,10]
            for off in [0,src.max_row]:
                for r in range(10,29 if kind=='ELE' else 30):
                    for c in cols:
                        if src.cell(r,c).value is None:self.assertIsNone(dst.cell(r+off,c).value,(kind,r+off,c))
                for c in range(3,src.max_column+1):self.assertIsNone(dst.cell(off+7,c).value)

    def test_styles_merges_and_print_layout_preserved(self):
        for kind in HASHES:
            src=load_workbook(app.LOOKUP[f'Unit Heater {kind}.xlsx']).active;dst=self.wb[src.title]
            for off in [0,src.max_row]:
                for row in src:
                    for c in row:
                        d=dst.cell(c.row+off,c.column)
                        for attr in ['font','fill','border','alignment','number_format','protection']:
                            self.assertEqual(copy(getattr(c,attr)),copy(getattr(d,attr)),(kind,c.coordinate,off,attr))
                for merge in src.merged_cells.ranges:
                    moved=str(merge) if not off else f'{get_column_letter(merge.min_col)}{merge.min_row+off}:{get_column_letter(merge.max_col)}{merge.max_row+off}'
                    self.assertIn(moved,{str(m) for m in dst.merged_cells.ranges})
            self.assertEqual(dict(dst.page_setup),dict(src.page_setup))
            self.assertEqual(dict(dst.page_margins),dict(src.page_margins))
            self.assertEqual(str(dst.print_area),f"'UNIT HEATER {kind}'!$A$1:${get_column_letter(src.max_column)}${src.max_row*2}")
            self.assertIn(src.max_row,[b.id for b in dst.row_breaks.brk])
            for r,dim in src.row_dimensions.items():self.assertEqual(dst.row_dimensions[r].height,dim.height)

    def test_original_artwork_bytes_survive_export(self):
        with zipfile.ZipFile(io.BytesIO(self.output)) as out:
            artwork={hashlib.sha256(out.read(name)).hexdigest() for name in out.namelist()
                     if '/media/' in name or '/printerSettings/' in name}
        for kind in HASHES:
            with zipfile.ZipFile(app.LOOKUP[f'Unit Heater {kind}.xlsx']) as src:
                originals={hashlib.sha256(src.read(name)).hexdigest() for name in src.namelist()
                           if '/media/' in name or '/printerSettings/' in name}
            self.assertTrue(originals)
            self.assertTrue(originals.issubset(artwork))

    def test_unit_id_design_extraction_ignores_field_readings(self):
        ws=load_workbook(app.LOOKUP['Unit Heater ELE.xlsx']).active
        ws['C3']='EUH-1';ws['C18']=240;ws['C19']=1;ws['C20']=8.3
        ws['D18']=999;ws['E18']=999;ws['F18']=999;ws['D20']=999
        rows=[[None if c.data_type=='f' else c.value for c in row] for row in ws]
        found=extract_design_rows(rows,ws.title,app.TAGS)
        values={k:v for item in found for k,v in item['values'].items()}
        self.assertEqual(values,{'heater_volts':240,'heater_phase':1,'heater_amps':8.3})

    def test_reset_clears_literal_readings_serials_and_signoffs(self):
        for kind in HASHES:
            ws=load_workbook(app.LOOKUP[f'Unit Heater {kind}.xlsx']).active
            for addr in ['C7','D10','D12','D13','D18','D19','D20']:ws[addr]=999
            if kind=='ELE':
                for addr in ['E18','F18','E20','F20','I18','J18','M18','N18']:ws[addr]=999
            comment='A31' if kind=='ELE' else 'A32';ws[comment]='OLD READING'
            ws['B37' if kind=='ELE' else 'B38']='OLD TECH'
            ws['K37' if kind=='ELE' else 'I38']='OLD DATE'
            ws['C18']=240
            formulas={c.coordinate:c.value for row in ws for c in row if c.data_type=='f'}
            reset_measurements(ws)
            self.assertEqual(ws['C18'].value,240)
            self.assertFalse(any(c.value in (999,'OLD READING','OLD TECH','OLD DATE') for row in ws for c in row))
            self.assertEqual({c.coordinate:c.value for row in ws for c in row if c.data_type=='f'},formulas)

    def test_reference_recognizes_unit_id(self):
        info=inspect_reference(self.output)
        self.assertEqual(len(info['units']),14)
        output=load_workbook(io.BytesIO(build_reference(self.output,'Synthetic heater reuse')))
        self.assertEqual(output['UNIT HEATER ELE']['C3'].value,'EUH-1')
        self.assertEqual(output['UNIT HEATER ELE']['C18'].value,240)
        self.assertIsNone(output['UNIT HEATER ELE']['E18'].value)

    def test_no_rating_is_back_calculated_into_inputs(self):
        r=annotate({'tag':'EUH-1','candidates':[{'basis':'PLAN_SCHEDULE','values':{'heater_kw':2,'heating_output_btu':6826}}]})
        self.assertNotIn('heater_kw',r['proposed']);self.assertNotIn('heater_amps',r['proposed'])
        self.assertNotIn('heating_cfm',r['proposed']);self.assertEqual(r['status'],'UNVERIFIED')
        with self.assertRaisesRegex(ValueError,'at least one reviewed design value'):
            app.validate_payload({'project':'Test','templates':['Unit Heater ELE.xlsx'],'records':[{'tag':'EUH-1','status':'VERIFIED','template':'Unit Heater ELE.xlsx','heater_kw':2,'heating_output_btu':6826}]})

    def test_validation_rejects_wrong_form_phase_and_stages(self):
        for change in [{'template':'Unit Heater GAS.xlsx'},{'heater_phase':2},{'heater_stages':1.5}]:
            r={**self.records[0],**change}
            with self.assertRaises(ValueError):app.validate_payload({'project':'Test','templates':list(HEATER_FORMS.values()),'records':[r]})

    def test_header_extraction_uses_heater_columns_not_motor_columns(self):
        words=[word(10,10,'ELECTRIC'),word(46,10,'UNIT'),word(66,10,'HEATER'),word(94,10,'SCHEDULE'),word(10,50,'MARK'),word(160,50,'VOLT'),word(240,50,'PH'),word(320,50,'AMPS'),word(400,50,'(KW)'),word(10,70,'EUH-1'),word(160,70,'480'),word(240,70,'3'),word(320,70,'6'),word(400,70,'5')]
        c=schedule_candidates(words,1,'synthetic.pdf')[0]
        self.assertEqual(c['values'],{'heater_volts':480,'heater_phase':3,'heater_amps':6,'heater_kw':5})
        self.assertEqual(c['text']['heating_type'],'ELECTRIC')
        words += [word(298,50,'MOTOR')]
        self.assertNotIn('heater_amps',schedule_candidates(words,1,'synthetic.pdf')[0]['values'])

    def test_generic_heater_type_comes_from_explicit_schedule_heading(self):
        for title,heat,form in [('HOT WATER UNIT HEATER SCHEDULE','HOT WATER','Unit Heater WTR.xlsx'),
                                ('GAS FIRED UNIT HEATER SCHEDULE','GAS','Unit Heater GAS.xlsx')]:
            words=[];x=10
            for token in title.split():words.append(word(x,10,token));x+=len(token)*4+4
            words += [word(10,50,'MARK'),word(200,50,'CFM'),word(10,70,'UH-1'),word(200,70,'250')]
            candidate=schedule_candidates(words,1,'synthetic.pdf')[0]
            record=annotate({'tag':'UH-1','candidates':[candidate]})
            self.assertEqual(record['text_proposed']['heating_type'],heat)
            self.assertEqual(record['proposed'],{'heating_cfm':250})
            self.assertEqual(inferred_form('UH-1',record),form)

if __name__=='__main__':unittest.main()
