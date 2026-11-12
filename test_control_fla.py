"""Synthetic fan ratings vs control artwork; no client fixtures or values."""
import unittest

import pymupdf

from abp_schedule import fan_motor_fla_rows, parse_fan_submittal, segments


def word(x, y, text):
    return (x, y, x + len(text) * 4, y + 9, text, 0, 0, 0)


def data_row(y, label, value, x=0):
    words = []
    cursor = x + 180 - len(label) * 4
    for token in label.split():
        words.append(word(cursor, y, token))
        cursor += (len(token) + 1) * 4
    words.append(word(x + 220 - len(value) * 2, y, value))
    return words


def table(value='0.37', label='* FLA (A)', x=0, y=100):
    return [word(x + 120, y, 'Performance')] + data_row(y + 15, 'Requested Volume (CFM)', '80', x) + data_row(y + 30, 'Fan RPM', '930', x) + data_row(y + 45, label, value, x)


def read(words):
    return fan_motor_fla_rows(segments(words))


class FanControlFlaTests(unittest.TestCase):
    def test_manufacturer_scalar_has_local_table_provenance(self):
        value, evidence = read(table())
        self.assertEqual(value, 0.37)
        text = ' '.join(w[4] for w in evidence)
        self.assertIn('Performance', text)
        self.assertIn('Requested Volume (CFM)', text)
        self.assertIn('Fan RPM', text)
        self.assertIn('* FLA (A) 0.37', text)

    def test_standalone_control_dial_tick_is_not_motor_rating(self):
        words = [word(80, 100, 'Motor Starter Configuration')]
        words += data_row(145, 'FLA (A)', '35')
        words += [word(215, 131, '30'), word(225, 157, '40'), word(80, 170, 'OVERLOAD SETTING')]
        self.assertIsNone(read(words)[0])

    def test_dial_tick_with_nearby_artwork_text_is_not_scalar_row(self):
        words = table('35') + [word(250, 145, 'RELAYS'), word(290, 145, 'OUTPUT')]
        self.assertIsNone(read(words)[0])

    def test_nec_and_reference_labels_cannot_become_nameplate_fla(self):
        for label in ('NEC FLA* (Amps)', 'REFERENCE FLA (A)', 'FLA RANGE (A)'):
            with self.subTest(label=label):
                self.assertIsNone(read(table('12', label=label))[0])
        self.assertIsNone(read(table('1-40'))[0])

    def test_unrelated_equipment_rows_do_not_qualify_a_dial(self):
        words = [word(120, 100, 'Performance')] + data_row(145, 'FLA (A)', '35')
        words += data_row(115, 'Fan RPM', '930', 310)
        words += data_row(130, 'Requested Volume (CFM)', '80', 310)
        self.assertIsNone(read(words)[0])

    def test_table_needs_heading_and_two_distinct_aligned_witnesses(self):
        words = table()
        self.assertIsNone(read(words[1:])[0])
        words = [word(120, 100, 'Performance')] + data_row(115, 'Fan RPM', '930') + data_row(145, 'FLA (A)', '0.37')
        self.assertIsNone(read(words)[0])
        words += data_row(130, 'Fan RPM', '930')
        self.assertIsNone(read(words)[0])

    def test_controls_elsewhere_do_not_hide_a_valid_rating(self):
        words = table()
        words += [word(410, 100, 'Motor Starter Configuration'), word(410, 170, 'NEC REFERENCE ONLY')]
        words += data_row(145, 'FLA (A)', '35', 310)
        self.assertEqual(read(words)[0], 0.37)

    def test_conflicting_valid_motor_tables_are_withheld(self):
        self.assertIsNone(read(table('0.37') + table('1.7', y=300))[0])

    def test_excessive_scalar_rows_are_withheld_without_partial_choice(self):
        words = table()
        for n in range(65):
            words += data_row(300 + n * 15, 'FLA (A)', '1.7')
        self.assertEqual(read(words), (None, []))

    def test_motor_nameplate_table_is_supported(self):
        words = [word(120, 100, 'Motor Data')]
        words += data_row(115, 'Voltage/Cycle/Phase', '115/60/1')
        words += data_row(130, 'Motor RPM', '1725')
        words += data_row(145, 'Motor FLA (Amps)', '1.7')
        self.assertEqual(read(words)[0], 1.7)

    def test_pdf_integration_retains_scalar_and_its_exact_words(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((30, 40), 'Mark: EF-1,2', fontsize=8)
            page.insert_text((120, 100), 'Performance', fontsize=8)
            for y, label, value in [(115, 'Requested Volume (CFM)', '80'), (130, 'Fan RPM', '930'), (145, '* FLA (A)', '0.37')]:
                page.insert_text((180 - pymupdf.get_text_length(label, fontsize=8), y), label, fontsize=8)
                page.insert_text((220 - pymupdf.get_text_length(value, fontsize=8) / 2, y), value, fontsize=8)
            page.insert_text((350, 110), 'Motor Starter Configuration', fontsize=8)
            page.insert_text((350, 145), 'FLA (A) 35', fontsize=8)
            found = parse_fan_submittal(doc, 'synthetic.pdf')
        self.assertEqual([item['tag'] for item in found], ['EF-1', 'EF-2'])
        for item in found:
            self.assertEqual(item['values']['motor_fla'], 0.37)
            self.assertEqual(item['values']['design_cfm'], 80)
            self.assertEqual(item['reference'], 'page 1')
            self.assertIn('motor_fla', item['value_words'])
            self.assertNotIn('35', [w[4] for w in item['value_words']['motor_fla']])


if __name__ == '__main__':
    unittest.main()
