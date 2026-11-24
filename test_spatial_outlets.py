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
    def test_numbered_supply_device_families_keep_physical_callout_rules(self):
        words=[(10,10,240,20,'MECHANICAL FLOOR PLAN',99)]
        for i,mark in enumerate(['SAG-7','SAD-8','SAR-9','SD-10','EAG-7','RAG-8','EF-9']):
            x=100+i*100
            words.extend([(x-20,100,x+20,110,mark,i),(x-10,114,x+10,124,'175',i)])
        found=centered_outlets(words,1,'synthetic.pdf')
        self.assertEqual([r['type'] for r in found],['SAG-7','SAD-8','SAR-9','SD-10'])
        self.assertTrue(all(not r['include'] and r['size']==r['system']==r['location']=='' for r in found))
        # A nearby note, two competing flows, and a schedule title each fail.
        prose=words+[(75,100,99,110,'MOUNT',88)]
        self.assertNotIn('SAG-7',[r['type'] for r in centered_outlets(prose,1,'synthetic.pdf')])
        ambiguous=words+[(90,116,110,126,'195',89)]
        self.assertNotIn('SAG-7',[r['type'] for r in centered_outlets(ambiguous,1,'synthetic.pdf')])
        words[0]=(*words[0][:4],'SUPPLY AIR DEVICE SCHEDULE',99)
        self.assertEqual(centered_outlets(words,1,'synthetic.pdf'),[])

    def test_repeated_centered_symbols_and_comma_flow(self):
        found=centered_outlets(sample(),2,'plan.pdf')
        self.assertEqual([o['design_cfm'] for o in found],[250,250,1200])
        self.assertTrue(all(o['include'] is False and o['system']=='' and o['size']=='' for o in found))
        self.assertEqual(len(distinct_outlets(found+found)),3)

    def test_each_marker_requires_centering_and_reviewed_locations(self):
        words=sample()+[(89,83,94,93,'2',91),(96,83,118,93,'EACH',91)]
        found=centered_outlets(words,1,'plan.pdf')
        self.assertEqual(len(found),3)
        self.assertEqual([o.get('quantity') for o in found],[2,None,None])
        self.assertTrue(found[0]['quantity_unresolved'])
        self.assertFalse(found[0]['include'])
        self.assertEqual(found[0]['design_cfm'],250)
        # "2 EACH UNIT" is adjacent prose. A distant note also cannot set a count.
        prose=words+[(120,83,142,93,'UNIT',91)]
        self.assertNotIn('quantity',centered_outlets(prose,1,'plan.pdf')[0])
        moved=words[:-2]+[(45,83,50,93,'2',91),(52,83,74,93,'EACH',91)]
        self.assertNotIn('quantity',centered_outlets(moved,1,'plan.pdf')[0])
        ocr_words=[{'box':list(w[:4]),'text':w[4],'confidence':95} for w in words]
        ocr=diffuser_candidates(ocr_words,'plan.pdf',1)
        self.assertEqual(ocr[0]['quantity'],2)
        ocr_words[-2]['confidence']=40
        uncertain=diffuser_candidates(ocr_words,'plan.pdf',1)[0]
        self.assertTrue(uncertain['quantity_unresolved'])
        self.assertNotIn('quantity',uncertain)
        self.assertEqual(uncertain['review_values']['design_cfm'],250)

    def test_notes_schedules_and_competing_flow_are_not_outlets(self):
        w=sample();w[0]=(*w[0][:4],'MECHANICAL SCHEDULE',99)
        self.assertEqual(centered_outlets(w,1,'schedules.pdf'),[])
        w[0]=(*w[0][:4],'MECHANICAL PLANS WITH THEIR QUOTE REQUEST',99)
        self.assertEqual(centered_outlets(w,1,'notes.pdf'),[])
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

    def test_mixed_floor_plan_and_symbol_schedule(self):
        from abp_symbol_examples import symbol_examples, is_symbol_example
        doc=pymupdf.open()
        page=doc.new_page(width=760,height=500)
        page.insert_text((20,30),'2nd Floor Plan - Mechanical')
        page.insert_text((40,90),'HVAC SYMBOL SCHEDULE')
        page.insert_text((150,158),'TYPE "C" CEILING DIFFUSER. BALANCE TO 250 CFM.',fontsize=10)
        for x,y in [(65,160),(410,160),(610,230)]:
            page.insert_text((x,y),'C',fontsize=10)
            page.insert_text((x-5,y+17),'250',fontsize=10)
        words=page.get_text('words')
        regions=symbol_examples(words)
        self.assertEqual(len(regions),1)
        self.assertFalse(symbol_examples([w for w in words if w[4]!='SYMBOL']))
        self.assertFalse(symbol_examples([w for w in words if w[4]!='BALANCE']))
        self.assertFalse(is_symbol_example({'type':'B','position':[65,155],'design_cfm':250},regions))
        self.assertFalse(is_symbol_example({'type':'C','position':[65,155],'design_cfm':225},regions))
        self.assertTrue(is_symbol_example({'type':'C','position':[65,155],
                                          'review_values':{'design_cfm':250}},regions))
        snapshots=[]
        _,_,outlets=parse_pdf('plan.pdf',doc.tobytes(),checkpoint=lambda *args:snapshots.append(list(args[2])))
        self.assertEqual([o['design_cfm'] for o in outlets],[250,250])
        self.assertTrue(all(o['position'][0]>400 for o in outlets))
        self.assertTrue(all(len(items)==2 for items in snapshots))
        # Tile OCR may see the example without seeing its explanatory paragraph.
        tile_words=[{'box':list(w[:4]),'text':w[4],'confidence':95} for w in words
                    if w[4] in ('C','250') and (w[0]<80 or w[0]>400)]
        saved=[]
        ocr=extract_local(doc.tobytes(),'MECHANICAL-FLOOR-PLAN.pdf',Budget(max_regions_per_page=3),
                          region_engine=lambda *a,**kw:tile_words,
                          selector=lambda *a,**kw:([[0,0,760,500]],1,False),
                          checkpoint=lambda report:saved.append(list(report['review_candidates'])))
        out=[c for c in ocr['review_candidates'] if c['kind']=='diffuser']
        self.assertEqual(len(out),2)
        self.assertTrue(all(c['position'][0]>400 for candidates in saved for c in candidates if c['kind']=='diffuser'))
        doc.close()

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
