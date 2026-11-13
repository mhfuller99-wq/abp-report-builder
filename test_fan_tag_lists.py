"""Project tags on manufacturer selection pages, not inferred model aliases."""
import time
import unittest
import pymupdf
from abp_schedule import parse_fan_submittal
from abp_ocr import prioritized_pages


def document(labels):
    doc=pymupdf.open();page=doc.new_page()
    lines=labels+['Ceiling Exhaust Fan','Performance','Requested Volume (CFM) 85',
                  'Actual Volume (CFM) 82','Total External SP (in. wg) 0.30','Fan RPM 800',
                  'Voltage/Cycle/Phase 115/60/1']
    for index,line in enumerate(lines):page.insert_text((20,30+index*20),line,fontsize=9)
    return doc


class FanTagTests(unittest.TestCase):
    def test_explicit_shared_tags_keep_selected_and_requested_flows_separate(self):
        with document(['Tags: EF-7 EF-8','Mark: INTERNAL07']) as doc:
            found=parse_fan_submittal(doc,'synthetic.pdf')
        self.assertEqual([c['tag'] for c in found],['EF-7','EF-8'])
        self.assertTrue(all(c['values']['design_cfm']==85 and c['values']['selected_cfm']==82 for c in found))
        self.assertTrue(all('actual_cfm' not in c['values'] for c in found))

    def test_conflicting_tag_lists_and_mixed_equipment_families_are_rejected(self):
        for labels in (['Tags: EF-7 EF-8','Mark: EF-9'],['Tags: EF-7 RTU-8'],['Mark: INTERNAL07']):
            with self.subTest(labels=labels),document(labels) as doc:
                self.assertEqual(parse_fan_submittal(doc,'synthetic.pdf'),[])

    def test_existing_mark_range_remains_supported(self):
        with document(['Mark: EF-7 THRU EF-9']) as doc:
            self.assertEqual([c['tag'] for c in parse_fan_submittal(doc,'synthetic.pdf')],['EF-7','EF-8','EF-9'])

    def test_tagged_selection_precedes_catalog_without_dropping_pages(self):
        with document(['Tag: EF-7']) as selection,pymupdf.open() as doc:
            doc.new_page().insert_text((20,30),'Product catalog')
            doc.insert_pdf(selection)
            self.assertEqual(prioritized_pages(doc,None,time.monotonic()+2),[1,0])


if __name__=='__main__':unittest.main()
