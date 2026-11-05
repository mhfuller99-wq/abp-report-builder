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
            self.assertEqual(by['DOAS-1']['proposed']['design_cfm'], 900)
            self.assertEqual(by['DOAS-1']['proposed']['esp'], 0.4)
            self.assertEqual(by['DOAS-1']['proposed']['motor_fla'], 2.2)
            self.assertNotIn('fan_rpm', by['DOAS-1']['proposed'])
            self.assertEqual(by['VRF-1']['proposed']['design_cfm'], 550)
            self.assertEqual(by['VRF-1']['template'], 'Fan Coil Units DX.xlsx')
            self.assertEqual(by['EF-1']['proposed']['motor_hp'], 0.25)
            status, raw = post(server, '/api/suggest', json.dumps({
                'tags': scanned['tags'], 'signals': scanned['signals'], 'sparse': scanned['sparse']
            }).encode(), 'application/json')
            self.assertEqual(status, 200, raw[:300])
            chosen = [item['name'] for item in json.loads(raw)['recommended']]
            self.assertEqual(chosen[0], 'Project Information.xlsx')
            self.assertEqual(chosen[1], 'Notes.xlsx')
            self.assertLess(chosen.index('Duct Traverse Rect..xlsx'), chosen.index('Duct Traverse RND.xlsx'))
            reviewed = []
            for row in scanned['records']:
                row = apply_proposed(row)
                if row.get('template') and row.get('design_cfm') not in (None, ''):
                    row['status'] = 'VERIFIED'
                reviewed.append(row)
            status, raw = post(server, '/api/build', json.dumps({
                'project': 'Synthetic schedule', 'location': 'Lab', 'templates': chosen, 'records': reviewed
            }).encode(), 'application/json')
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
            air = book['AIR MOVING EQUIPMENT']
            self.assertEqual(air['G3'].value, 'DOAS-1')
            self.assertEqual(air['G17'].value, 900)
            self.assertAlmostEqual(air['G21'].value, 0.4)
            self.assertAlmostEqual(air['T6'].value, 2.2)
            self.assertIsNone(air['T7'].value)
            self.assertIsNone(air['G5'].value)
            self.assertIsNone(air['G6'].value)
            self.assertIsNone(air['J17'].value)
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
        reviewed = []
        for row in scanned['records']:
            row = apply_proposed(row)
            if row.get('template') and row.get('design_cfm') not in (None, ''):
                row['status'] = 'VERIFIED'
            reviewed.append(row)
        self.assertEqual(sum(row['status'] == 'VERIFIED' for row in reviewed), 32)
        raw = abp_server.build({'project': 'New McComb Sales Center', 'location': 'McComb, MS',
                                'templates': chosen, 'records': reviewed})
        book = load_workbook(io.BytesIO(raw))
        self.assertEqual(book.sheetnames[0], 'PROJECT INFO')
        self.assertEqual(book.sheetnames[1], 'NOTES')
        self.assertEqual(book.sheetnames[-2:], ['DUCT TRAVERSE RECT.', 'DUCT TRAVERSE RND'])
        self.assertNotIn('EXTRACTION CANDIDATES', book.sheetnames)
        self.assertNotIn('BOILER', book.sheetnames)
        self.assertEqual(book['DUCT TRAVERSE RECT.'].max_row, 42 * 30)
        self.assertEqual(book['DUCT TRAVERSE RND'].max_row, 27 * 15)
        self.assertEqual(book['AIR MOVING EQUIPMENT']['G3'].value, 'DOAS-1')
        self.assertEqual(book['AIR MOVING EQUIPMENT']['G17'].value, 1000)
        self.assertAlmostEqual(book['AIR MOVING EQUIPMENT']['G21'].value, 0.75)
        self.assertAlmostEqual(book['AIR MOVING EQUIPMENT']['T6'].value, 1.4)
        self.assertIsNone(book['AIR MOVING EQUIPMENT']['T7'].value)
        self.assertIsNone(book['AIR MOVING EQUIPMENT']['G5'].value)
        self.assertIsNone(book['AIR MOVING EQUIPMENT']['G6'].value)
        self.assertIsNone(book['EXHAUST FAN']['U7'].value)
        vrf = find_tag(book['FAN COIL UNITS DX'], 'VRF-20C')
        self.assertIsNotNone(vrf)
        self.assertEqual(book['FAN COIL UNITS DX'].cell(vrf[0] + 8, vrf[1]).value, 550)
        out = Path('/opt/cursor/artifacts/CocaCola_McComb_PreField_source.xlsx')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)


if __name__ == '__main__':
    unittest.main()
