"""Synthetic native/OCR integration for sized supply-register labels."""
import unittest
import pymupdf
from abp_ocr import diffuser_candidates
from abp_schedule import parse_pdf


def word(x, y, text, confidence=96):
    return {'text': text, 'box': [x, y, x + len(text)*5, y+9], 'confidence': confidence}


class RegisterIntegrationTests(unittest.TestCase):
    def test_native_pdf_preserves_two_distinct_registers_and_ignores_return(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=800, height=600)
            page.insert_text((30, 40), 'FLOOR PLAN - HVAC', fontsize=12)
            for x, mark, flow in [(100, 'SAR', 215), (350, 'SAR', 215), (600, 'RAG', 430)]:
                page.insert_text((x, 130), '14x6 ' + mark, fontsize=10)
                page.insert_text((x, 142), str(flow) + ' CFM', fontsize=10)
            _, _, found = parse_pdf('synthetic-registers.pdf', doc.tobytes())
        self.assertEqual(len(found), 2)
        self.assertEqual([(o['type'], o['size'], o['design_cfm']) for o in found],
                         [('SAR', '14x6', 215)]*2)
        self.assertEqual(len({tuple(o['position']) for o in found}), 2)
        self.assertTrue(all(not o['include'] and not o['system'] and not o['location'] for o in found))
        self.assertTrue(all('neck_in' not in o for o in found))

    def test_ocr_confidence_gates_the_entire_sized_callout(self):
        words = [word(20, 20, 'HVAC PLAN'), word(100, 100, '14x6'), word(125, 100, 'SAR'),
                 word(100, 112, '215'), word(120, 112, 'CFM')]
        result = diffuser_candidates(words, 'synthetic.pdf', 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['review_values'], {'design_cfm': 215})
        self.assertFalse(result[0]['include'])
        self.assertEqual(result[0]['values'], {})
        self.assertEqual(result[0]['status'], 'UNVERIFIED')
        words[1]['confidence'] = 30
        result = diffuser_candidates(words, 'synthetic.pdf', 1)
        self.assertEqual(result[0]['review_values'], {})


if __name__ == '__main__':
    unittest.main()
