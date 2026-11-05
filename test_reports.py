import io
import unittest
import http.client
import threading
import json
from openpyxl import Workbook, load_workbook
from abp_reference import build_reference, inspect_reference
from abp_server import TAGS, suggested_templates, read_sources
import abp_server


def packed(wb):
    out=io.BytesIO();wb.save(out);return out.getvalue()


class ReportTests(unittest.TestCase):
    def test_restaurant_repeated_forms_are_pre_field(self):
        wb=Workbook();ws=wb.active;ws.title='AIR MOVING EQUIPMENT'
        for off in (0,43):
            for col,row,value in [('A',3,'UNIT DESIGNATION'),('G',3,f'RTU-{off+1}'),
                                  ('G',7,'old serial'),('G',17,1800),('J',17,1774),
                                  ('A',29,-.5),('W',29,.3),('T',17,208),('T',18,3),
                                  ('T',20,5),('J',37,'DIRTY'),('N',36,'Old observation'),
                                  ('A',42,'TECHNICIAN:'),('E',42,'Old tech'),
                                  ('Q',42,'TEST DATE:'),('U',42,'Old date')]:
                ws[f'{col}{row+off}']=value
        hood=wb.create_sheet('KITCHEN HOOD')
        for cell,val in {'A3':'UNIT DESIGNATION','D3':'KH-1','D6':2500,'J3':'16X16',
                         'D11':118,'D12':2.1,'D13':'=D11*D12','D7':'=SUM(D13:M13)',
                         'K7':'VELGRID'}.items():hood[cell]=val
        traverse=wb.create_sheet('DUCT TRAVERSE RECT.')
        for cell,val in {'L3':1550,'L7':28,'M7':18,'N7':'=M7*L7/144','B10':394,
                         'N4':'=AVERAGE(B10:O18)','N3':'=N4*N7'}.items():traverse[cell]=val
        small=wb.create_sheet('EXHAUST FANS SMALL')
        for cell,val in {'A3':'UNIT DESIGNATION','C3':'TEF-1','C9':'DESIGN','D9':'ACTUAL',
                         'C10':100,'D10':58,'D11':'--'}.items():small[cell]=val
        result=load_workbook(io.BytesIO(build_reference(packed(wb),'Example')))
        for off in (0,43):
            self.assertEqual(result.worksheets[0][f'G{17+off}'].value,1800)
            for col,row in [('G',7),('J',17),('A',29),('W',29),('T',17),('T',18),
                            ('T',20),('J',37),('N',36),('E',42),('U',42)]:
                self.assertIsNone(result.worksheets[0][f'{col}{row+off}'].value)
            self.assertEqual(result.worksheets[0][f'Q{42+off}'].value,'TEST DATE:')
        self.assertEqual(result['KITCHEN HOOD']['D6'].value,2500)
        self.assertIsNone(result['KITCHEN HOOD']['D12'].value)
        self.assertEqual('=D11*D12',result['KITCHEN HOOD']['D13'].value)
        self.assertIsNone(result['DUCT TRAVERSE RECT.']['B10'].value)
        self.assertIn('M7*L7/144',result['DUCT TRAVERSE RECT.']['N7'].value)
        self.assertEqual(result['DUCT TRAVERSE RECT.']['N7'].value,'=M7*L7/144')
        self.assertIsNone(result['EXHAUST FANS SMALL']['D10'].value)
        self.assertLessEqual(result['EXHAUST FANS SMALL'].max_row,16)

    def test_cover_is_not_certified_and_old_certificates_removed(self):
        wb=Workbook();ws=wb.active;ws.title='Cover '
        ws['A7']='CERTIFIED\nANALYSIS REPORT';ws['A5']='Old report date'
        ws['B30']='These measurements are certified accurate.'
        ws['B37']='APPROVED BY:';ws['B39']='Old approver'
        inst=wb.create_sheet('INSTRUMENT');inst['A3']='Instrument';inst['A4']='Manometer'
        inst['D4']='Old serial';inst['E4']='Old calibration date'
        unit=wb.create_sheet('EXHAUST FAN');unit['B3']='UNIT DESIGNATION';unit['H3']='KEF-1'
        result=load_workbook(io.BytesIO(build_reference(packed(wb),'Example')))
        self.assertEqual(ws['A7'].value,result['Cover ']['A7'].value)
        self.assertIsNone(result['Cover ']['B39'].value)
        self.assertEqual(ws['B30'].value,result['Cover ']['B30'].value)
        self.assertIsNone(result['INSTRUMENT']['D4'].value)
        self.assertEqual(result['INSTRUMENT']['A4'].value,'Manometer')

    def test_restaurant_tags(self):
        self.assertEqual([m.group() for m in TAGS.finditer('KH-1 KEF-1 TEF-2 MAU-1')],
                         ['KH-1','KEF-1','TEF-2','MAU-1'])
        names=[r['name'] for r in suggested_templates(['KH-1','KEF-1','TEF-2'])['recommended']]
        self.assertIn('Kitchen Hood.xlsx',names)
        self.assertIn('Exhaust Fans _Std._.xlsx',names)

    def test_hydronic_tags_and_false_standard(self):
        self.assertEqual([m.group() for m in TAGS.finditer('BC-1 BCU-12 CH-1 P-1 FCU-3 RTU1')],
                         ['BC-1','BCU-12','CH-1','P-1','FCU-3','RTU1'])
        scanned=read_sources([('spec.csv',b'IAS AC89 - Accreditation Criteria for Testing Laboratories\nBCU-1\n')])
        self.assertEqual(scanned['tags'],['BCU-1'])
        names=[r['name'] for r in suggested_templates(['BCU-1','CH-1'])['recommended']]
        self.assertIn('Fan Coil Units WTR.xlsx',names)
        self.assertIn('Chiller - Air Cooled.xlsx',names)
        # Archive examples show that a tag alone does not settle coil type.
        self.assertIn('Fan Coil Units DX.xlsx',names)

    def test_grouped_design_preserved_actuals_reset(self):
        wb=Workbook();ws=wb.active;ws.title='FAN COIL UNITS WTR'
        for offset,tag,flow in [(0,'BCU-1',2400),(44,'BCU-5',1125),(88,'BCU-9',760)]:
            for cell,value in [('A3','UNIT DESIGNATION'),('C3',tag),('A7','SERIAL #'),('C7','OLD SERIAL'),
                               ('C9','DESIGN'),('D9','ACTUAL'),('C11',flow),('D11',999),('C12',0),
                               ('D20',f'=D{11+offset}*1.08'),('A43','TECHNICIAN:'),('C43','OLD TECH'),
                               ('G43','TEST DATE:'),('I43','2024-01-01')]:
                import re
                col,row=re.fullmatch(r'([A-Z]+)(\d+)',cell).groups()
                ws[f'{col}{int(row)+offset}']=value
        wb.create_sheet('Sheet1')
        data=packed(wb)
        self.assertEqual(len(inspect_reference(data)['units']),3)
        result=load_workbook(io.BytesIO(build_reference(data,'Test','Olive Branch, MS')))
        self.assertEqual(result.sheetnames,['FAN COIL UNITS WTR'])
        dst=result.active
        for row,flow in [(11,2400),(55,1125),(99,760)]:
            self.assertEqual(dst[f'C{row}'].value,flow)
            self.assertIsNone(dst[f'D{row}'].value)
            self.assertEqual(dst[f'C{row+1}'].value,0)
        for c in ['C7','C51','C95','C43','I43','C87','I87','C131','I131']:
            self.assertIsNone(dst[c].value,c)
        self.assertEqual(dst['G43'].value,'TEST DATE:')
        self.assertEqual(dst['D20'].value,'=D11*1.08')

    def test_grille_design_and_formulas(self):
        wb=Workbook();ws=wb.active;ws.title='EXHAUST GRILLS'
        for c,v in {'A3':'AREA SERVED','F3':'INITIAL','G3':'DESIGN','H3':'ACTUAL',
                    'F4':'CFM','H4':'CFM','G7':70,'F7':65,'H7':69,'I7':'=H7/G7'}.items():ws[c]=v
        unit=wb.create_sheet('EXHAUST FAN');unit['B3']='UNIT DESIGNATION';unit['H3']='EF-1';unit['I29']=0.5
        result=load_workbook(io.BytesIO(build_reference(packed(wb),'Test')))
        ws=result['EXHAUST GRILLS']
        self.assertEqual(ws['G7'].value,70)
        self.assertIsNone(ws['H7'].value);self.assertIsNone(ws['F7'].value)
        self.assertEqual(ws['H4'].value,'CFM')
        self.assertEqual('=H7/G7',ws['I7'].value)
        self.assertIsNone(result['EXHAUST FAN']['I29'].value)

    def test_reject_unknown_layout(self):
        wb=Workbook();wb.active['A1']='Unrecognized report'
        with self.assertRaisesRegex(ValueError,'unsupported'):
            inspect_reference(packed(wb))

    def test_serial_reset_does_not_erase_motor_design(self):
        wb=Workbook();ws=wb.active;ws.title='PUMPS'
        for c,v in {'A3':'UNIT DESIGNATION','C3':'P-1','F2':'MOTOR DATA','A7':'SERIAL NUMBER',
                    'C7':'OLD SERIAL','F7':'RPM','H7':1800,'C16':'DESIGN','D16':'ACTUAL',
                    'C17':93.3,'D17':90,'H25':'--'}.items():ws[c]=v
        out=load_workbook(io.BytesIO(build_reference(packed(wb),'Test'))).active
        self.assertEqual(out['F7'].value,'RPM');self.assertEqual(out['H7'].value,1800)
        self.assertIsNone(out['C7'].value);self.assertIsNone(out['D17'].value)
        self.assertEqual(out['H25'].value,'--')

    def test_empty_or_oversized_reference(self):
        for data in (b'',b'x'*8_000_001):
            with self.assertRaises(ValueError):inspect_reference(data)

    def test_reference_http_inspect_and_build(self):
        wb=Workbook();ws=wb.active;ws.title='PUMPS';ws['A3']='UNIT DESIGNATION';ws['C3']='P-1'
        ws['C16']='DESIGN';ws['D16']='ACTUAL';ws['C17']=93.3;ws['D17']=90
        raw=packed(wb)
        server=abp_server.ThreadingHTTPServer(('127.0.0.1',0),abp_server.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,approved):
            boundary='ABPTestBoundary'
            parts=[]
            for key,value in [('project',b'Test'),('approved',approved.encode()),('reference',raw)]:
                header=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                if key=='reference':header+='; filename="reference.xlsx"'
                parts.append(header.encode()+b'\r\n\r\n'+value+b'\r\n')
            body=b''.join(parts)+f'--{boundary}--\r\n'.encode()
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            conn.request('POST',path,body,{'Content-Type':f'multipart/form-data; boundary={boundary}'})
            response=conn.getresponse();result=(response.status,response.read());conn.close();return result
        try:
            status,body=request('/api/reference/inspect','false')
            self.assertEqual(status,200);self.assertEqual(json.loads(body)['units'][0]['tag'],'P-1')
            self.assertEqual(request('/api/reference/build','false')[0],400)
            status,body=request('/api/reference/build','true')
            self.assertEqual(status,200)
            out=load_workbook(io.BytesIO(body)).active
            self.assertEqual(out['C17'].value,93.3);self.assertIsNone(out['D17'].value)
            abp_server.LAN_MODE=True
            self.assertEqual(request('/api/reference/inspect','false')[0],401)
        finally:
            abp_server.LAN_MODE=False
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
