"""Synthetic source and report regressions. No customer documents or values."""
import io,unittest
from unittest.mock import patch
import pymupdf
from openpyxl import load_workbook
import abp_server as app
from abp_design import inferred_form
from abp_mechanical import schedule_candidates
from abp_ocr import circle_outlet,word,equipment_candidates,extract_local,Budget
from abp_ocr_regions import circle_regions,complete_raster_tables
from abp_presentation import header_text
from test_mechanical import word as native_word


class SourceReviewTests(unittest.TestCase):
    def test_literal_cd_cfm_callouts_keep_repeated_outlets_and_omit_ambiguous_pairs(self):
        from abp_outlets import coded_outlets
        from abp_ocr import diffuser_candidates
        pairs=[(10,20,40,28,'914CD'),(10,30,45,38,'310CFM'),
               (100,20,130,28,'914CD'),(100,30,135,38,'310CFM')]
        found=coded_outlets(pairs,1,'synthetic.pdf',plan_confirmed=True)
        self.assertEqual(len(found),2);self.assertEqual(sum(c['design_cfm'] for c in found),620)
        self.assertTrue(all(not c['include'] and not c['size'] and not c['system'] for c in found))
        self.assertEqual(coded_outlets(pairs,1,'notes.pdf'),[])
        ambiguous=pairs[:2]+[(10,32,45,40,'320CFM')]
        self.assertEqual(coded_outlets(ambiguous,1,'x',plan_confirmed=True),[])
        self.assertEqual(coded_outlets([(10,20,40,28,'914RAG'),pairs[1]],1,'x',plan_confirmed=True),[])
        words=[word(*p,confidence=95) for p in pairs]
        self.assertEqual(len(diffuser_candidates(words,'x',1,plan_confirmed=True)),2)
        words[1]['confidence']=45
        self.assertEqual(diffuser_candidates(words,'x',1,plan_confirmed=True)[0]['review_values'],{})

    def test_decorative_circles_cannot_consume_the_plan_tile_allowance(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=600,height=800);p.insert_text((20,30),'HVAC PLAN')
            for i in range(24):p.draw_circle((30+(i%6)*60,80+(i//6)*60),9)
            calls=[]
            def engine(*args,psm,**kwargs):calls.append(psm);return []
            result=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            self.assertEqual(calls.count(11),6)
            self.assertLessEqual(result['ocr_regions_attempted'],Budget().max_regions_per_page)
            self.assertFalse(result['complete_takeoff'])

    def test_uncertain_tag_reread_requires_exact_repeat_and_budget(self):
        from test_mechanical import fan_words
        from test_targeted_ocr import ruled_pdf
        for repeat,budget,expected in [('EF-1',4,75),('EF-9',4,None),('EF-1',1,None)]:
            def engine(*args,psm,**kwargs):
                if psm==7:return [word(10,100,30,110,repeat,96)]
                words=[word(*w[:5],confidence=95) for w in fan_words()]+[word(0,0,90,9,'FAN SCHEDULE',95)]
                next(w for w in words if w['text']=='EF-1')['confidence']=50
                return words
            with ruled_pdf() as doc:
                result=extract_local(doc.tobytes(),region_engine=engine,budget=Budget(max_regions_per_page=budget),retain_words=False)
            found=next(c for c in result['review_candidates'] if c['tag']=='EF-1')
            self.assertEqual(found['review_values'].get('design_cfm'),expected)
            self.assertEqual(found['values'],{});self.assertFalse(found['include'])
            self.assertLessEqual(result['ocr_regions_attempted'],budget)
            if budget==1:self.assertTrue(any(r['status']=='budget_skipped' for r in result['coverage'][0]['regions']))

    def test_circle_review_crop_contains_type_and_airflow(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=600,height=800);p.insert_text((20,30),'MECHANICAL FLOOR PLAN')
            p.draw_circle((200,200),9)
            def engine(*args,psm,clip,**kwargs):
                if psm in (10,7):return [word(*clip,'A' if psm==10 else '275',96)]
                return []
            result=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            c=next(c for c in result['review_candidates'] if c['kind']=='diffuser')
            self.assertLessEqual(c['region'][1],191);self.assertGreater(c['region'][3],220)
            self.assertFalse(result['complete_takeoff']);self.assertFalse(c['include'])
            with patch('abp_ocr.circle_regions',side_effect=RuntimeError('synthetic geometry failure')):
                failed=extract_local(doc.tobytes(),region_engine=engine,retain_words=False)
            self.assertEqual(failed['coverage'][0]['circle_selection_failed'],'RuntimeError')
            self.assertTrue(failed['coverage'][0]['circle_selection_truncated'])

    def test_indoor_ms_schedule_keeps_outdoor_unit_separate(self):
        words=[native_word(10,70,'MARK'),native_word(180,70,'SUPPLY'),native_word(208,70,'CFM'),
               native_word(10,100,'MS-4'),native_word(192,100,'325')]
        found=schedule_candidates(words,1,'synthetic.pdf')
        self.assertEqual(found[0]['values']['design_cfm'],325)
        self.assertEqual(inferred_form('MS-4'),'Fan Coil Units DX.xlsx')
        self.assertIsNone(inferred_form('MSHP-4'))
        self.assertEqual(schedule_candidates([native_word(10,10,'MS'),native_word(35,10,'38801')],1,'address'),[])

    def test_reference_to_served_unit_does_not_create_an_equipment_row(self):
        words=[word(0,0,150,10,'HUMIDIFIER SCHEDULE',95),word(0,30,30,40,'MARK',95),
               word(80,30,120,40,'SERVES',95),word(0,60,20,70,'H-4',95),word(80,60,115,70,'AHU-4',95)]
        self.assertEqual(equipment_candidates(words,'synthetic.pdf',1,'ocr'),[])

    def test_circle_candidates_require_real_flow_and_stay_unverified(self):
        letter=[word(12,12,18,20,'A',96)];flow=[word(5,31,25,40,'275',95)]
        c=circle_outlet(letter,flow,'synthetic.pdf',2,[10,10,30,30])
        self.assertEqual(c['review_values'],{'design_cfm':275});self.assertEqual(c['values'],{})
        self.assertFalse(c['include']);self.assertEqual(c['status'],'UNVERIFIED')
        for raw,confidence in [('i275',95),('275',60)]:
            self.assertEqual(circle_outlet(letter,[word(5,31,25,40,raw,confidence)],'x',1,[10,10,30,30])['review_values'],{})
        self.assertIsNone(circle_outlet(letter,[word(5,31,25,40,'RETURN',95)],'x',1,[10,10,30,30]))
        letter[0]['confidence']=50
        self.assertIsNone(circle_outlet(letter,flow,'x',1,[10,10,30,30]))

    def test_circle_geometry_is_rotation_aware_and_bounded(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=300,height=400)
            p.draw_circle((60,80),9);p.draw_circle((120,80),9)
            before=doc.tobytes();p.set_rotation(90)
            boxes,truncated=circle_regions(p,max_regions=1)
            self.assertTrue(truncated);self.assertEqual(len(boxes),1)
            self.assertAlmostEqual(boxes[0][0],311,places=2)
            p.set_rotation(0)
            self.assertEqual(len(p.get_cdrawings()),2)

    def test_embedded_table_restores_rows_but_not_whole_page_image(self):
        boxes=[[98,80,502,155]];rect=pymupdf.Rect(0,0,1000,1000)
        parent={'box':[100,100,500,280],'status':'raster_unexamined'}
        self.assertGreaterEqual(complete_raster_tables(boxes,[parent],rect)[0][3],280)
        full={'box':[0,0,1000,1000],'status':'raster_unexamined'}
        self.assertEqual(complete_raster_tables(boxes,[full],rect),boxes)


class ReportPresentationTests(unittest.TestCase):
    def test_compact_multi_system_totals_and_original_formulas(self):
        outlets=[{'system':'ahu-4','location':'exam room','type':'a','size':'8','design_cfm':275} for _ in range(4)]
        outlets += [{'system':'ahu-5','location':'lobby','type':'b','size':'6','design_cfm':125}]
        with patch.object(app,'BLANK_RECT_FORMS',1),patch.object(app,'BLANK_RND_FORMS',1):
            result=app.build({'project':'Example clinic','location':'Example, MS','templates':['Supply Diffusers.xlsx'], 'diffusers':outlets})
        w=load_workbook(io.BytesIO(result));s=w['SUPPLY DIFFUSERS']
        self.assertEqual(s['A6'].value,'EXAM ROOM');self.assertEqual(s['D6'].value,'A')
        self.assertEqual([r for r in range(6,28) if not s.row_dimensions[r].hidden],[6,7,8,9,27])
        self.assertEqual([r for r in range(48,70) if not s.row_dimensions[r].hidden],[48,69])
        self.assertEqual(s['G27'].value,'=SUM(G6:G26)');self.assertEqual(s['G69'].value,'=SUM(G48:G68)')
        self.assertEqual(s['I10'].value,'=IF(H10=0,"",H10/G10)')
        self.assertIn('PROJECT: EXAMPLE CLINIC',s.oddHeader.left.text)
        self.assertIn('LOCATION: EXAMPLE, MS',s.oddHeader.left.text)
        self.assertIsNone(s['A36'].value)
        self.assertTrue(all(s.cell(r,c).value is None for r in range(6,27) for c in (6,8)))

    def test_header_controls_survive_and_user_ampersands_are_escaped(self):
        value='&L&"Calibri,Bold"PROJECT:_x000a_LOCATION:_x000a_&G&R&G'
        result=header_text(value,'A & B','Example')
        self.assertIn('&"Calibri,Bold"',result);self.assertIn('A && B',result)
        self.assertIn('_x000a_',result);self.assertTrue(result.endswith('&G&R&G'))


if __name__=='__main__':unittest.main()
