import unittest
from abp_ocr import equipment_candidates,word
from test_schedule_pdf import synthetic_schedule_pdf

class EquipmentImageTests(unittest.TestCase):
    def words(self):
        import pymupdf
        with pymupdf.open(stream=synthetic_schedule_pdf(),filetype='pdf') as doc:
            return [word(*w[:5],confidence=95) for w in doc[0].get_text('words')]
    def test_values_stay_in_unverified_image_queue(self):
        candidates=equipment_candidates(self.words(),'synthetic.pdf',7,'ocr')
        self.assertTrue(candidates)
        self.assertTrue(any(c['review_values'] for c in candidates))
        for c in candidates:
            self.assertEqual(c['kind'],'equipment');self.assertEqual(c['status'],'UNVERIFIED')
            self.assertEqual(c['values'],{});self.assertFalse(c['include']);self.assertEqual(c['page'],7)
    def test_low_confidence_and_actual_report_values_not_used(self):
        words=self.words();words[0]['confidence']=40
        self.assertTrue(all(c['review_values']=={} for c in equipment_candidates(words,'a.pdf',1,'ocr')))
        self.assertEqual(equipment_candidates(words+[word(0,0,20,20,'ACTUAL',95)],'a.pdf',1,'ocr'),[])

if __name__=='__main__':unittest.main()
