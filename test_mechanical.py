"""Public synthetic regressions. No customer drawing or workbook is embedded."""
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
import abp_server as app
from abp_design import inferred_form
from abp_mechanical import schedule_candidates, keyed_outlets, packaged_submittals
from abp_schedule import parse_page, resolve_proposed


def word(x, y, text):
    return (x, y, x + len(text)*4, y+9, text, 0, 0, 0)


def fan_words():
    header=[word(10,90,'MARK'),word(200,90,'SCFM'),word(220,90,'@'),word(228,90,'70°F'),
            word(300,90,'ESP'),word(316,90,'(IN'),word(332,90,'W.C.)'),
            word(400,90,'FAN'),word(416,90,'RPM'),
            word(500,90,'MOTOR'),word(524,90,'HP'),word(600,90,'TYPE')]
    return header+[word(10,110,'EF-1'),word(216,110,'75'),word(316,110,'0.25'),
                   word(408,110,'800'),word(512,110,'0.02'),word(596,110,'CEILING')]


class MechanicalTests(unittest.TestCase):
    def test_fan_headers_not_numeric_order(self):
        result=schedule_candidates(fan_words(),1,'schedule')[0]
        self.assertEqual(result['values']['design_cfm'],75)
        self.assertEqual(result['values']['esp'],.25)
        self.assertEqual(result['values']['fan_rpm'],800)
        self.assertEqual(result['values']['motor_hp'],.02)
        # Moving airflow and ESP columns must not swap their meanings.
        changed=[]
        for w in fan_words():
            shift=100 if 190<w[0]<250 else -100 if 290<w[0]<360 else 0
            changed.append((w[0]+shift,w[1],w[2]+shift,*w[3:]))
        self.assertEqual(schedule_candidates(changed,1,'schedule')[0]['values'],result['values'])

    def test_actual_header_is_not_design(self):
        self.assertEqual(schedule_candidates(fan_words()+[word(50,70,'ACTUAL')],1,'readings'),[])

    def test_false_plan_tag_does_not_become_equipment(self):
        self.assertEqual(parse_page([word(10,10,'PAHU-12'),word(70,10,'STUDIO')],1,'plan'),[])
        for tag in ['PAHU-1','MSAH-1','MSHP-1']:
            self.assertTrue(app.TAGS.fullmatch(tag))

    def test_supported_and_unsupported_form_choices(self):
        self.assertEqual(inferred_form('PAHU-1'),'Air Moving Equipment.xlsx')
        self.assertEqual(inferred_form('MSAH-1'),'Fan Coil Units DX.xlsx')
        self.assertEqual(inferred_form('EUH-1'),'Unit Heater ELE.xlsx')
        self.assertIsNone(inferred_form('MSHP-1'))
        self.assertEqual(inferred_form('EF-1',{'proposed':{'design_cfm':75,'motor_hp':.02},
                         'text_proposed':{'service':'CEILING'}}),'Exhaust Fans _Sm._.xlsx')
        self.assertEqual(inferred_form('EF-1'),'Exhaust Fans _Std._.xlsx')

    def test_keyed_grilles_require_note_and_unambiguous_stacked_flow(self):
        words=[word(10,10,'FLOOR'),word(34,10,'PLAN'),word(54,10,'-'),word(62,10,'HVAC'),
               word(600,30,'7.'),word(612,30,'DUCT'),word(632,30,'MOUNTED'),word(664,30,'SUPPLY'),
               word(90,104,'7'),word(100,100,'16x8'),word(101,109,'125'),
               word(200,100,'SB'),word(201,109,'80'),word(300,100,'RB'),word(301,109,'90')]
        out=keyed_outlets(words,1,'plan',{'SB':'8"Ø'})
        self.assertEqual([x['design_cfm'] for x in out],[125,80])
        self.assertTrue(all(x['include'] is False and x['system']==x['location']=='' for x in out))
        self.assertEqual(len(keyed_outlets(words+[word(102,110,'999')],1,'plan',{'SB':'8"Ø'})),1)
        self.assertEqual(keyed_outlets(words[4:],1,'detail',{'SB':'8"Ø'}),[])

    def test_explicit_shared_submittal_and_separate_heat_modes(self):
        import pymupdf
        doc=pymupdf.open();page=doc.new_page()
        for i,line in enumerate(['Unit Tag: PAHU-1, PAHU-2, PAHU-3','Airflow 3000 cfm',
                   'Design ESP 1.000 in H2O','Supply Motor Horsepower 3.000 hp',
                   'Electric Heat','Heat pump EAT 70.00 F','Heat pump LAT 99.00 F',
                   'Heating EAT 70.00 F','Heating LAT 88.00 F']):
            page.insert_text((20,30+i*20),line,fontsize=9)
        found=packaged_submittals(doc,'selection')
        self.assertEqual([r['tag'] for r in found],['PAHU-1','PAHU-2','PAHU-3'])
        self.assertEqual(found[0]['values']['electric_heating_ldb'],88)
        self.assertEqual(found[0]['values']['heating_ldb'],99)
        self.assertNotIn('heating_cfm',found[0]['values'])
        doc.close()

    def test_conflicting_schedule_values_remain_unresolved(self):
        values,flags,_=resolve_proposed([{'values':{'design_cfm':100},'basis':'PLAN_SCHEDULE'},
                                        {'values':{'design_cfm':200},'basis':'PLAN_SCHEDULE'}])
        self.assertNotIn('design_cfm',values);self.assertTrue(flags)

    def test_submittal_strip_temperatures_survive_proposal_resolution(self):
        values,_,_=resolve_proposed([{'values':{'electric_heating_edb':70,'electric_heating_ldb':88},
                                     'basis':'SUBMITTAL_SELECTION'}])
        self.assertEqual(values,{'electric_heating_edb':70,'electric_heating_ldb':88})

    def test_mixed_coil_forms_require_per_unit_selection(self):
        templates=['Air Moving Equipment.xlsx','Coil DX GAS HT.xlsx','COIL DX HP ELE.xlsx']
        records=[{'tag':'RTU-1','template':templates[0],'status':'VERIFIED','design_cfm':1000},
                 {'tag':'PAHU-1','template':templates[0],'status':'VERIFIED','design_cfm':3000}]
        payload={'project':'Mixed heating','templates':templates,'records':records}
        with self.assertRaisesRegex(ValueError,'choose a companion'):
            app.validate_payload(payload)
        records[0]['coil_template']=templates[1];records[1]['coil_template']=templates[2]
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):
            wb=load_workbook(io.BytesIO(app.build(payload)))
        self.assertEqual(wb['COIL DX GAS HT']['D4'].value,'RTU-1')
        self.assertIsNone(wb['COIL DX GAS HT']['F4'].value)
        self.assertEqual(wb['COIL DX HP ELE']['D4'].value,'PAHU-1')
        self.assertIsNone(wb['COIL DX HP ELE']['H4'].value)

    def test_addendum_symbol_without_legend_keeps_size_unresolved(self):
        words=[word(10,10,'FLOOR'),word(34,10,'PLAN'),word(54,10,'-'),word(62,10,'HVAC'),
               word(200,100,'SB'),word(201,109,'80')]
        out=keyed_outlets(words,2,'addendum',{})
        self.assertEqual(len(out),1);self.assertEqual(out[0]['size'],'')
        self.assertFalse(out[0]['include']);self.assertIn('no neck legend',out[0]['evidence'])

    def test_electric_coil_mapping_formula_and_actual_safety(self):
        rec={'tag':'PAHU-1','template':'Air Moving Equipment.xlsx','status':'VERIFIED',
             'design_cfm':3000,'cooling_edb':80,'cooling_ewb':67,'cooling_ldb':57,
             'cooling_lwb':56,'heating_edb':70,'heating_ldb':99,
             'electric_heating_edb':70,'electric_heating_ldb':88}
        payload={'project':'Synthetic packaged','templates':['Air Moving Equipment.xlsx',
                 'COIL DX HP ELE.xlsx'],'records':[rec]}
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):
            data=app.build(payload)
        wb=load_workbook(io.BytesIO(data));ws=wb['COIL DX HP ELE']
        self.assertEqual(ws['D4'].value,'PAHU-1');self.assertEqual(ws['D8'].value,3000)
        self.assertEqual(ws['D22'].value,99);self.assertEqual(ws['D27'].value,88)
        self.assertIsNone(ws['D20'].value) # not inferred from cooling flow
        source=load_workbook(app.TEMPLATES/'COIL DX HP ELE.xlsx').active
        for row in source:
            for c in row:
                if c.data_type=='f':self.assertEqual(ws[c.coordinate].value,c.value)
        for addr in ['E8','E12','E13','E14','E15','E20','E21','E22','E26','E27','E31','E33']:
            self.assertIsNone(ws[addr].value,addr)
        self.assertNotIn('EXHAUST FAN',wb.sheetnames)
        self.assertEqual(wb.sheetnames[:2],['PROJECT INFO','NOTES'])

    def test_unsupported_verified_equipment_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'select a unit report form'):
            app.validate_payload({'project':'Test','templates':['Air Moving Equipment.xlsx'],
                'records':[{'tag':'EUH-1','template':'','status':'VERIFIED','heating_output_btu':6826}]})


if __name__=='__main__':unittest.main()
