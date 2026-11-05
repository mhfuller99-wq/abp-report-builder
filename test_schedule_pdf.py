"""Scan the McComb source drawings and submittals, review them, and build."""
import io
import json
import http.client
import threading
import unittest
from pathlib import Path
from openpyxl import load_workbook
import abp_server

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / 'tests' / 'source_pdfs'
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


def find_tag(ws, tag):
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == tag:
                return cell.row, cell.column
    return None


class SchedulePdfTests(unittest.TestCase):
    def test_source_pdfs_scan_review_and_build(self):
        files = [
            SOURCES / 'Mechanical_Drawings.pdf',
            SOURCES / 'Submittal_DOAS.pdf',
            SOURCES / 'Submittal_Warehouse_Equipment.pdf',
        ]
        self.assertTrue(all(path.is_file() and path.stat().st_size > 1000 for path in files))
        server = abp_server.ThreadingHTTPServer(('127.0.0.1', 0), abp_server.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(path, body, content_type):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('POST', path, body, {'Content-Type': content_type})
            response = conn.getresponse()
            payload = response.read()
            status = response.status
            conn.close()
            return status, payload

        try:
            boundary = 'ABPScheduleBoundary'
            parts = []
            for path in files:
                header = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                          f'filename="{path.name}"\r\nContent-Type: application/pdf\r\n\r\n')
                parts.append(header.encode() + path.read_bytes() + b'\r\n')
            body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
            status, raw = post('/api/scan', body, f'multipart/form-data; boundary={boundary}')
            self.assertEqual(status, 200, raw[:300])
            scanned = json.loads(raw)
            self.assertNotIn('B-6', scanned['tags'])
            self.assertNotIn('EF-22', scanned['tags'])
            self.assertNotIn('BC-24', scanned['tags'])
            self.assertNotIn('RTU1', scanned['tags'])
            self.assertNotIn('AC-8-03', scanned['tags'])
            self.assertEqual(len(scanned['tags']), 54)
            by = {row['tag']: row for row in scanned['records']}
            self.assertIsNone(by['DOAS-1']['design_cfm'])
            self.assertEqual(by['DOAS-1']['status'], 'UNVERIFIED')
            self.assertEqual(by['DOAS-1']['template'], 'Air Moving Equipment.xlsx')
            self.assertEqual(by['VRF-20C']['template'], 'Fan Coil Units DX.xlsx')
            self.assertEqual(by['VRF-1']['proposed']['design_cfm'], 550)
            self.assertEqual(by['VRF-20C']['proposed']['design_cfm'], 550)
            self.assertEqual(by['VRF-2']['proposed']['design_cfm'], 305)
            self.assertEqual(by['DOAS-1']['proposed']['design_cfm'], 1000)
            self.assertEqual(by['DOAS-1']['proposed']['esp'], 0.75)
            self.assertEqual(by['DOAS-1']['proposed']['motor_fla'], 1.4)
            self.assertEqual(by['DOAS-1']['proposed']['cooling_edb'], 100.5)
            self.assertNotIn('fan_rpm', by['DOAS-1']['proposed'])
            self.assertNotIn('motor_hp', by['EF-5']['proposed'])
            self.assertEqual(by['EF-5']['proposed']['motor_fla'], 4.1)
            self.assertEqual(by['EF-6']['proposed']['motor_hp'], 0.5)
            self.assertTrue(any('not motor RPM' in flag or 'not written to motor RPM' in flag for flag in by['EF-6']['flags']))
            self.assertTrue(any('Unit MCA' in flag for flag in by['DOAS-1']['flags']))
            self.assertEqual(by['SSCU-1']['template'], '')
            status, raw = post('/api/suggest', json.dumps({'tags': scanned['tags'], 'signals': scanned['signals']}).encode(), 'application/json')
            self.assertEqual(status, 200, raw[:300])
            recommended = json.loads(raw)['recommended']
            names = [item['name'] for item in recommended]
            self.assertNotIn('Boiler.xlsx', names)
            self.assertNotIn('Fan Coil Units WTR.xlsx', names)
            chosen = [item['name'] for item in recommended if not item['review']]
            reviewed = []
            for row in scanned['records']:
                row = apply_proposed(row)
                if row.get('template') and row.get('design_cfm') not in (None, ''):
                    row['status'] = 'VERIFIED'
                reviewed.append(row)
            self.assertEqual(sum(row['status'] == 'VERIFIED' for row in reviewed), 32)
            payload = {'project': 'New McComb Sales Center', 'location': 'McComb, MS',
                       'templates': chosen, 'records': reviewed, 'prefield_pack': True}
            status, raw = post('/api/build', json.dumps(payload).encode(), 'application/json')
            self.assertEqual(status, 200, raw[:400])
            self.assertGreater(len(raw), 10000)
            out = load_workbook(io.BytesIO(raw))
            self.assertEqual(out.sheetnames, [
                'PROJECT INFO', 'NOTES', 'AIR MOVING EQUIPMENT', 'EXHAUST FAN',
                'FAN COIL UNITS DX', 'COIL DX GAS HT', 'DUCT TRAVERSE RECT.', 'DUCT TRAVERSE RND'])
            self.assertNotIn('EXTRACTION CANDIDATES', out.sheetnames)
            air = out['AIR MOVING EQUIPMENT']
            self.assertEqual(air['G3'].value, 'DOAS-1')
            self.assertEqual(air['G17'].value, 1000)
            self.assertEqual(air['G18'].value, 1000)
            self.assertAlmostEqual(air['G20'].value, 0.942)
            self.assertAlmostEqual(air['G21'].value, 0.75)
            self.assertEqual(air['T4'].value, 1)
            self.assertEqual(air['T5'].value, 460)
            self.assertAlmostEqual(air['T6'].value, 1.4)
            self.assertIsNone(air['T7'].value)
            self.assertIsNone(air['G5'].value)
            self.assertIsNone(air['G6'].value)
            self.assertIsNone(air['G7'].value)
            self.assertIsNone(air['J17'].value)
            self.assertEqual(air['G10'].value, 'DEDICATED OUTSIDE AIR')
            self.assertEqual(air['G12'].value, 'MECHANICAL YARD')
            fans = out['EXHAUST FAN']
            self.assertEqual(fans['H3'].value, 'EF-1')
            self.assertEqual(fans['H17'].value, 400)
            self.assertEqual(fans['H21'].value, 0.5)
            self.assertEqual(fans['U4'].value, 0.25)
            self.assertEqual(fans['U5'].value, 115)
            self.assertIsNone(fans['U7'].value)
            self.assertIsNone(fans['K17'].value)
            ef5 = find_tag(fans, 'EF-5')
            ef6 = find_tag(fans, 'EF-6')
            self.assertIsNotNone(ef5)
            self.assertIsNotNone(ef6)
            self.assertEqual(fans.cell(ef5[0] + 14, ef5[1]).value, 650)
            self.assertIsNone(fans.cell(ef5[0] + 1, 21).value)
            self.assertAlmostEqual(fans.cell(ef5[0] + 3, 21).value, 4.1)
            self.assertEqual(fans.cell(ef6[0] + 14, ef6[1]).value, 1791)
            self.assertEqual(fans.cell(ef6[0] + 1, 21).value, 0.5)
            self.assertIsNone(fans.cell(ef6[0] + 4, 21).value)
            coils = out['FAN COIL UNITS DX']
            vrf1 = find_tag(coils, 'VRF-1')
            vrf20 = find_tag(coils, 'VRF-20C')
            ssau = find_tag(coils, 'SSAU-1')
            self.assertIsNotNone(vrf1)
            self.assertIsNotNone(vrf20)
            self.assertEqual(coils.cell(vrf1[0] + 8, vrf1[1]).value, 550)
            self.assertEqual(coils.cell(vrf1[0] + 13, vrf1[1]).value, 80)
            self.assertEqual(coils.cell(vrf1[0] + 14, vrf1[1]).value, 67)
            self.assertEqual(coils.cell(vrf1[0] + 23, vrf1[1]).value, 70)
            self.assertAlmostEqual(coils.cell(vrf1[0] + 24, vrf1[1]).value, 87.6)
            self.assertEqual(coils.cell(vrf1[0] + 1, vrf1[1]).value, 'BREAK ROOM 111')
            self.assertIsNone(coils.cell(vrf1[0] + 2, vrf1[1]).value)
            self.assertIsNone(coils.cell(vrf1[0] + 3, vrf1[1]).value)
            self.assertTrue(str(coils.cell(vrf1[0] + 17, vrf1[1]).value or '').startswith('='))
            self.assertIsNone(coils.cell(vrf1[0] + 8, vrf1[1] + 1).value)
            self.assertEqual(coils.cell(vrf20[0] + 8, vrf20[1]).value, 550)
            self.assertEqual(coils.cell(ssau[0] + 8, ssau[1]).value, 400)
            self.assertEqual(coils.cell(ssau[0] + 9, ssau[1]).value, 25)
            self.assertEqual(sum(1 for row in coils.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith(('VRF-', 'SSAU-'))), 25)
            gas = out['COIL DX GAS HT']
            self.assertEqual(gas['D4'].value, 'DOAS-1')
            self.assertEqual(gas['D8'].value, 1000)
            self.assertAlmostEqual(gas['D14'].value, 100.5)
            self.assertEqual(gas['D15'].value, 84)
            self.assertAlmostEqual(gas['D16'].value, 51.9)
            self.assertAlmostEqual(gas['D17'].value, 51.7)
            self.assertEqual(gas['D25'].value, 17)
            self.assertEqual(gas['D26'].value, 90)
            self.assertEqual(gas['D19'].data_type, 'f')
            self.assertEqual(gas['D28'].data_type, 'f')
            rect = out['DUCT TRAVERSE RECT.']
            rnd = out['DUCT TRAVERSE RND']
            self.assertEqual(rect.max_row, 42 * 30)
            self.assertEqual(rnd.max_row, 27 * 15)
            self.assertEqual(rect['D3'].value, 'DOAS-1')
            self.assertEqual(rect['L3'].value, 1000)
            self.assertIsNone(rect['B10'].value)
            self.assertIsNone(rnd['D3'].value)
            self.assertIsNone(rect['D45'].value)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
