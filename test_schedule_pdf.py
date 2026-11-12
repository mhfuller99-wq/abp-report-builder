"""Schedule parsing through scan, review, and build.

Committed fixtures are synthetic. Original job drawings stay off the public
branch. Set ABP_PRIVATE_SOURCES to a local directory of those PDFs to opt in.
"""
import io
import json
import os
import http.client
import threading
import unittest
from collections import Counter
from pathlib import Path
from openpyxl import load_workbook
import abp_server

SKIP = {'manufacturer', 'model'}


def apply_proposed(record):
    """Same review step the page runs after a scan. Does not verify."""
    record = {**record, 'status': 'UNVERIFIED'}
    for field, value in (record.get('proposed') or {}).items():
        if field in SKIP:
            continue
        if record.get(field) in (None, ''):
            record[field] = value
    for field, value in (record.get('text_proposed') or {}).items():
        if field in SKIP:
            continue
        if record.get(field) in (None, ''):
            record[field] = value
    return record


def synthetic_schedule_pdf():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=1600, height=900)
    rows = [
        (60, 'EF-1 PARTS GREENHECK SYN-100 400 1200 0.50 0.10 1/4 DIRECT 10 20 10x10 NEMA 115/60/1'),
        (100, 'VRF-1 ROOM 101 CARRIER (NO EXCEPTIONS) MMU-UP0001HP-UL 550 60 80.0/67.0 9013 12675 70.0 88.0 10469 208-230/60/1 1 / 15 1'),
        (140, 'DOAS-1 CARRIER (NO EXCEPTIONS) SYN-DOAS 07 (7 TONS) 9 5 5 100 1.0 800 80.0/67.0 55.0/55.0 70 90 10 8 80 460/60/3 10 / 15'),
    ]
    for y, line in rows:
        page.insert_text((36, y), line, fontsize=8)
    # A grille mark and a distant dimension must not become equipment.
    page.insert_text((36, 220), 'B', fontsize=8)
    page.insert_text((700, 220), '6', fontsize=8)
    # Plan symbols. The submittal on the next page says 900 CFM for the unit.
    page.insert_text((40, 340), 'ENLARGED MECHANICAL FLOOR PLANS - AREA C', fontsize=8)
    page.insert_text((80, 360), 'DOAS', fontsize=8)
    page.insert_text((130, 360), '1', fontsize=8)

    def put(x, y, text):
        page.insert_text((x, y), text, fontsize=8)

    put(100, 420, 'A:')
    put(130, 420, '6"Ø')
    put(100, 436, '25')
    put(124, 436, 'CFM')
    put(260, 420, 'A:')
    put(290, 420, '6"Ø')
    put(260, 436, '25')
    put(284, 436, 'CFM')
    put(420, 420, 'A:')
    put(450, 420, '8"Ø')
    put(420, 436, '100')
    put(448, 436, 'CFM')
    put(580, 420, 'B:')
    put(610, 420, '6"Ø')
    put(580, 436, '80')
    put(604, 436, 'CFM')
    put(100, 500, 'A LAY-IN SUPPLY GRILLE')
    put(100, 530, 'REGISTER, GRILLE, & DIFFUSER SCHEDULE')
    put(100, 560, 'TYPICAL DIFFUSER NECK')
    sub = doc.new_page(width=800, height=1100)
    submittal = '''
SYN DOAS (#1)
Supply Air: 900 CFM
Outdoor Air: 900 CFM
1.000 HP, 3 Phs, 460 V, 60 Hz, 2.2 FLA
SP: 0.500" w.g. (0.400" Ductwork Discharge ESP + 0.100" Opt.)
Output BTU: 50,000
Input BTU: 60,000
Winter Outdoor Air Dry Bulb Temp: 10.0
Temp Rise: 40.0
Discharge Dry Bulb Temp: 50.0
Outdoor Air Dry Bulb Temp: 95.0
Outdoor Air Wet Bulb Temp: 75.0
Leaving Dry Bulb Temp: 55.0
Leaving Wet Bulb Temp: 54.0
Total Capacity: 40.0 MBH
Sensible Capacity: 30.0 MBH
Unit Main Input: 12.0 Amps MCA
20 Amps MOP
RPM: 1100
'''
    sub.insert_text((36, 40), submittal, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def find_tag(ws, tag):
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == tag:
                return cell.row, cell.column
    return None


def post(server, path, body, content_type):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    conn.request('POST', path, body, {'Content-Type': content_type})
    response = conn.getresponse()
    payload = response.read()
    status = response.status
    conn.close()
    return status, payload


class SchedulePdfTests(unittest.TestCase):
    def test_diffuser_text_cannot_become_a_formula(self):
        payload = {
            'type': '=HYPERLINK("http://evil")',
            'size': '+1+1',
            'system': '-DOAS',
            'location': ' =1+1',
            'design_cfm': 25,
            'source': '=NOW()',
            'reference': 'page 1',
            'evidence': '@SUM(A1)',
        }
        raw = abp_server.build({
            'project': 'Formula guard',
            'location': 'Lab',
            'templates': ['Supply Diffusers.xlsx'],
            'records': [],
            'diffusers': [payload],
        })
        sheet = load_workbook(io.BytesIO(raw))['SUPPLY DIFFUSERS']
        written = {
            'D6': payload['type'],
            'E6': payload['size'],
            'A5': payload['system'],
            'A6': payload['location'],
        }
        for address, original in written.items():
            cell = sheet[address]
            self.assertNotEqual(cell.data_type, 'f', address)
            self.assertEqual(cell.value, abp_server.excel_safe(original).upper())
            self.assertTrue(str(cell.value).startswith("'"), address)
        self.assertEqual(sheet['G6'].value, 25)
        self.assertNotEqual(sheet['G6'].data_type, 'f')
        self.assertIsNone(sheet['F6'].value)
        self.assertIsNone(sheet['H6'].value)

    def test_doas_form_follows_source_heating_type(self):
        from abp_design import doas_fan_coil
        gas = {'candidates': [{'values': {'heating_input_btu': 75000, 'cooling_edb': 81.7}}]}
        electric = {'candidates': [{'values': {'cooling_edb': 80}, 'evidence': 'ELECTRIC HEAT 5 KW'}]}
        dx = {'candidates': [{'values': {'cooling_edb': 80, 'heating_edb': 70}}]}
        self.assertEqual(doas_fan_coil(gas), 'Fan Coil Units DX GAS.xlsx')
        self.assertEqual(doas_fan_coil(electric), 'Fan Coil Units DX ELE.xlsx')
        self.assertEqual(doas_fan_coil(dx), 'Fan Coil Units DX.xlsx')

    def test_synthetic_schedule_scan_review_and_build(self):
        server = abp_server.ThreadingHTTPServer(('127.0.0.1', 0), abp_server.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            boundary = 'ABPSyntheticBoundary'
            header = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                      'filename="synthetic-schedule.pdf"\r\nContent-Type: application/pdf\r\n\r\n')
            body = header.encode() + synthetic_schedule_pdf() + f'\r\n--{boundary}--\r\n'.encode()
            status, raw = post(server, '/api/scan', body, f'multipart/form-data; boundary={boundary}')
            self.assertEqual(status, 200, raw[:300])
            scanned = json.loads(raw)
            self.assertNotIn('B-6', scanned['tags'])
            self.assertCountEqual([tag for tag in scanned['tags'] if tag in {'EF-1', 'VRF-1', 'DOAS-1'}], ['EF-1', 'VRF-1', 'DOAS-1'])
            by = {row['tag']: row for row in scanned['records']}
            self.assertIsNone(by['DOAS-1']['design_cfm'])
            self.assertEqual(by['DOAS-1']['status'], 'UNVERIFIED')
            self.assertEqual(by['DOAS-1']['template'], 'Fan Coil Units DX GAS.xlsx')
            self.assertNotIn('design_cfm', by['DOAS-1']['proposed'])
            self.assertTrue(any('disagree' in flag for flag in by['DOAS-1']['flags']))
            self.assertNotIn('esp', by['DOAS-1']['proposed'])
            self.assertEqual(by['DOAS-1']['proposed']['motor_fla'], 2.2)
            self.assertNotIn('fan_rpm', by['DOAS-1']['proposed'])
            self.assertEqual(by['VRF-1']['proposed']['design_cfm'], 550)
            self.assertEqual(by['VRF-1']['template'], 'Fan Coil Units DX.xlsx')
            self.assertEqual(by['EF-1']['proposed']['motor_hp'], 0.25)
            outlets = scanned['diffusers']
            self.assertEqual([item['design_cfm'] for item in outlets], [25, 25, 100])
            self.assertTrue(all(item['type'] == 'A' and item['system'] == '' and item['include'] is False for item in outlets))
            self.assertEqual([item['size'] for item in outlets], ['6"Ø', '6"Ø', '8"Ø'])
            self.assertNotIn(900, [item['design_cfm'] for item in outlets])
            self.assertIn('supply_outlets', scanned['signals'])
            status, raw = post(server, '/api/suggest', json.dumps({
                'tags': scanned['tags'], 'signals': scanned['signals'], 'sparse': scanned['sparse']
            }).encode(), 'application/json')
            self.assertEqual(status, 200, raw[:300])
            chosen = [item['name'] for item in json.loads(raw)['recommended']]
            self.assertEqual(chosen[0], 'Project Information.xlsx')
            self.assertEqual(chosen[1], 'Notes.xlsx')
            self.assertLess(chosen.index('Duct Traverse Rect..xlsx'), chosen.index('Duct Traverse RND.xlsx'))
            self.assertIn('Supply Diffusers.xlsx', chosen)
            self.assertLess(chosen.index('Supply Diffusers.xlsx'), chosen.index('Duct Traverse Rect..xlsx'))
            for row in scanned['records']:
                if row.get('template') and row['template'] not in chosen:
                    chosen.append(row['template'])
            for outlet in outlets:
                outlet.update(include=True, system='DOAS-1', location='Reviewed room')
            reviewed = []
            for row in scanned['records']:
                row = apply_proposed(row)
                if row['tag'] == 'DOAS-1':
                    row.update(row['selected_performance'][0]['values'])
                if row.get('template') and row.get('design_cfm') not in (None, ''):
                    row['status'] = 'VERIFIED'
                reviewed.append(row)
            payload = {
                'project': 'Synthetic schedule', 'location': 'Lab', 'templates': chosen,
                'records': reviewed, 'diffusers': outlets,
                'scan_state': {'status': scanned['scan_status'], 'complete_takeoff': False,
                               'source_checkpoints': scanned['source_checkpoints'], 'warnings': scanned['warnings']}
            }
            status, raw = post(server, '/api/build', json.dumps(payload).encode(), 'application/json')
            if scanned['scan_status'] == 'incomplete':
                self.assertEqual(status, 400, raw[:400])
                self.assertIn('no partial report', json.loads(raw)['error'])
                # Assembly fidelity is tested separately from the public API guard.
                # This internal call is not a client compatibility path.
                raw = abp_server.build({k:v for k,v in payload.items() if k != 'scan_state'})
            else:
                self.assertEqual(status, 200, raw[:400])
            book = load_workbook(io.BytesIO(raw))
            self.assertEqual(book.sheetnames[0], 'PROJECT INFO')
            self.assertEqual(book.sheetnames[1], 'NOTES')
            self.assertEqual(book.sheetnames[-2:], ['DUCT TRAVERSE RECT.', 'DUCT TRAVERSE RND'])
            self.assertNotIn('EXTRACTION CANDIDATES', book.sheetnames)
            self.assertNotIn('BOILER', book.sheetnames)
            self.assertEqual(book['DUCT TRAVERSE RECT.'].max_row, 42 * abp_server.BLANK_RECT_FORMS)
            self.assertEqual(book['DUCT TRAVERSE RND'].max_row, 27 * abp_server.BLANK_RND_FORMS)
            self.assertIsNone(book['DUCT TRAVERSE RECT.']['B10'].value)
            self.assertNotIn('AIR MOVING EQUIPMENT', book.sheetnames)
            gas = book['FAN COIL UNITS GAS DX']
            self.assertEqual(gas['C10'].value, 'DX COOLING')
            self.assertEqual(gas['C25'].value, 'GAS HEATING')
            self.assertEqual(gas['C3'].value, 'DOAS-1')
            self.assertEqual(gas['C11'].value, 900)
            self.assertEqual(gas['C12'].value, 900)
            self.assertEqual(gas['C16'].value, 95)
            self.assertEqual(gas['C17'].value, 75)
            self.assertEqual(gas['C18'].value, 55)
            self.assertEqual(gas['C19'].value, 54)
            self.assertEqual(gas['C26'].value, 10)
            self.assertEqual(gas['C27'].value, 50)
            self.assertTrue(str(gas['C20'].value).startswith('='))
            self.assertTrue(str(gas['C28'].value).startswith('='))
            self.assertIsNone(gas['D11'].value)
            self.assertIsNone(gas['D16'].value)
            self.assertIsNone(gas['C5'].value)
            self.assertIsNone(gas['C6'].value)
            self.assertIsNone(gas['C7'].value)
            fans = book['EXHAUST FAN']
            self.assertEqual(fans['H17'].value, 400)
            self.assertEqual(fans['U4'].value, 0.25)
            self.assertIsNone(fans['U7'].value)
            coils = book['FAN COIL UNITS DX']
            spot = find_tag(coils, 'VRF-1')
            self.assertIsNotNone(spot)
            self.assertEqual(coils.cell(spot[0] + 8, spot[1]).value, 550)
            self.assertEqual(coils.cell(spot[0] + 13, spot[1]).value, 80)
            self.assertIsNone(coils.cell(spot[0] + 2, spot[1]).value)
            self.assertLess(book.sheetnames.index('SUPPLY DIFFUSERS'), book.sheetnames.index('DUCT TRAVERSE RECT.'))
            diffusers = book['SUPPLY DIFFUSERS']
            self.assertEqual(diffusers['A2'].value, 'SUPPLY DIFFUSERS')
            self.assertEqual(diffusers['F3'].value, 'INITIAL')
            exported = [(diffusers.cell(row, 4).value, diffusers.cell(row, 5).value, diffusers.cell(row, 7).value)
                        for row in range(6, 12) if diffusers.cell(row, 4).value]
            self.assertEqual(exported, [('A', 6, 25), ('A', 6, 25), ('A', 8, 100)])
            self.assertIsNone(diffusers['F6'].value)
            self.assertIsNone(diffusers['H6'].value)
            self.assertNotEqual(diffusers['G6'].value, 900)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_private_job_sources_when_opted_in(self):
        root = os.environ.get('ABP_PRIVATE_SOURCES', '').strip()
        if not root:
            self.skipTest('Set ABP_PRIVATE_SOURCES to a local directory of job PDFs')
        folder = Path(root)
        files = sorted(folder.glob('*.pdf'))
        self.assertGreaterEqual(len(files), 1)
        scanned = abp_server.read_sources([(path.name, path.read_bytes()) for path in files])
        self.assertNotIn('B-6', scanned['tags'])
        self.assertNotIn('EF-22', scanned['tags'])
        self.assertNotIn('BC-24', scanned['tags'])
        self.assertNotIn('RTU1', scanned['tags'])
        self.assertNotIn('AC-8-03', scanned['tags'])
        by = {row['tag']: row for row in scanned['records']}
        # Counts below match the supplied McComb drawings and submittals.
        self.assertEqual(len(scanned['tags']), 54)
        self.assertEqual(by['DOAS-1']['status'], 'UNVERIFIED')
        self.assertIsNone(by['DOAS-1']['design_cfm'])
        self.assertEqual(by['DOAS-1']['template'], 'Fan Coil Units DX GAS.xlsx')
        self.assertEqual(by['DOAS-1']['proposed']['design_cfm'], 1000)
        self.assertEqual(by['DOAS-1']['proposed']['esp'], 0.75)
        self.assertEqual(by['DOAS-1']['proposed']['motor_fla'], 1.4)
        self.assertEqual(by['DOAS-1']['proposed']['cooling_edb'], 100.5)
        self.assertEqual(by['VRF-1']['proposed']['design_cfm'], 550)
        self.assertEqual(by['VRF-2']['proposed']['design_cfm'], 305)
        self.assertEqual(by['VRF-20C']['proposed']['design_cfm'], 550)
        self.assertEqual(by['EF-6']['proposed']['motor_hp'], 0.5)
        self.assertIsNone(by['EF-5']['proposed'].get('motor_hp'))
        self.assertEqual(by['EF-5']['proposed']['motor_fla'], 4.1)
        self.assertEqual(by['SSCU-1']['template'], '')
        chosen = [item['name'] for item in abp_server.suggested_templates(
            scanned['tags'], scanned['signals'], sparse=scanned['sparse'])['recommended']]
        self.assertNotIn('Boiler.xlsx', chosen)
        self.assertNotIn('Fan Coil Units WTR.xlsx', chosen)
        self.assertEqual(chosen[0], 'Project Information.xlsx')
        self.assertEqual(chosen[1], 'Notes.xlsx')
        self.assertEqual(chosen[-2:], ['Duct Traverse Rect..xlsx', 'Duct Traverse RND.xlsx'])
        for row in scanned['records']:
            if row.get('template') and row['template'] not in chosen:
                chosen.append(row['template'])
        reviewed = []
        for row in scanned['records']:
            row = apply_proposed(row)
            if row.get('template') and row.get('design_cfm') not in (None, ''):
                row['status'] = 'VERIFIED'
            reviewed.append(row)
        self.assertEqual(sum(row['status'] == 'VERIFIED' for row in reviewed), 32)
        outlets = scanned['diffusers']
        doas_size_6 = [item for item in outlets if item['reference'] == 'page 4' and item['neck_in'] == 6]
        # These callouts are the plan text. A finished report's count of 21 is a
        # comparison after the build, not a number this test is allowed to require.
        self.assertEqual(Counter(item['design_cfm'] for item in doas_size_6),
                         Counter({25: 13, 100: 2, 50: 2, 150: 1, 60: 1, 65: 1}))
        self.assertTrue(any(item['design_cfm'] == 150 and 'BREAK ROOM 111' in item['evidence'] for item in doas_size_6))
        self.assertTrue(all(item['design_cfm'] != 1000 for item in outlets))
        unlabeled = [item for item in outlets if item['reference'] == 'page 2']
        self.assertEqual(len(unlabeled), 2)
        self.assertTrue(all(item['system'] == '' and item['design_cfm'] is None and item['size'] == '10"ø' for item in unlabeled))
        self.assertIn('Supply Diffusers.xlsx', chosen)
        self.assertLess(chosen.index('Supply Diffusers.xlsx'), chosen.index('Duct Traverse Rect..xlsx'))
        raw = abp_server.build({'project': 'New McComb Sales Center', 'location': 'McComb, MS',
                                'templates': chosen, 'records': reviewed, 'diffusers': outlets})
        book = load_workbook(io.BytesIO(raw))
        self.assertEqual(book.sheetnames[0], 'PROJECT INFO')
        self.assertEqual(book.sheetnames[1], 'NOTES')
        self.assertEqual(book.sheetnames[-2:], ['DUCT TRAVERSE RECT.', 'DUCT TRAVERSE RND'])
        self.assertNotIn('EXTRACTION CANDIDATES', book.sheetnames)
        self.assertNotIn('BOILER', book.sheetnames)
        self.assertEqual(book['DUCT TRAVERSE RECT.'].max_row, 42 * 30)
        self.assertEqual(book['DUCT TRAVERSE RND'].max_row, 27 * 15)
        self.assertNotIn('AIR MOVING EQUIPMENT', book.sheetnames)
        gas = book['FAN COIL UNITS GAS DX']
        self.assertEqual(gas['C10'].value, 'DX COOLING')
        self.assertEqual(gas['C25'].value, 'GAS HEATING')
        self.assertEqual(gas['C3'].value, 'DOAS-1')
        self.assertEqual(gas['C11'].value, 1000)
        self.assertEqual(gas['C12'].value, 1000)
        self.assertAlmostEqual(gas['C16'].value, 100.5)
        self.assertEqual(gas['C17'].value, 84)
        self.assertAlmostEqual(gas['C18'].value, 51.9)
        self.assertAlmostEqual(gas['C19'].value, 51.7)
        self.assertEqual(gas['C26'].value, 17)
        self.assertEqual(gas['C27'].value, 90)
        self.assertTrue(str(gas['C20'].value).startswith('='))
        self.assertTrue(str(gas['C28'].value).startswith('='))
        self.assertIsNone(gas['D11'].value)
        self.assertIsNone(gas['D16'].value)
        self.assertIsNone(gas['C5'].value)
        self.assertIsNone(gas['C6'].value)
        self.assertIsNone(gas['C7'].value)
        self.assertIsNone(find_tag(book['FAN COIL UNITS DX'], 'DOAS-1'))
        self.assertLess(book.sheetnames.index('SUPPLY DIFFUSERS'), book.sheetnames.index('DUCT TRAVERSE RECT.'))
        supply = book['SUPPLY DIFFUSERS']
        exported = []
        for off in range(0,supply.max_row,42):
            for row in range(6+off,34+off):
                if supply.cell(row, 3).value:
                    exported.append((supply.cell(row, 4).value, supply.cell(row, 5).value,
                                     supply.cell(row, 1).value, supply.cell(row, 7).value,
                                     supply.cell(row, 6).value, supply.cell(row, 8).value))
        # Unreviewed drawing candidates never populate the supply form.
        self.assertTrue(all(item['include'] is False and item['system']=='' for item in outlets))
        self.assertEqual(exported, [])
        self.assertIsNone(book['EXHAUST FAN']['U7'].value)
        vrf = find_tag(book['FAN COIL UNITS DX'], 'VRF-20C')
        self.assertIsNotNone(vrf)
        self.assertEqual(book['FAN COIL UNITS DX'].cell(vrf[0] + 8, vrf[1]).value, 550)
        out = Path(os.environ.get('ABP_TEST_OUTPUT', 'test-output')) / 'McComb_unreviewed_source.xlsx'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)


if __name__ == '__main__':
    unittest.main()
