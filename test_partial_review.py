import copy, io, unittest
from unittest.mock import patch
from openpyxl import load_workbook
import abp_server as app
from abp_review_gate import partial_review_allowed, partial_review_lines


class PartialReviewTests(unittest.TestCase):
    def setUp(self):
        self.state={'status':'incomplete','complete_takeoff':False,
            'source_checkpoints':[{'name':'schedule.pdf','sha256':'a'*64,
                'native_status':'completed_native_stage','image_status':'incomplete'},
                {'name':'failed.pdf','native_status':'incomplete','image_status':'not_started','reason':'wall time limit'}],
            'warnings':['Image coverage incomplete; check the original sources.']}
        self.ack={'acknowledged':True,'note':'Checked the source schedule manually; failed pages remain unresolved.',
                  'scan_state':copy.deepcopy(self.state)}

    def test_ack_required_and_bound_to_exact_coverage(self):
        for ack in (None,{},dict(self.ack,acknowledged=False),dict(self.ack,note='too short')):
            self.assertFalse(partial_review_allowed(self.state,ack))
            with self.assertRaises(ValueError):app.validate_scan_state(self.state,ack)
        app.validate_scan_state(self.state,self.ack)
        for key,value in [('warnings',['Another omission']),('status','stale')]:
            changed=copy.deepcopy(self.state);changed[key]=value
            with self.assertRaises(ValueError):app.validate_scan_state(changed,self.ack)
        changed=copy.deepcopy(self.state);changed['source_checkpoints'][0]['sha256']='b'*64
        self.assertFalse(partial_review_allowed(changed,self.ack))
        self.assertFalse(self.state['complete_takeoff'])

    def test_no_successful_source_cannot_be_acknowledged(self):
        state=copy.deepcopy(self.state);state['source_checkpoints']=state['source_checkpoints'][1:]
        with self.assertRaises(ValueError):app.validate_scan_state(state,dict(self.ack,scan_state=state))

    def test_large_disclosure_rejected_without_truncation(self):
        state=copy.deepcopy(self.state);state['warnings']=['x'*2000]*100
        with self.assertRaisesRegex(ValueError,'no disclosure was truncated'):
            partial_review_lines(state,dict(self.ack,scan_state=state))

    def test_partial_workbook_keeps_template_and_blank_actuals(self):
        # Enough warning lines to exercise multiple intact Notes pages.
        self.state['warnings']=['Review source page '+str(i) for i in range(40)]
        self.ack['scan_state']=copy.deepcopy(self.state)
        payload={'project':'Partial regression','templates':['Exhaust Fans _Sm._.xlsx'],
            'scan_state':self.state,'scan_acknowledgement':self.ack,
            'records':[{'tag':'EF-1','status':'VERIFIED','template':'Exhaust Fans _Sm._.xlsx','design_cfm':75,'esp':0.5}]}
        app.validate_api_scan_state(payload)
        wb=load_workbook(io.BytesIO(app.build(payload)))
        notes=wb['NOTES'];master=load_workbook(app.LOOKUP['Notes.xlsx']).active
        self.assertEqual(notes.max_row%master.max_row,0)
        self.assertGreater(notes.max_row,master.max_row)
        disclosed=[notes.cell(r+off,3).value for off in range(0,notes.max_row,43) for r in range(4,40)]
        self.assertEqual([x for x in disclosed if x],partial_review_lines(self.state,self.ack))
        self.assertIn('DUCT TRAVERSE RECT.',wb.sheetnames);self.assertIn('DUCT TRAVERSE RND',wb.sheetnames)
        fan=wb['EXHAUST FANS SMALL'];self.assertEqual(fan['C10'].value,75);self.assertIsNone(fan['D10'].value)
        self.assertTrue(str(notes['C4'].value).startswith('REVIEWED PARTIAL REPORT'))
        for off in range(0,notes.max_row,43):
            for row in master:
                for cell in row:
                    target=notes.cell(cell.row+off,cell.column)
                    self.assertEqual(target.number_format,cell.number_format)
                    self.assertEqual(copy.copy(target.font),copy.copy(cell.font))
                    if cell.data_type=='f':self.assertEqual(target.value,cell.value)

if __name__=='__main__':unittest.main()
