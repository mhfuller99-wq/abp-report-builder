import unittest

import pymupdf

from abp_grille_service import grille_hints
from abp_symbol_examples import symbol_examples, is_symbol_example


class GrilleServiceTests(unittest.TestCase):
    def setUp(self):
        self.doc = pymupdf.open()
        self.addCleanup(self.doc.close)
        self.page = self.doc.new_page(width=500, height=400)
        self.words = []
        def word(x, y, value, block, line=0, index=0):
            w = (x,y,x+6,y+10,value,block,line,index)
            self.words.append(w)
            return w
        for i, value in enumerate('HVAC SYMBOL LEGEND'.split()):
            word(50+20*i,35,value,1,0,i)
        prose = 'TYPE F, EXHAUST GRILLE, BALANCE TO CFM INDICATED, SEE EQUIPMENT SCHEDULE, OTHERS SIMILAR.'
        for i, value in enumerate(prose.split()):
            word(100+i%6*20,80+i//6*10,value,2,i//6,i%6)
        word(65,86,'F',2,5)
        word(65,101,'190',2,6)
        word(65,175,'F',3)
        self.examples=[('F',150,(60,170,85,205))]
        self.candidates=[]
        for index, x in enumerate([190, 235, 285, 335, 385]):
            mark='G' if index==0 else 'F'
            word(x,90,mark,4+index)
            self.candidates.append({'type':mark,'include':False,'position':[x,90],'design_cfm':90,
                                    'size':'8','neck_in':8,'evidence':'centered type-over-airflow'})
        # Legend sample and first candidate have closed boxes. The next has
        # a diamond, an open box, an extended grid line and then text only.
        for x,y in [(65,86),(190,90)]:
            self.page.draw_rect((x-2,y-1,x+8,y+11),width=.45)
        self.diamond(65,175)
        self.diamond(235,90)
        self.page.draw_polyline([(283,89),(293,89),(293,101),(283,101)],width=.45)
        self.page.draw_rect((333,89,343,101),width=.45)
        self.page.draw_line((330,89),(347,89),width=.45)

    def diamond(self,x,y):
        self.page.draw_polyline([(x+3,y-4),(x+12,y+5),(x+3,y+14),(x-6,y+5),(x+3,y-4)],width=.45)

    def test_closed_box_with_page_legend_only(self):
        grille_hints(self.page,self.words,self.candidates,self.examples)
        self.assertEqual([c['type'] for c in self.candidates if c.get('service_hint')],['G'])
        self.assertEqual(self.candidates[0]['size'],'')
        self.assertNotIn('neck_in',self.candidates[0])
        self.assertTrue(all(c['include'] is False for c in self.candidates))
        self.assertEqual(self.candidates[1]['size'],'8')

    def test_missing_or_ambiguous_legend(self):
        for words,examples in [(self.words,[]), (self.words,self.examples*2),
                               ([w for w in self.words if w[4]!='EXHAUST'],self.examples),
                               (self.words+[(*w[:5],20,*w[6:]) for w in self.words if w[5]==2],self.examples)]:
            grille_hints(self.page,words,self.candidates,examples)
            self.assertFalse(any(c.get('service_hint') for c in self.candidates))

    def test_matching_box_for_the_supply_example_withholds_hint(self):
        self.page.draw_rect((63,174,73,186),width=.45)
        grille_hints(self.page,self.words,self.candidates,self.examples)
        self.assertFalse(any(c.get('service_hint') for c in self.candidates))

    def test_exhaust_sample_is_not_an_image_or_native_outlet(self):
        words=list(self.words)
        words.append((64,190,73,200,'150',10,0,0))
        for i,value in enumerate('TYPE "F" CEILING DIFFUSER. BALANCE TO 150 CFM.'.split()):
            words.append((100+i*15,175,110+i*15,185,value,11,0,i))
        examples=symbol_examples(words)
        self.assertTrue(is_symbol_example({'type':'F','position':[65,86],
                                          'review_values':{'design_cfm':190}},examples))
        self.assertFalse(is_symbol_example({'type':'F','position':[190,90],
                                           'design_cfm':190},examples))
