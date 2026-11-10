import unittest
from unittest.mock import patch
import abp_server as app
class CoverageTests(unittest.TestCase):
 def native(self,coverage):
  return {'status':'completed_native_stage','source':{'bytes':10,'sha256':'a'*64},'ocr':{'review_candidates':[],'warnings':[],'coverage':coverage},'warnings':[],'outlets':[],'chunks':[],'candidates':[]}
 def test_scan_keeps_source_coverage_and_bounds_overflow(self):
  coverage=[{'page':1,'status':'budget_skipped'}]*600
  with patch.object(app,'bounded_pdf_scan',return_value=self.native(coverage)):
   result=app.read_sources([('a.pdf',b''),('b.pdf',b'')])
  self.assertEqual(len(result['image_coverage']),1000)
  self.assertTrue(result['image_coverage_truncated'])
  self.assertEqual(result['image_coverage'][0]['source'],'a.pdf')
  self.assertEqual(result['image_coverage'][-1]['source'],'b.pdf')
  self.assertTrue(any('coverage display limit' in w for w in result['warnings']))
 def test_missing_ocr_coverage_marks_every_page_unexamined(self):
  native=self.native([]);native['pages']=3
  with patch.object(app,'bounded_pdf_scan',return_value=native):
   result=app.read_sources([('a.pdf',b'')])
  self.assertEqual([p['page'] for p in result['image_coverage']],[1,2,3])
  self.assertTrue(all(p['status']=='image_reading_unavailable' for p in result['image_coverage']))
 def test_hd_generic_supply_cannot_become_exhaust(self):
  result=app.read_sources([('synthetic.csv',b'TAG,SUPPLY CFM\nHD-1,1800\n')])
  self.assertEqual(result['records'],[])
 def test_hd_preserved_in_explicit_review(self):
  self.assertTrue(app.REVIEW_TAGS.fullmatch('HD-1'))
  self.assertFalse(app.TAGS.fullmatch('HD-1'))
  payload={'project':'Synthetic','standard':'Commercial','templates':['Kitchen Hood.xlsx'],'records':[{'tag':'HD-1','status':'UNVERIFIED','template':'Kitchen Hood.xlsx','design_cfm':None}]}
  app.validate_payload(payload)
  self.assertEqual(payload['records'][0]['tag'],'HD-1')
if __name__=='__main__':unittest.main()
