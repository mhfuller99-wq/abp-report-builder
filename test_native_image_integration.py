"""Raw scan aggregation must retain native data and flag conflicting image repeats."""
import copy
import unittest
from unittest.mock import patch
import abp_server


def native():
    return {'status': 'completed_native_stage', 'source': {'bytes': 1, 'sha256': 'a'*64},
            'pages': 1, 'warnings': [], 'chunks': [], 'candidates': [],
            'outlets': [{'source': 'plan.pdf', 'reference': 'page 1', 'position': [100, 100],
                         'position_coordinate_space': 'displayed_pdf_points',
                         'type': 'SAR', 'size': '14x6', 'design_cfm': 215, 'include': False}]}


def image():
    return {'warnings': [], 'coverage': [{'page': 1, 'status': 'review_required'}],
            'review_candidates': [{'kind': 'diffuser', 'tag': '', 'source': 'plan.pdf', 'page': 1,
                                   'position': [101, 100], 'position_coordinate_space': 'displayed_pdf_points',
                                   'type': 'SAR', 'size': '1x6', 'review_values': {'design_cfm': 415},
                                   'values': {}, 'include': False, 'status': 'UNVERIFIED',
                                   'evidence_text': '1x6 SAR / 415 CFM', 'review_reasons': []}]}


class NativeImageIntegrationTests(unittest.TestCase):
    def check_result(self, result):
        self.assertEqual(result['diffusers'], native()['outlets'])
        candidate = result['image_review'][0]
        self.assertTrue(candidate['native_outlet_match'])
        self.assertEqual(candidate['review_values'], {})
        self.assertEqual(candidate['size'], '')
        self.assertFalse(candidate['include'])
        self.assertEqual(candidate['status'], 'UNVERIFIED')
        self.assertFalse(result['complete_takeoff'])
        self.assertIn('415', ' '.join(candidate['review_reasons']))
        self.assertIn('215', ' '.join(candidate['review_reasons']))

    def test_direct_scan_checks_native_and_image_without_changing_native(self):
        with patch.object(abp_server, 'bounded_pdf_scan', side_effect=lambda *a, **k: native()), \
                patch('abp_resilient.deferred_ocr', side_effect=lambda *a, **k: image()):
            self.check_result(abp_server.read_sources([('plan.pdf', b'x')]))

    def test_cached_runner_results_are_checked_again_after_retry(self):
        class Runner:
            def native(self, *args, **kw): return native()
            def image(self, *args, **kw): return image()
        self.check_result(abp_server.read_sources([('plan.pdf', b'x')], runner=Runner()))

    def test_duplicate_source_names_cannot_cross_match_different_documents(self):
        with patch.object(abp_server, 'bounded_pdf_scan', side_effect=lambda *a, **k: native()), \
                patch('abp_resilient.deferred_ocr', side_effect=lambda *a, **k: image()):
            result = abp_server.read_sources([('plan.pdf', b'x'), ('plan.pdf', b'y')])
        self.assertTrue(all(not c.get('native_outlet_match') for c in result['image_review']))
        self.assertTrue(all(c['review_values'] == {'design_cfm': 415} for c in result['image_review']))


if __name__ == '__main__':
    unittest.main()
