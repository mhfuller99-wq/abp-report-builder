"""Physical outlet identity and conflicting OCR observations; synthetic only."""
import copy
import unittest

from abp_ocr_candidates import merge_diffuser_candidate


def candidate(flow=None, *, x=100, source='plan.pdf', page=1, kind='824CD', printed='824CD / 171CFM', type_confidence=None):
    return {'kind': 'diffuser', 'source': source, 'page': page, 'type': kind,
            'position': [x, 100], 'region': [0, 0, 600, 600], 'size': '',
            'values': {}, 'review_values': {} if flow is None else {'design_cfm': flow},
            'status': 'UNVERIFIED', 'include': False, 'type_confidence': type_confidence,
            'evidence_text': printed + '; source-linked candidate', 'review_reasons': []}


class OCRCandidateTests(unittest.TestCase):
    def test_same_printed_reading_upgrades_blank_without_duplicate_or_verification(self):
        existing = [candidate()]
        incoming = candidate(171, x=101)
        incoming['region'] = [90, 90, 650, 650]
        self.assertTrue(merge_diffuser_candidate(existing, incoming))
        self.assertEqual(len(existing), 1)
        self.assertEqual(existing[0]['review_values'], {'design_cfm': 171})
        self.assertEqual(len(existing[0]['ocr_readings']), 2)
        self.assertEqual(existing[0]['values'], {})
        self.assertFalse(existing[0]['include'])
        self.assertEqual(existing[0]['status'], 'UNVERIFIED')

    def test_low_confidence_repeat_does_not_erase_stronger_reading(self):
        existing = [candidate(171)]
        self.assertTrue(merge_diffuser_candidate(existing, candidate()))
        self.assertEqual(existing[0]['review_values'], {'design_cfm': 171})

    def test_different_printed_value_cannot_fill_blank(self):
        existing = [candidate(printed='824CD / 17ICFM')]
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171)))
        self.assertEqual(existing[0]['review_values'], {})
        self.assertTrue(existing[0]['printed_evidence_conflict'])
        self.assertEqual(existing[0]['ocr_readings'][1]['review_values'], {'design_cfm': 171})

    def test_conflicting_values_stay_blank_even_after_later_matching_read(self):
        existing = [candidate(171)]
        self.assertTrue(merge_diffuser_candidate(existing, candidate(181, printed='824CD / 181CFM')))
        self.assertEqual(existing[0]['review_values'], {})
        self.assertEqual(existing[0]['field_conflicts'], {'design_cfm': [171, 181]})
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171)))
        self.assertEqual(existing[0]['review_values'], {})
        self.assertEqual(existing[0]['field_conflicts'], {'design_cfm': [171, 181]})

    def test_equal_flows_in_same_crop_remain_distinct_devices(self):
        existing = [candidate(171)]
        self.assertFalse(merge_diffuser_candidate(existing, candidate(171, x=150)))
        self.assertNotIn('ocr_readings', existing[0])

    def test_same_position_on_other_page_or_source_is_distinct(self):
        for incoming in (candidate(171, page=2), candidate(171, source='other.pdf')):
            self.assertFalse(merge_diffuser_candidate([candidate(171)], incoming))

    def test_strong_type_is_preserved_against_weaker_type_without_duplicate(self):
        existing = [candidate(171, type_confidence=96)]
        incoming = candidate(171, kind='324CD', printed='324CD / 171CFM', type_confidence=12)
        self.assertTrue(merge_diffuser_candidate(existing, incoming))
        self.assertEqual(len(existing), 1)
        self.assertEqual(existing[0]['type'], '824CD')
        self.assertEqual(existing[0]['review_values'], {'design_cfm': 171})
        self.assertEqual(existing[0]['type_conflicts'], ['824CD', '324CD'])
        self.assertEqual(len(existing[0]['ocr_readings']), 2)

    def test_strong_type_replaces_weak_type_but_not_disagreeing_printed_flow(self):
        existing = [candidate(kind='324CD', printed='324CD / 181CFM', type_confidence=12)]
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171, type_confidence=96)))
        self.assertEqual(existing[0]['type'], '824CD')
        self.assertEqual(existing[0]['review_values'], {})
        self.assertEqual(existing[0]['ocr_readings'][0]['type'], '324CD')
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171, type_confidence=96)))
        self.assertEqual(existing[0]['review_values'], {})

    def test_agreeing_literal_flow_can_fill_while_weak_type_is_corrected(self):
        existing = [candidate(kind='324CD', printed='324CD / 171CFM', type_confidence=12)]
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171, type_confidence=96)))
        self.assertEqual(existing[0]['type'], '824CD')
        self.assertEqual(existing[0]['review_values'], {'design_cfm': 171})

    def test_two_strong_type_readings_stay_unresolved_after_later_repeat(self):
        existing = [candidate(171, type_confidence=96)]
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171, kind='324CD',
                         printed='324CD / 171CFM', type_confidence=92)))
        self.assertEqual(existing[0]['type'], '')
        self.assertTrue(existing[0]['type_conflict_unresolved'])
        self.assertTrue(merge_diffuser_candidate(existing, candidate(171, type_confidence=99)))
        self.assertEqual(existing[0]['type'], '')

    def test_missing_type_confidence_does_not_choose_a_winner(self):
        for score in (None, float('nan'), '95'):
            existing = [candidate(171, type_confidence=96)]
            self.assertTrue(merge_diffuser_candidate(existing, candidate(171, kind='324CD',
                             printed='324CD / 171CFM', type_confidence=score)))
            self.assertEqual(existing[0]['type'], '')
            self.assertTrue(existing[0]['type_conflict_unresolved'])

    def test_missing_position_and_reviewed_user_choice_are_not_merged(self):
        for altered in ('no_position', 'selected', 'verified'):
            old = candidate(171)
            if altered == 'no_position':
                old.pop('position')
            elif altered == 'selected':
                old['include'] = True
            else:
                old['status'] = 'VERIFIED'
            before = copy.deepcopy(old)
            self.assertFalse(merge_diffuser_candidate([old], candidate(171)))
            self.assertEqual(old, before)

    def test_ambiguous_adjacent_positions_are_not_arbitrarily_merged(self):
        existing = [candidate(171, x=97), candidate(171, x=103)]
        incoming = candidate(171, x=100)
        self.assertFalse(merge_diffuser_candidate(existing, incoming))
        self.assertTrue(incoming['review_reasons'])

    def test_repeated_identical_observations_do_not_grow_log(self):
        existing = [candidate(171)]
        for _ in range(100):
            self.assertTrue(merge_diffuser_candidate(existing, candidate(171)))
        self.assertEqual(len(existing[0]['ocr_readings']), 1)


if __name__ == '__main__':
    unittest.main()
