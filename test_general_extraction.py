"""Public synthetic regressions for general schedules and source semantics."""
import unittest
import pymupdf
from abp_mechanical import schedule_candidates, expand_marks, diffuser_legend, keyed_outlets, page_words
from abp_schedule import parse_doas_submittal, parse_fan_submittal, parse_page, resolve_proposed
from abp_server import read_sources
from abp_design import inferred_form


def word(x,y,text):
    return (x,y,x+len(text)*4,y+9,text,0,0,0)


def schedule(tag,flow=650):
    return [word(10,10,'INDOOR UNIT SCHEDULE'),word(10,70,'MARK'),
            word(220,70,'TOTAL'),word(244,70,'CFM'),word(330,70,'ESP'),
            word(430,70,'MOTOR'),word(454,70,'HP'),word(10,90,tag),
            word(228,90,str(flow)),word(330,90,'0.5'),word(442,90,'0.25')]


def selection_doc(pages):
    doc=pymupdf.open()
    for lines in pages:
        page=doc.new_page(width=900,height=1100)
        for i,line in enumerate(lines):page.insert_text((30,40+20*i),line,fontsize=10)
    return doc


class GeneralExtractionTests(unittest.TestCase):
    def test_explicit_service_selects_small_fan_without_inventing_hp(self):
        record={'proposed':{'design_cfm':350},'text_proposed':{'service':'CEILING'}}
        self.assertEqual(inferred_form('EF-3',record),'Exhaust Fans _Sm._.xlsx')
        self.assertNotIn('motor_hp',record['proposed'])
        self.assertEqual(inferred_form('DOAS-1',{'candidates':[{'text':{'unit_type':'DOAS / INDIRECT GAS'}}]}),
                         'Fan Coil Units DX GAS.xlsx')

    def test_pdf_scan_keeps_exact_tags_and_unverified_conflicts(self):
        with pymupdf.open() as doc:
            for tag,flow in [('IU-1.01',650),('DSS-2.1',750),('DOAS-4.2',1000)]:
                page=doc.new_page(width=900,height=1100)
                for x,y,text in [(20,40,'MECHANICAL EQUIPMENT SCHEDULE'),(20,90,'MARK'),
                                 (230,90,'TOTAL CFM'),(340,90,'ESP'),(20,120,tag),
                                 (235,120,str(flow)),(340,120,'0.5')]:
                    page.insert_text((x,y),text,fontsize=8)
            page=doc.new_page()
            page.insert_text((20,40),'Unit Mark: DOAS-4.2',fontsize=9)
            page.insert_text((20,60),'Supply Air: 1100 CFM',fontsize=9)
            scan=read_sources([('synthetic.pdf',doc.tobytes())])
        by={r['tag']:r for r in scan['records']}
        self.assertEqual(set(by),{'IU-1.01','DSS-2.1','DOAS-4.2'})
        self.assertEqual(by['IU-1.01']['proposed']['design_cfm'],650)
        self.assertEqual(by['DSS-2.1']['proposed']['design_cfm'],750)
        self.assertNotIn('design_cfm',by['DOAS-4.2']['proposed'])
        self.assertTrue(all(r['status']=='UNVERIFIED' and r['design_cfm'] is None for r in by.values()))

    def test_peak_airflow_is_selection_evidence_not_plan_design(self):
        words=[word(10,70,'TAG'),word(210,60,'Peak'),word(230,60,'Fan'),word(246,60,'Airflow'),
               word(10,90,'IU-2.01'),word(254,90,'1485')]
        c=schedule_candidates(words,1,'selection.pdf')[0]
        self.assertEqual(c['values'],{'selected_cfm':1485})
        self.assertEqual(c['basis'],'SUBMITTAL_SELECTION')

    def test_stacked_mark_requires_explicit_tag_column(self):
        words=[word(10,70,'TAG'),word(220,70,'CFM'),word(10,90,'EF'),
               word(12,104,'2'),word(220,98,'50')]
        c=schedule_candidates(words,1,'a')
        self.assertEqual([(x['tag'],x['values']) for x in c],[('EF-2',{'design_cfm':50})])
        self.assertEqual(schedule_candidates(words[1:],1,'a'),[])

    def test_vendor_neutral_vertical_selection_table(self):
        with pymupdf.open() as doc:
            page=doc.new_page()
            for x,y,text in [(20,30,'Mark: DOAS-8'),(100,100,'Supply'),(100,112,'(CFM)'),
                             (100,126,'2,000'),(200,100,'Outdoor Air'),(210,112,'(CFM)'),(210,126,'2,000')]:
                page.insert_text((x,y),text,fontsize=8)
            c=parse_doas_submittal(doc,'selection.pdf')
        self.assertEqual(c[0]['tag'],'DOAS-8')
        self.assertEqual(c[0]['values']['design_cfm'],2000)

    def test_decimal_identifiers_and_vendor_neutral_schedule(self):
        for tag in ['IU-1.01','IU-1.02','DSS-2.1','DSS-2.11A','DOAS-4.2']:
            with self.subTest(tag=tag):
                c=schedule_candidates(schedule(tag),2,'synthetic.pdf')
                self.assertEqual([x['tag'] for x in c],[tag])
                self.assertEqual(c[0]['values']['design_cfm'],650)
                self.assertEqual(c[0]['reference'],'page 2')

    def test_reordered_header_columns(self):
        a=schedule('IU-1.01');b=[]
        for w in a:
            d=110 if 220<=w[0]<280 else -110 if 320<=w[0]<370 else 0
            b.append((w[0]+d,w[1],w[2]+d,*w[3:]))
        self.assertEqual(schedule_candidates(a,1,'a')[0]['values'],schedule_candidates(b,1,'b')[0]['values'])

    def test_fan_lists_and_ranges(self):
        for value,expected in [('EF-1,3,5',[1,3,5]),('EF-2,6-8,10-14',[2,6,7,8,10,11,12,13,14]),('EF-4 & 5',[4,5]),('EF-1 THRU EF-3',[1,2,3])]:
            self.assertEqual(expand_marks(value),['EF-'+str(n) for n in expected])
        for value in ['EF-3-1','EF-1-300','IU-1.01-1.04','EF-1,XX-2']:
            self.assertEqual(expand_marks(value),[])
        words=schedule('EF-1');words += [word(32,90,'THRU'),word(54,90,'EF-3')]
        self.assertEqual([x['tag'] for x in schedule_candidates(words,1,'a')],['EF-1','EF-2','EF-3'])

    def test_far_rows_and_fractional_hp(self):
        a=[(w[0],w[1]+250,w[2],w[3]+250,*w[4:]) if w[1]==90 else w for w in schedule('IU-4.02')]
        self.assertEqual(schedule_candidates(a,1,'a')[0]['values']['design_cfm'],650)
        a=[word(w[0],w[1],'1/4') if w[1]==90 and w[0]==442 else w for w in schedule('EF-1')]
        self.assertEqual(schedule_candidates(a,1,'a')[0]['values']['motor_hp'],.25)

    def test_actual_readings_never_design(self):
        self.assertEqual(schedule_candidates(schedule('IU-1.01',9999)+[word(180,50,'ACTUAL')],1,'a'),[])
        result=read_sources([('synthetic.csv',b'Tag,Design CFM,Actual CFM\nIU-1.01,650,9999\nDSS-2.1,750,8888\n')])
        for row in result['records']:
            self.assertEqual(row['status'],'UNVERIFIED')
            self.assertFalse(any(v in (9999,8888) for c in row['candidates'] for v in c['values'].values()))

    def test_outdoor_air_separate_from_supply(self):
        for label in ['OA CFM','OUTDOOR AIR CFM','OUTSIDE AIR CFM']:
            words=schedule('DOAS-4.2',1250);x=540
            for token in label.split():words.append(word(x,70,token));x+=4*len(token)+4
            words.append(word((540+x-4)/2-6,90,'250'))
            c=schedule_candidates(words,1,'a')[0]['values']
            self.assertEqual((c['design_cfm'],c['osa_cfm']),(1250,250))

    def test_selection_requires_explicit_unique_mark_and_page_scope(self):
        with selection_doc([['Unit Mark: DOAS-4.2','Supply Air: 1250 CFM'],['Unit Mark: DOAS-3','Supply Air: 1400 CFM']]) as doc:
            c=parse_doas_submittal(doc,'a')
        self.assertEqual({x['tag']:x['values']['design_cfm'] for x in c},{'DOAS-4.2':1250,'DOAS-3':1400})
        self.assertTrue(all('heating_cfm' not in x['values'] for x in c))
        for lines in [['DOAS SELECTION','Supply Air: 1250 CFM'],['Coordinate with DOAS-4.2 shown elsewhere','Supply Air: 1250 CFM'],['Unit Mark: DOAS-4.2','Supply Air: 1250 CFM','Supply Air: 1500 CFM']]:
            with selection_doc([lines]) as doc:self.assertEqual(parse_doas_submittal(doc,'a'),[])

    def test_conflicts_hold_for_review(self):
        a=[{'values':{'design_cfm':1000},'basis':'PLAN_SCHEDULE'},{'values':{'design_cfm':1100},'basis':'SUBMITTAL_SELECTION'}]
        p,f,_=resolve_proposed(a)
        self.assertNotIn('design_cfm',p);self.assertTrue(f)
        a[1]['values']['design_cfm']=1000
        self.assertEqual(resolve_proposed(a)[0]['design_cfm'],1000)

    def test_fan_requested_selected_and_field_readings_separate(self):
        with selection_doc([['Mark: EF-2,6-8,10-14','Requested Volume (CFM) 50','Actual Volume (CFM) 61']]) as doc:
            c=parse_fan_submittal(doc,'a')
        self.assertEqual(len(c),9)
        for row in c:
            self.assertEqual(row['values'],{'design_cfm':50,'selected_cfm':61})
            self.assertEqual(resolve_proposed([row])[0],{'design_cfm':50})

    def test_rotated_pdf_keeps_displayed_coordinates(self):
        with selection_doc([['Unit Mark: DOAS-2']]) as doc:
            page=doc[0];page.set_rotation(90)
            words=page_words(page)
            box=pymupdf.Rect(page.get_text('words')[0][:4])*page.rotation_matrix
            self.assertEqual(tuple(box),words[0][:4])

    def test_generic_legend_and_unassigned_outlets(self):
        class Page:
            def get_text(self,mode):
                return [word(10,10,'DIFFUSER'),word(46,10,'SCHEDULE'),word(10,60,'SA'),word(100,60,'8"Ø')]
        legend=diffuser_legend([Page()]);self.assertEqual(legend,{'SA':'8"Ø'})
        plan=[word(10,10,'FLOOR'),word(34,10,'PLAN'),word(54,10,'-'),word(62,10,'HVAC'),word(200,100,'SA'),word(201,109,'125')]
        c=keyed_outlets(plan,4,'a',legend)[0]
        self.assertEqual(c['design_cfm'],125);self.assertFalse(c['include'])
        self.assertEqual((c['system'],c['location']),('',''))

    def test_legacy_parser_does_not_bypass_actual_heading(self):
        line='EF-1 PARTS GREENHECK SYN-100 9999 1200 0.50 0.10 1/4 DIRECT 10 20 10x10 NEMA 115/60/1'
        words=[];x=10
        for token in line.split():words.append(word(x,90,token));x+=4*len(token)+4
        self.assertEqual(parse_page(words,1,'a')[0]['values']['design_cfm'],9999)
        self.assertFalse(any(9999 in c['values'].values() for c in parse_page(words+[word(200,70,'ACTUAL')],1,'a')))

if __name__=='__main__':unittest.main()
