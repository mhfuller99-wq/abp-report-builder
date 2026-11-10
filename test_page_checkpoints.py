import copy,unittest
from abp_schedule import parse_pdf
from abp_ocr import extract_local,Budget
from test_schedule_pdf import synthetic_schedule_pdf

class PageCheckpointTests(unittest.TestCase):
    def pages(self):
        import pymupdf
        with pymupdf.open(stream=synthetic_schedule_pdf(),filetype='pdf') as src,pymupdf.open() as doc:
            doc.insert_pdf(src);doc.insert_pdf(src);return doc.tobytes()
    def test_native_selected_pages_keep_original_page_references(self):
        checkpoints=[]
        found,warnings,outlets=parse_pdf('two.pdf',self.pages(),page_numbers=[2],checkpoint=lambda f,w,o,p,done:checkpoints.append((list(p),done)))
        self.assertTrue(found);self.assertTrue(all(c['reference']=='page 2' for c in found))
        self.assertEqual(checkpoints[-1],([2],True));self.assertFalse(checkpoints[0][1])
    def test_image_checkpoint_precedes_next_page_and_does_not_claim_takeoff(self):
        retained=[]
        result=extract_local(self.pages(),page_numbers=[1],checkpoint=lambda r:retained.append(copy.deepcopy(r)))
        self.assertEqual([c['page'] for c in result['coverage']],[1]);self.assertFalse(result['complete_takeoff'])
        self.assertTrue(any(len(r['coverage'])==1 for r in retained))

if __name__=='__main__':unittest.main()
