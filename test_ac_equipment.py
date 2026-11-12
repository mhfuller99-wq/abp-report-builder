"""Synthetic AC schedule regressions. No client source or workbook values."""
import re
import unittest

from abp_mechanical import TAG, expand_marks, schedule_candidates
from abp_ocr import equipment_candidates
from abp_schedule import parse_page


def word(x, y, text):
    return (x, y, x + len(text)*4, y+9, text, 0, 0, 0)


def phrase(x, y, text):
    result = []
    for token in text.split():
        result.append(word(x, y, token))
        x = result[-1][2] + 4
    return result


def ac_schedule(title='HEATING & AIR CONDITIONING UNIT SCHEDULE'):
    headers = phrase(180, 35, title) + phrase(170, 60, 'EVAPORATOR FAN')
    headers += [word(10, 90, 'MARK'), word(150, 90, 'CFM'), word(230, 90, 'ESP'),
                word(280, 90, 'HP'), word(330, 76, 'OUTSIDE')]
    headers += phrase(330, 90, 'AIR CFM') + phrase(450, 90, 'GAS INPUT')
    headers += phrase(600, 90, 'GAS OUTPUT')
    data = []
    for y, tag, flow, outside, gas_in, gas_out in [
            (120, 'AC-7', '1800', '250', '88000', '70000'),
            (140, 'AC-8', '1100', '150', '55000', '44000')]:
        data += [word(10, y, tag), word(150, y, flow), word(230, y, '0.45'),
                 word(280, y, '1'), word(330, y, outside),
                 word(450, y, gas_in), word(474, y, 'Btu/h'),
                 word(600, y, gas_out), word(624, y, 'Btu/h')]
    return headers + data


def image_words(words, low_token=None):
    return [{'box': list(w[:4]), 'text': w[4],
             'confidence': 30 if w[4] == low_token else 96} for w in words]


class ACEquipmentTests(unittest.TestCase):
    def test_labeled_hvac_schedule_reads_airflows_and_gas_capacities(self):
        result = schedule_candidates(ac_schedule(), 4, 'synthetic.pdf')
        self.assertEqual([r['tag'] for r in result], ['AC-7', 'AC-8'])
        for item, flow, outside, gas_in, gas_out in zip(
                result, (1800, 1100), (250, 150), (88000, 55000), (70000, 44000)):
            self.assertEqual(item['values']['design_cfm'], flow)
            self.assertEqual(item['values']['osa_cfm'], outside)
            self.assertEqual(item['values']['esp'], .45)
            self.assertEqual(item['values']['heating_input_btu'], gas_in)
            self.assertEqual(item['values']['heating_output_btu'], gas_out)
            self.assertEqual(item['text']['heating_type'], 'GAS')
            self.assertEqual(item['basis'], 'PLAN_SCHEDULE')
            self.assertEqual(item['reference'], 'page 4')
            self.assertNotIn('PACKAGED', item['text']['unit_type'])
            self.assertTrue(any(w[4] == 'EVAPORATOR'
                                for w in item['value_words']['design_cfm']))

    def test_global_ac_tag_and_mark_expansion_remain_disabled(self):
        self.assertIsNone(re.fullmatch(TAG, 'AC-7'))
        self.assertEqual(expand_marks('AC-7,8'), [])
        self.assertEqual(expand_marks('RTU-7,8'), ['RTU-7', 'RTU-8'])

    def test_electrical_ac_and_unlabeled_chart_are_not_hvac_equipment(self):
        electrical = phrase(180, 35, 'ELECTRICAL EQUIPMENT SCHEDULE')
        electrical += [word(10, 90, 'MARK'), word(150, 90, 'VOLTAGE'),
                       word(230, 90, 'PHASE'), word(10, 120, 'AC-7'),
                       word(150, 120, '240'), word(230, 120, '1')]
        self.assertEqual(parse_page(electrical, 1, 'electrical.pdf'), [])
        self.assertEqual(equipment_candidates(image_words(electrical), 'electrical.pdf', 1, 'ocr'), [])
        no_title = [w for w in ac_schedule() if w[1] != 35]
        self.assertEqual(schedule_candidates(no_title, 1, 'unlabeled.pdf'), [])
        no_fan_context = [w for w in ac_schedule() if w[1] != 60]
        self.assertEqual(schedule_candidates(no_fan_context, 1, 'ambiguous.pdf'), [])
        bare_ac = [word(10, 10, '120'), word(30, 10, 'V'), word(40, 10, 'AC')]
        self.assertEqual(parse_page(bare_ac, 1, 'power.pdf'), [])

    def test_prose_title_reference_does_not_authorize_ac(self):
        for title in ['SEE AIR CONDITIONING UNIT SCHEDULE',
                      'AIR CONDITIONING UNIT SCHEDULE FOR DETAILS']:
            self.assertEqual(schedule_candidates(ac_schedule(title), 1, 'notes.pdf'), [])

    def test_adjacent_hvac_schedule_does_not_authorize_electrical_ac(self):
        hvac = [(w[0]+800, w[1], w[2]+800, *w[3:]) for w in ac_schedule()]
        electrical = [word(10, 90, 'MARK'), word(150, 90, 'CFM'),
                      word(230, 90, 'ESP'), word(10, 120, 'AC-99'),
                      word(150, 120, '240'), word(230, 120, '1')]
        result = schedule_candidates(electrical + hvac, 1, 'adjacent.pdf')
        self.assertEqual([r['tag'] for r in result], ['AC-7', 'AC-8'])

    def test_duplicate_supply_columns_are_unresolved(self):
        words = ac_schedule() + [word(190, 90, 'CFM'), word(190, 120, '900'),
                                 word(190, 140, '800')]
        result = schedule_candidates(words, 1, 'ambiguous.pdf')
        self.assertEqual(len(result), 2)
        self.assertTrue(all('design_cfm' not in r['values'] for r in result))

    def test_split_mark_tokens_need_explicit_hyphen_and_hvac_context(self):
        words = [w for w in ac_schedule() if w[4] not in {'AC-7', 'AC-8'}]
        words += phrase(10, 120, 'AC - 7') + phrase(10, 140, 'AC - 8')
        self.assertEqual([r['tag'] for r in schedule_candidates(words, 1, 'split.pdf')],
                         ['AC-7', 'AC-8'])
        no_hyphen = [w for w in words if w[4] != '-']
        self.assertEqual(schedule_candidates(no_hyphen, 1, 'split.pdf'), [])

    def test_packaged_type_requires_printed_packaged_title(self):
        words = ac_schedule('PACKAGED GAS ELECTRIC UNIT SCHEDULE')
        for item in schedule_candidates(words, 1, 'packaged.pdf'):
            self.assertEqual(item['text']['unit_type'], 'PACKAGED GAS / ELECTRIC')

    def test_no_gas_capacity_or_type_without_explicit_units(self):
        words = [w for w in ac_schedule() if w[4] != 'Btu/h']
        for item in schedule_candidates(words, 1, 'no-units.pdf'):
            self.assertNotIn('heating_input_btu', item['values'])
            self.assertNotIn('heating_output_btu', item['values'])
            self.assertNotIn('heating_type', item['text'])

    def test_zero_gas_capacities_do_not_suggest_gas_heating(self):
        words = [(*w[:4], '0', *w[5:]) if w[1] >= 120 and w[0] in {450, 600}
                 else w for w in ac_schedule()]
        for item in schedule_candidates(words, 1, 'no-gas.pdf'):
            self.assertNotIn('heating_input_btu', item['values'])
            self.assertNotIn('heating_output_btu', item['values'])
            self.assertNotIn('heating_type', item['text'])
            self.assertIn('0 Btu/h', item['evidence'])
        for item in equipment_candidates(image_words(words), 'image.pdf', 1, 'ocr'):
            self.assertNotIn('heating_input_btu', item['review_values'])
            self.assertNotIn('heating_output_btu', item['review_values'])

    def test_header_only_gas_units_are_required_ocr_evidence(self):
        words = [w for w in ac_schedule() if w[4] != 'Btu/h']
        words += [word(455, 105, 'Btu/h'), word(610, 105, 'Btu/h')]
        native = schedule_candidates(words, 1, 'header-units.pdf')
        self.assertEqual(native[0]['values']['heating_input_btu'], 88000)
        result = equipment_candidates(image_words(words, 'Btu/h'), 'image.pdf', 1, 'ocr')
        self.assertNotIn('heating_input_btu', result[0]['review_values'])
        self.assertNotIn('heating_output_btu', result[0]['review_values'])
        self.assertEqual(result[0]['review_values']['design_cfm'], 1800)

    def test_measurement_headers_are_never_design_input(self):
        self.assertEqual(schedule_candidates(ac_schedule()+[word(50, 80, 'ACTUAL')],
                                             1, 'measurements.pdf'), [])

    def test_ocr_ac_values_stay_in_unverified_queue(self):
        result = equipment_candidates(image_words(ac_schedule()), 'image.pdf', 4, 'ocr')
        self.assertEqual([r['tag'] for r in result], ['AC-7', 'AC-8'])
        for item, flow in zip(result, (1800, 1100)):
            self.assertEqual(item['status'], 'UNVERIFIED')
            self.assertFalse(item['include'])
            self.assertEqual(item['values'], {})
            self.assertEqual(item['review_values']['design_cfm'], flow)
            self.assertEqual(item['template'], 'Air Moving Equipment.xlsx')

    def test_uncertain_ac_context_does_not_promote_image_values(self):
        for token in ('EVAPORATOR', 'CONDITIONING', 'AC-7'):
            result = equipment_candidates(image_words(ac_schedule(), token), 'image.pdf', 4, 'ocr')
            self.assertEqual(result[0]['review_values'], {})
            self.assertEqual(result[0]['values'], {})


if __name__ == '__main__':
    unittest.main()
