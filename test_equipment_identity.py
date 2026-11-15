"""Original form labels and exported identity, independent of writer cell maps."""
import io
import unittest
from openpyxl import load_workbook
from abp_server import LOOKUP, build


class EquipmentIdentityTests(unittest.TestCase):
    def test_reviewed_identity_on_every_supported_form(self):
        # Coordinates are checked against the actual original form labels below,
        # rather than imported from UNIT_FORMS (which omitted these fields).
        forms = [
            ('Air Moving Equipment.xlsx', 'RTU', 'A5', 'A6', 'G5', 'G6', 'G7', 'design_cfm'),
            ('Exhaust Fans _Std._.xlsx', 'EF', 'B5', 'B6', 'H5', 'H6', 'H7', 'design_cfm'),
            ('Exhaust Fans _Sm._.xlsx', 'CEF', 'A4', 'A5', 'C4', 'C5', None, 'design_cfm'),
            ('Fan Coil Units WTR.xlsx', 'BCU', 'A5', 'A6', 'C5', 'C6', 'C7', 'design_cfm'),
            ('Fan Coil Units DX.xlsx', 'FCU', 'A5', 'A6', 'C5', 'C6', 'C7', 'design_cfm'),
            ('Fan Coil Units DX GAS.xlsx', 'DOAS', 'A5', 'A6', 'C5', 'C6', 'C7', 'design_cfm'),
            ('Fan Coil Units DX ELE.xlsx', 'IDU', 'A5', 'A6', 'C5', 'C6', 'C7', 'design_cfm'),
            ('Unit Heater ELE.xlsx', 'EUH', 'A5', 'A6', 'C5', 'C6', 'C7', 'heating_cfm'),
            ('Unit Heater GAS.xlsx', 'GUH', 'A5', 'A6', 'C5', 'C6', 'C7', 'heating_cfm'),
            ('Unit Heater WTR.xlsx', 'UH', 'A5', 'A6', 'C5', 'C6', 'C7', 'heating_cfm'),
            ('Kitchen Hood.xlsx', 'KH', 'A4', 'A5', 'D4', 'D5', None, 'design_cfm'),
            ('Chiller - Air Cooled.xlsx', 'CH', 'A5', 'A6', 'C5', 'C6', 'C7', 'design_gpm'),
        ]
        records = []
        for n, (form, prefix, *_, flow) in enumerate(forms, 1):
            records += [dict(tag=f'{prefix}-1', template=form, status='VERIFIED',
                             manufacturer=f'MAKER{n}', model=f'MODEL{n}', **{flow: 100}),
                        dict(tag=f'{prefix}-99', template=form, status='UNVERIFIED',
                             manufacturer='UNREVIEWED MAKER', model='UNREVIEWED MODEL')]
        output = load_workbook(io.BytesIO(build({'project': 'Identity regression',
                    'templates': [f[0] for f in forms], 'records': records})))
        for n, (form, _, make_label, model_label, make, model, serial, _) in enumerate(forms, 1):
            with self.subTest(form=form):
                original = load_workbook(LOOKUP[form]).active
                self.assertIn(original[make_label].value.strip(), ('MAKE', 'MANUFACTURER'))
                self.assertTrue(original[model_label].value.strip().startswith('MODEL'))
                sheet = output[original.title]
                self.assertEqual(sheet[make].value, f'MAKER{n}')
                self.assertEqual(sheet[model].value, f'MODEL{n}')
                if serial:
                    self.assertIsNone(sheet[serial].value)
        self.assertFalse(any(c.value in ('UNREVIEWED MAKER', 'UNREVIEWED MODEL')
                             for s in output for row in s for c in row))

    def test_fan_coil_identity_survives_side_slots_and_page_append(self):
        forms = [('Fan Coil Units DX.xlsx', 'FCU', (3, 5, 7, 9)),
                 ('Fan Coil Units DX ELE.xlsx', 'IDU', (3, 7, 11))]
        records = [dict(tag=f'{prefix}-{i+1}', template=form, status='VERIFIED',
                        design_cfm=500, manufacturer=f'MAKER{i+1}', model=f'MODEL{i+1}')
                   for form, prefix, cols in forms for i in range(len(cols)+1)]
        # A new physical unit without selected identity must remain blank.
        records += [dict(tag='FCU-6', template=forms[0][0], status='VERIFIED', design_cfm=600)]
        output = load_workbook(io.BytesIO(build({'project': 'Packed identity',
                    'templates': [f[0] for f in forms], 'records': records})))
        for form, prefix, cols in forms:
            original = load_workbook(LOOKUP[form]).active
            sheet = output[original.title]
            for i in range(len(cols)+1):
                row = (i // len(cols)) * original.max_row
                col = cols[i % len(cols)]
                self.assertEqual(sheet.cell(row+3, col).value, f'{prefix}-{i+1}')
                self.assertEqual(sheet.cell(row+5, col).value, f'MAKER{i+1}')
                self.assertEqual(sheet.cell(row+6, col).value, f'MODEL{i+1}')
                self.assertIsNone(sheet.cell(row+7, col).value)
                self.assertIsNone(sheet.cell(row+11, col+1).value)
            self.assertEqual(sheet.max_row, original.max_row * 2)
        dx = output['FAN COIL UNITS DX']
        height = load_workbook(LOOKUP[forms[0][0]]).active.max_row
        self.assertEqual(dx.cell(height+3, 5).value, 'FCU-6')
        self.assertIsNone(dx.cell(height+5, 5).value)
        self.assertIsNone(dx.cell(height+6, 5).value)


if __name__ == '__main__':
    unittest.main()
