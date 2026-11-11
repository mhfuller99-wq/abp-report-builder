"""Invented CAD geometries; no customer documents or project values."""
import unittest
import pymupdf
from abp_outlets import plan_context, necked_outlets, centered_outlets
from abp_mechanical import keyed_outlets, schedule_candidates, joined_schedule_tags
from abp_schedule import parse_pdf
from abp_ocr import diffuser_candidates

def w(x,y,text,width=None):return (x,y,x+(width or len(text)*5),y+11,text,0,0,0)
def outlet(x=100,flow='325',mark='CSD7'):
    return [w(x,100,mark,24),w(x+2,110,'9"Ø',20),w(x+4,121,flow,16)]
def schedule():
    return [w(10,60,'MARK'),w(150,45,'SUPPLY'),w(150,60,'CFM'),w(250,60,'ESP'),
            w(10,85,'AHU'),w(28,85,'-'),w(36,85,'7'),w(150,85,'875'),w(250,85,'0.45')]

class CadCallouts(unittest.TestCase):
    def test_titles_not_references_to_other_sheets(self):
        for title in ['H.V.A.C. FLOOR PLAN 1','HVAC PLAN','2nd Floor Plan - Mechanical','MECHANICAL CEILING PLAN']:
            self.assertTrue(plan_context([w(10,10,title)]),title)
        for title in ['SEE HVAC FLOOR PLAN FOR INFORMATION','MECHANICAL PLANS WITH THEIR QUOTE REQUEST',
                      'COORDINATE WITH MECHANICAL FLOOR PLAN','H.V.A.C. ROOF PLAN','AIR HANDLING UNIT SCHEDULE']:
            self.assertFalse(plan_context([w(10,10,title)]),title)

    def test_three_lines_require_unique_neck_and_flow(self):
        words=[w(10,10,'H.V.A.C. FLOOR PLAN')]+outlet()+outlet(300,'225','CSD8')
        found=necked_outlets(words,1,'synthetic.pdf')
        self.assertEqual([(o['type'],o['neck_in'],o['design_cfm']) for o in found],[('CSD7',9,325),('CSD8',9,225)])
        self.assertTrue(all(not o['include'] and o['system']==o['location']=='' for o in found))
        self.assertEqual(necked_outlets(words+[w(104,122,'425',16)],1,'synthetic.pdf')[0]['design_cfm'],225)
        self.assertEqual(necked_outlets([words[0]]+outlet()[::2],1,'synthetic.pdf'),[])

    def test_equipment_bubbles_and_return_marks_are_not_supply(self):
        for mark in ['SF','EF','RF','AHU','CRG']:
            words=[w(10,10,'HVAC PLAN')]+outlet(mark=mark)
            self.assertEqual(necked_outlets(words,1,'synthetic.pdf'),[])
        words=[w(10,10,'HVAC PLAN'),w(100,100,'SF'),w(101,111,'1')]
        self.assertEqual(keyed_outlets(words,1,'synthetic.pdf',{}),[])
        self.assertEqual(centered_outlets(words,1,'synthetic.pdf'),[])
        words[1]=w(100,100,'SB')
        self.assertEqual(keyed_outlets(words,1,'synthetic.pdf',{}),[])

    def test_title_required_even_when_legend_matches(self):
        words=[w(10,10,'SEE HVAC PLAN FOR INFORMATION'),w(100,100,'SB'),w(101,111,'125')]
        self.assertEqual(keyed_outlets(words,1,'synthetic.pdf',{'SB':'8"Ø'}),[])

    def test_horizontal_tag_parts_need_explicit_dash_and_id_column(self):
        found=schedule_candidates(schedule(),1,'synthetic.pdf')
        self.assertEqual(found[0]['tag'],'AHU-7')
        self.assertEqual(found[0]['values']['design_cfm'],875)
        self.assertEqual(found[0]['values']['esp'],.45)
        for words in [[w for w in schedule() if w[4]!='-'],[w for w in schedule() if w[4]!='MARK']]:
            self.assertEqual(schedule_candidates(words,1,'synthetic.pdf'),[])
        words=schedule();words[5]=w(80,85,'-')
        self.assertEqual(schedule_candidates(words,1,'synthetic.pdf'),[])
        self.assertEqual(schedule_candidates(schedule()+[w(90,50,'ACTUAL')],1,'synthetic.pdf'),[])

    def test_round_neck_is_also_checked_for_ocr_confidence(self):
        words=[{'box':list(t[:4]),'text':t[4],'confidence':96} for t in [w(10,10,'HVAC PLAN')]+outlet()]
        found=diffuser_candidates(words,'synthetic.pdf',1)
        self.assertEqual(found[0]['review_values']['design_cfm'],325)
        self.assertFalse(found[0]['include'])
        words[2]['confidence']=10
        self.assertEqual(diffuser_candidates(words,'synthetic.pdf',1)[0]['review_values'],{})

    def test_grouped_supply_heading_and_oa_subcolumn_do_not_swap(self):
        words=[w(10,70,'MARK'),w(160,40,'SUPPLY'),w(194,40,'FAN'),
               w(150,70,'CFM'),w(190,55,'ESP'),w(230,70,'HP'),w(350,55,'O/A'),w(350,70,'CFM'),
               w(10,100,'AHU-7'),w(150,100,'875'),w(190,100,'0.45'),w(230,100,'1'),w(350,100,'135')]
        values=schedule_candidates(words,1,'synthetic.pdf')[0]['values']
        self.assertEqual(values['design_cfm'],875)
        self.assertEqual(values['osa_cfm'],135)
        self.assertEqual(values['esp'],.45)

    def test_fan_static_pressure_units_required(self):
        words=[w(10,70,'MARK'),w(150,70,'CFM'),w(250,55,'S.P.'),w(272,55,'IN'),w(250,70,'INCHES'),
               w(10,100,'EF-7'),w(150,100,'135'),w(250,100,'0.35')]
        self.assertEqual(schedule_candidates(words,1,'synthetic.pdf')[0]['values']['esp'],.35)
        words=[w for w in words if w[4]!='INCHES']
        self.assertNotIn('esp',schedule_candidates(words,1,'synthetic.pdf')[0]['values'])

    def test_pdf_integration_reads_three_line_callout(self):
        d=pymupdf.open();p=d.new_page()
        p.insert_text((20,30),'H.V.A.C. FLOOR PLAN',fontsize=12)
        for text,y in [('CSD7',100),('9"',112),('325',124)]:
            # Use a rectangular neck to avoid a substitute font for the diameter glyph.
            text='9x7' if y==112 else text
            width=pymupdf.get_text_length(text,fontsize=10)
            p.insert_text((200-width/2,y),text,fontsize=10)
        _,_,found=parse_pdf('synthetic.pdf',d.tobytes())
        self.assertEqual([(o['type'],o['size'],o['design_cfm']) for o in found],[('CSD7','9x7',325)])
        d.close()

if __name__=='__main__':unittest.main()
