"""Synthetic explicit supply-register callouts; no client fixture data."""
import random
import unittest

from abp_outlets import sized_registers


def callout(x=100,y=100,kind='SAR',value='240',size='10x6',joined=False):
    if joined:
        return [(x,y,x+41,y+10,size+kind),(x+3,y+12,x+38,y+22,value+'CFM')]
    return [(x,y,x+22,y+10,size),(x+24,y,x+42,y+10,kind),
            (x+3,y+12,x+20,y+22,value),(x+22,y+12,x+40,y+22,'CFM')]


def plan(words):
    return [(10,10,180,20,'HVAC FLOOR PLAN')]+words


class SizedRegisterTests(unittest.TestCase):
    def test_split_label_and_airflow_preserve_register_size_only(self):
        found=sized_registers(plan(callout()),1,'plan.pdf')
        self.assertEqual(len(found),1)
        item=found[0]
        self.assertEqual((item['type'],item['size'],item['design_cfm']),('SAR','10x6',240))
        self.assertEqual(item['shape'],'rectangular')
        self.assertFalse(item['include']);self.assertEqual(item['system'],'');self.assertEqual(item['location'],'')
        self.assertNotIn('neck_in',item)
        self.assertEqual(item['evidence_box'],[100,100,142,122])

    def test_joined_words_quotes_multiplication_sign_and_comma_flow(self):
        for size in ('10x6','10"x6"','10×6'):
            found=sized_registers(callout(size=size,value='1,200',joined=True),3,'plan.pdf',plan_confirmed=True)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['design_cfm'],1200)
            self.assertEqual(found[0]['size'],'10x6')

    def test_shuffled_words_and_separate_equal_flow_devices(self):
        words=plan(callout()+callout(250,200))
        random.Random(3).shuffle(words)
        found=sized_registers(words,1,'plan.pdf')
        self.assertEqual([o['position'] for o in found],[[100,100],[250,200]])
        self.assertEqual([o['design_cfm'] for o in found],[240,240])

    def test_duplicate_pdf_words_do_not_duplicate_physical_device(self):
        self.assertEqual(len(sized_registers(plan(callout()*2),1,'plan.pdf')),1)

    def test_return_exhaust_duct_and_bare_airflow_are_excluded(self):
        for kind in ('RAG','EAR','EAG','SA','DUCT',''):
            self.assertEqual(sized_registers(plan(callout(kind=kind)),1,'plan.pdf'),[])
        words=callout()[:-1]
        self.assertEqual(sized_registers(plan(words),1,'plan.pdf'),[])

    def test_nearby_return_is_distinct_and_cannot_supply_shared_airflow(self):
        found=sized_registers(plan(callout()+callout(150,100,kind='RAG',value='350')),1,'plan.pdf')
        self.assertEqual(len(found),1);self.assertEqual(found[0]['design_cfm'],240)
        # A second valid label above the same flow makes ownership ambiguous.
        words=callout()+[(101,99,142,109,'10x6RAG')]
        self.assertEqual(sized_registers(plan(words),1,'plan.pdf'),[])

    def test_competing_flows_or_shared_cfm_are_not_silently_chosen(self):
        words=callout()+[(103,113,138,123,'360CFM')]
        self.assertEqual(sized_registers(plan(words),1,'plan.pdf'),[])
        words=callout()+[(104,112,119,122,'360')]
        self.assertEqual(sized_registers(plan(words),1,'plan.pdf'),[])

    def test_nonplan_and_nearby_legend_or_schedule_example_are_excluded(self):
        self.assertEqual(sized_registers(callout(),1,'schedule.pdf'),[])
        for heading in ('LEGEND','SCHEDULE','SYMBOL','EXAMPLE','ACTUAL','MEASURED'):
            words=plan(callout()+[(90,65,150,75,heading)])
            self.assertEqual(sized_registers(words,1,'plan.pdf'),[])

    def test_nearby_round_duct_does_not_replace_rectangular_register_dimensions(self):
        words=plan(callout()+[(152,101,170,111,'8"ø')])
        item=sized_registers(words,1,'plan.pdf')[0]
        self.assertEqual(item['size'],'10x6');self.assertNotIn('neck_in',item)

    def test_nonfinite_geometry_and_pathological_density_do_not_create_candidates(self):
        words=plan(callout()+[(float('nan'),100,142,110,'10x6SAR')])
        self.assertEqual(len(sized_registers(words,1,'plan.pdf')),1)
        dense=callout()+[(100+i*.1,105,110+i*.1,115,'noise'+str(i)) for i in range(150)]
        self.assertEqual(sized_registers(plan(dense),1,'plan.pdf'),[])

    def test_maximum_input_of_valid_size_tokens_is_bounded_before_neighbor_expansion(self):
        # Distinct valid dimensions all occupy one cell. Every token reaches
        # the size-label lookup; none can be removed by token dedup or the
        # 30,000-word input cap. Expanding that cell per token is quadratic.
        crowded=[(100,100,122,110,f'12.{i:05}x8') for i in range(29998)]
        crowded.extend([(124,100,142,110,'SAR'),(103,112,140,122,'240CFM')])
        self.assertEqual(len(crowded),30000)
        self.assertEqual(sized_registers(crowded,1,'plan.pdf',plan_confirmed=True),[])

    def test_combined_label_cannot_bypass_dense_neighborhood_guard(self):
        crowded=callout(joined=True)+[(100,100,122,110,f'{i}CFM') for i in range(1,150)]
        self.assertEqual(sized_registers(crowded,1,'plan.pdf',plan_confirmed=True),[])


if __name__=='__main__':unittest.main()
