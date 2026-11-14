import unittest
from abp_ocr import word
from abp_product_tables import candidates,product_tag,same_row,uncertain_rows

def row(text,y=100):
    x=0;out=[]
    for token in text.split():
        out.append(word(x,y,x+len(token)*5,y+8,token,95));x+=len(token)*5+4
    return out
NATIVE=row('Product Report Tag(s): RTU-3',10)

class ProductTableTests(unittest.TestCase):
    def test_exact_labels_do_not_confuse_total_pressure_or_power(self):
        w=row('Airflow 1500 cfm')+row('Design ESP 0.600 in H2O',120)+row('Total SP 0.829 in H2O',140)+row('Supply Motor Horsepower 0.750 hp',160)+row('Total Supply Motor Operating Power 0.320 hp',180)
        result=candidates(w,NATIVE,'selection.pdf',2)[0]
        self.assertEqual(result['review_values'],{'design_cfm':1500,'esp':.6,'motor_hp':.75})
        self.assertEqual(result['values'],{});self.assertFalse(result['include'])
    def test_identity_low_confidence_actuals_and_conflicts(self):
        w=row('Airflow 1500 cfm')
        self.assertEqual(candidates(w,[], 's.pdf',1),[])
        self.assertIsNone(product_tag(NATIVE+row('RTU-4',20)))
        w[1]['confidence']=40
        self.assertEqual(candidates(w,NATIVE,'s.pdf',1),[])
        self.assertEqual(candidates(row('Airflow 1500 cfm ACTUAL'),NATIVE,'s.pdf',1),[])
        self.assertEqual(candidates(row('Airflow 1500 cfm')+row('Airflow 1600 cfm',120),NATIVE,'s.pdf',1),[])
    def test_reread_cannot_change_digits_or_accept_uncertain_units(self):
        original=row('Design ESP 0.600 in H2O')
        original[-1]['confidence']=30
        self.assertEqual(len(uncertain_rows(original)),1)
        self.assertTrue(same_row(original,row('Design ESP 0.600 in H20')))
        self.assertFalse(same_row(original,row('Design ESP 0.800 in H20')))
        revised=row('Design ESP 0.600 in H20');revised[-1]['confidence']=79
        self.assertFalse(same_row(original,revised))
    def test_product_pages_take_priority_without_dropping_other_pages(self):
        import pymupdf,time
        from abp_ocr import prioritized_pages
        with pymupdf.open() as doc:
            doc.new_page().insert_text((30,40),'General catalog information')
            doc.new_page().insert_text((30,40),'Product Report Tag(s): RTU-3')
            self.assertEqual(prioritized_pages(doc,None,time.monotonic()+5),[1,0])
            self.assertEqual(prioritized_pages(doc,{1},time.monotonic()+5),[0])
    def test_distant_cells_and_excessive_anchors_fail_closed(self):
        w=row('Airflow 1500 cfm')
        for item in w[1:]:item['box'][0]+=500;item['box'][2]+=500
        self.assertEqual(candidates(w,NATIVE,'s.pdf',1),[])
        self.assertEqual(uncertain_rows(row('Airflow '*33)),[])
