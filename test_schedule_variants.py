"""Invented schedule geometries; no customer source data or filenames."""
import unittest
from abp_mechanical import schedule_candidates,expand_marks,keyed_outlets
from abp_design import inferred_form
from abp_schedule import parse_page,resolve_proposed

def w(x,y,text):return (x,y,x+len(text)*4,y+9,text,0,0,0)

class ScheduleVariants(unittest.TestCase):
    def test_stacked_id_columns(self):
        words=[w(10,70,'ID'),w(150,55,'SUPPLY'),w(150,70,'CFM'),w(250,55,'OUTDOOR'),w(250,70,'CFM'),
               w(10,95,'RTU-7'),w(150,95,'950'),w(250,95,'125')]
        values=schedule_candidates(words,1,'synthetic.pdf')[0]['values']
        self.assertEqual(values['design_cfm'],950)
        self.assertEqual(values['osa_cfm'],125)
        for label in ['Actual','actual','ACTUAL']:
            self.assertEqual(schedule_candidates(words+[w(100,60,label)],1,'synthetic.pdf'),[])

    def test_multilevel_mark_is_not_fan_range(self):
        self.assertEqual(expand_marks('BCU-3-7'),['BCU-3-7'])
        self.assertEqual(expand_marks('EF-3-5'),['EF-3','EF-4','EF-5'])
        self.assertEqual(inferred_form('BCU-3-7',{'text_proposed':{'heating_type':'HOT WATER'}}),'Fan Coil Units WTR.xlsx')
        self.assertIsNone(inferred_form('BCU-3-7'))
        found=parse_page([w(10,10,'ROOM'),w(50,10,'BCU-3-7')],1,'synthetic.pdf')
        self.assertEqual([x['tag'] for x in found],['BCU-3-7'])
        self.assertEqual(found[0]['values'],{})

    def test_raster_style_callout_requires_neck_flow_pair(self):
        words=[w(0,0,'MECHANICAL'),w(44,0,'CEILING'),w(76,0,'PLAN'),
               w(100,100,'Q'),w(111,95,'9"Ø'),w(111,105,'175'),w(200,100,'Q')]
        found=keyed_outlets(words,2,'synthetic.pdf',{})
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['design_cfm'],175)
        self.assertFalse(found[0]['include'])
        self.assertEqual(found[0]['system'],'')

    def test_offset_cfm_and_explicit_quantity(self):
        words=[w(0,0,'HVAC'),w(20,0,'PLAN'),w(100,100,'R-7'),w(80,112,'180'),w(96,112,'CFM'),w(90,124,'(TYP-3)')]
        found=keyed_outlets(words,2,'synthetic.pdf',{'R-7':'12x6'})
        self.assertEqual(len(found),3)
        self.assertTrue(all(x['design_cfm']==180 and not x['include'] for x in found))

    def test_revisions_do_not_silently_overwrite_design(self):
        proposed,flags,_=resolve_proposed([{'basis':'PLAN_SCHEDULE','values':{'design_cfm':420}},
                                           {'basis':'PLAN_SCHEDULE','values':{'design_cfm':480}}])
        self.assertNotIn('design_cfm',proposed)
        self.assertTrue(any('disagree' in f for f in flags))

    def test_symbol_key_example_is_not_physical_outlet(self):
        words=[w(0,0,'HVAC'),w(20,0,'PLAN'),w(100,100,'SB'),w(100,115,'200'),w(180,100,'INDICATES')]
        self.assertEqual(keyed_outlets(words,1,'synthetic.pdf',{'SB':'8"Ø'}),[])

    def test_water_companion_preserves_formulas_and_actuals(self):
        import io
        from unittest.mock import patch
        from openpyxl import load_workbook
        import abp_server as app
        name='Coil WTR CLG WTR HT.xlsx'
        row={'tag':'OAU-7','status':'VERIFIED','template':'Air Moving Equipment.xlsx',
             'coil_template':name,'design_cfm':950,'cooling_edb':82,'cooling_ewb':68,
             'cooling_ldb':54,'cooling_lwb':53,'heating_edb':54,'heating_ldb':72}
        with patch.object(app,'BLANK_RECT_FORMS',0),patch.object(app,'BLANK_RND_FORMS',0):
            raw=app.build({'project':'Synthetic water coil','templates':['Air Moving Equipment.xlsx',name],'records':[row]})
        book=load_workbook(io.BytesIO(raw))
        sheet=next(s for s in book if s['D3'].value=='OAU-7')
        self.assertEqual(sheet['D6'].value,950)
        self.assertEqual(sheet['F11'].value,82)
        self.assertEqual(sheet['H13'].value,72)
        source=load_workbook(app.LOOKUP[name]).active
        for cells in source:
            for cell in cells:
                if cell.data_type=='f':self.assertEqual(sheet[cell.coordinate].value,cell.value)
        for col in ['E','G','I']:
            for r in [6,11,12,13,14,17,18,20,21]:
                if source[f'{col}{r}'].value is None:self.assertIsNone(sheet[f'{col}{r}'].value)
        self.assertEqual(sheet.print_area,source.print_area)

    def test_mixed_water_and_dx_forms_require_per_unit_choice(self):
        import abp_server as app
        with self.assertRaisesRegex(ValueError,'choose a companion coil'):
            app.validate_payload({'project':'Synthetic','templates':['Air Moving Equipment.xlsx','Coil WTR CLG WTR HT.xlsx','Coil DX GAS HT.xlsx'],
                                  'records':[{'tag':'OAU-7','status':'VERIFIED','template':'Air Moving Equipment.xlsx','design_cfm':950}]})

if __name__=='__main__':unittest.main()
