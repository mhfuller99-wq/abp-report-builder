import unittest
from abp_outlets import numbered_supply_outlets

def words():
    result=[(0,0,280,10,'MECHANICAL - SERVICE HVAC PLAN')]
    for x in [100,200,300,400]:
        result += [(x,100,x+12,113,'S1'),(x-12,111,x+4,124,'300'),(x+6,111,x+26,124,'CFM')]
    return result

class NumberedSupplyTests(unittest.TestCase):
    def test_repeated_physical_devices_remain_separate_and_unreviewed(self):
        result=numbered_supply_outlets(words(),1,'plan.pdf')
        self.assertEqual([r['design_cfm'] for r in result],[300]*4)
        self.assertTrue(all(not r['include'] and r['size']==r['system']==r['location']=='' for r in result))
    def test_no_prose_or_return_or_bare_number(self):
        for title in ['SEE MECHANICAL - SERVICE HVAC PLAN','MECHANICAL SCHEDULE']:
            w=words();w[0]=(*w[0][:4],title)
            self.assertEqual(numbered_supply_outlets(w,1,'plan.pdf'),[])
        for old,new in [('S1','R1'),('CFM','NOTE')]:
            w=[(*v[:4],new if v[4]==old else v[4]) for v in words()]
            self.assertEqual(numbered_supply_outlets(w,1,'plan.pdf'),[])
    def test_duplicate_text_and_competing_flows(self):
        self.assertEqual(len(numbered_supply_outlets(words()*2,1,'plan.pdf')),4)
        w=words()+[(88,111,104,124,'350')]
        self.assertEqual(len(numbered_supply_outlets(w,1,'plan.pdf')),3)
