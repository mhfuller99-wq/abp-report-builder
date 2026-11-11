import unittest
import pymupdf
from abp_outlets import centered_outlets, distinct_outlets
from abp_ocr import diffuser_candidates, extract_local, Budget
from abp_schedule import parse_pdf

def sample():
    words=[(10,10,240,20,'2nd Floor Plan - Mechanical',99)]
    for i,flow in enumerate(['250','250','1,200']):
        x=100+i*100
        words.extend([(x,100,x+8,110,'C',i),(x-5,114,x+13,124,flow,i)])
    return words

class SpatialOutletTests(unittest.TestCase):
    def test_repeated_centered_symbols_and_comma_flow(self):
        found=centered_outlets(sample(),2,'plan.pdf')
        self.assertEqual([o['design_cfm'] for o in found],[250,250,1200])
        self.assertTrue(all(o['include'] is False and o['system']=='' and o['size']=='' for o in found))
        self.assertEqual(len(distinct_outlets(found+found)),3)

    def test_notes_schedules_and_competing_flow_are_not_outlets(self):
        w=sample();w[0]=(*w[0][:4],'MECHANICAL SCHEDULE',99)
        self.assertEqual(centered_outlets(w,1,'schedules.pdf'),[])
        w=sample();w.append((96,116,114,126,'350',55))
        self.assertEqual(len(centered_outlets(w,1,'plan.pdf')),2)
        w=sample();w.append((90,101,130,111,'NOTE',56))
        self.assertEqual(len(centered_outlets(w,1,'plan.pdf')),2)

    def test_nearby_duct_size_is_not_prose_or_neck(self):
        w=sample();w.append((120,101,145,111,'12"x8"',45))
        self.assertEqual(len(centered_outlets(w,1,'plan.pdf')),3)
        self.assertEqual(centered_outlets(w,1,'plan.pdf')[0]['size'],'')

    def test_ocr_confidence_is_local_and_values_remain_review_only(self):
        words=[{'box':list(w[:4]),'text':w[4],'confidence':95} for w in sample()]
        words.append({'box':[700,700,710,710],'text':'unrelated','confidence':12})
        found=diffuser_candidates(words,'plan.pdf',1)
        self.assertEqual([o['review_values']['design_cfm'] for o in found],[250,250,1200])
        self.assertTrue(all(o['values']=={} and o['include'] is False for o in found))
        words[2]['confidence']=30
        self.assertEqual(diffuser_candidates(words,'plan.pdf',1)[0]['review_values'],{})

    def test_real_pdf_path_uses_native_reader(self):
        d=pymupdf.open();p=d.new_page(width=600,height=500)
        p.insert_text((20,30),'2nd Floor Plan - Mechanical')
        for x in [100,200,300]:
            p.insert_text((x,100),'C',fontsize=10)
            p.insert_text((x-5,117),'250',fontsize=10)
        _,_,outlets=parse_pdf('plan.pdf',d.tobytes())
        self.assertEqual(len(outlets),3)
        self.assertEqual(sum(o['design_cfm'] for o in outlets),750)

    def test_plan_tiles_preserve_budget_and_avoid_overlap_duplicates(self):
        d=pymupdf.open();d.new_page(width=600,height=400)
        calls=[]
        words=[{'box':list(w[:4]),'text':w[4],'confidence':95} for w in sample()[1:]]
        def engine(page,pixels,remaining,**kw):calls.append(pixels);return words
        r=extract_local(d.tobytes(),'MECHANICAL-FLOOR-PLAN.pdf',Budget(max_regions_per_page=3),
                        region_engine=engine,selector=lambda *a,**k:([[0,0,100,100]],1,False))
        self.assertLessEqual(len(calls),3)
        self.assertLessEqual(r['pixels_processed'],Budget().max_page_pixels)
        self.assertEqual(len(r['review_candidates']),3)
        self.assertEqual(r['coverage'][0]['selection'],'plan_tiles')
        self.assertTrue(any(x['status']=='budget_skipped' for x in r['coverage'][0]['regions']))

if __name__=='__main__':unittest.main()
