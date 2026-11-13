"""Native-header / outlined-row schedule regressions, using synthetic data."""
import unittest
from unittest.mock import patch
import pymupdf
from abp_mechanical import schedule_candidates
from abp_ocr import equipment_candidates,word,extract_local
from abp_outline_tables import read,split_flow_cells


def furnace():
    def w(x,y,text,width=None):return (x,y,x+(width or len(text)*4),y+8,text)
    header=[w(10,90,'MARK'),w(50,90,'TYPE'),w(90,90,'TOTAL'),
            w(133,90,'E.S.P.'),w(159,90,'(IN)'),w(178,90,'O.A.'),w(197,90,'CFM'),
            w(222,90,'INPUT'),w(245,90,'(M.B.H.)'),w(280,90,'OUTPUT'),w(308,90,'(M.B.H.)'),
            w(350,90,'MCA'),w(400,90,'MARK'),w(440,90,'TOTAL'),w(465,90,'(MBH)'),
            w(80,74,'NATURAL'),w(113,74,'GAS'),w(129,74,'FURNACE'),w(400,74,'EVAP.'),w(424,74,'COIL')]
    row=[w(10,110,'AHU-7'),w(50,110,'UPFLOW'),w(94,110,'1,250'),w(147,110,'0.6'),
         w(188,110,'125'),w(243,110,'90.0'),w(304,110,'86.0'),w(350,110,'14.2'),
         w(400,110,'CC-7'),w(451,110,'36.0')]
    return header+row


class FurnaceTests(unittest.TestCase):
    def test_pressure_parentheses_cannot_consume_neighboring_capacity_heading(self):
        item=schedule_candidates(furnace(),1,'synthetic')[0]
        self.assertEqual(item['values']['esp'],.6)
        self.assertNotEqual(item['values']['esp'],125)
        self.assertFalse(any(w[4] in ('INPUT','OUTPUT','O.A.') for w in item['value_words']['esp']))

    def test_outside_air_total_capacity_and_mca_have_separate_meanings(self):
        found=schedule_candidates(furnace(),1,'synthetic')
        self.assertEqual([i['tag'] for i in found],['AHU-7'])
        values=found[0]['values']
        self.assertEqual(values['design_cfm'],1250)
        self.assertEqual(values['osa_cfm'],125)
        self.assertEqual(values['heating_input_btu'],90000)
        self.assertEqual(values['heating_output_btu'],86000)
        self.assertEqual(values['unit_mca'],14.2)
        self.assertNotIn('motor_fla',values)
        self.assertNotIn('cooling_total_btu',values)

    def test_total_without_full_furnace_context_is_not_assumed_cfm(self):
        for removed in ('FURNACE','TYPE','E.S.P.','O.A.'):
            items=schedule_candidates([w for w in furnace() if w[4]!=removed],1,'synthetic')
            self.assertNotEqual(items[0]['values'].get('design_cfm'),1250)

    def test_split_ocr_digits_are_not_concatenated_into_a_capacity(self):
        words=[w for w in furnace() if w[4]!='1,250']
        words.extend([(94,110,98,118,'1'),(102,110,114,118,'250')])
        self.assertNotIn('design_cfm',schedule_candidates(words,1,'synthetic')[0]['values'])

    def test_fragment_detection_requests_reread_without_creating_a_value(self):
        words=[word(*w,confidence=96) for w in furnace() if w[4]!='1,250']
        words.extend([word(94,110,98,118,'1',95),word(102,110,114,118,'250',95),
                      word(520,90,540,98,'MARK',100)])
        found=split_flow_cells(words)
        self.assertEqual([[w['text'] for w in parts] for parts in found],[['1','250']])
        self.assertFalse(any(w['text']=='1250' for w in words))
        next(w for w in words if w['text']=='250')['confidence']=50
        self.assertEqual([[w['text'] for w in parts] for parts in split_flow_cells(words)],[['1','250']])
        self.assertNotIn('design_cfm',equipment_candidates(words+[word(10,40,150,48,'SCHEDULE',100)],'synthetic.pdf',1,'ocr')[0]['review_values'])

    def test_image_field_needs_tag_value_and_context_confidence(self):
        words=[word(*w,confidence=96) for w in furnace()]
        words.append(word(10,40,150,48,'SCHEDULE',100))
        found=equipment_candidates(words,'synthetic.pdf',1,'ocr')
        self.assertEqual(found[0]['review_values']['design_cfm'],1250)
        next(w for w in words if w['text']=='FURNACE')['confidence']=40
        self.assertNotIn('design_cfm',equipment_candidates(words,'synthetic.pdf',1,'ocr')[0]['review_values'])
        next(w for w in words if w['text']=='FURNACE')['confidence']=96
        next(w for w in words if w['text']=='AHU-7')['confidence']=40
        self.assertEqual(equipment_candidates(words,'synthetic.pdf',1,'ocr')[0]['review_values'],{})

    def test_uncertain_fragments_require_a_strong_matching_literal_reread(self):
        for literal,confidence,expected in [('1,250',95,1250),('1,250',89,None),('1,251',95,None)]:
            with self.subTest(literal=literal,confidence=confidence),pymupdf.open() as doc:
                page=doc.new_page(width=600,height=800);page.insert_text((10,30),'SCHEDULE')
                words=[word(*w,confidence=96) for w in furnace() if w[4]!='1,250']
                words.extend([word(94,110,98,118,'1',50),word(102,110,114,118,'250',50),
                              word(520,90,540,98,'MARK',100),word(10,40,150,48,'SCHEDULE',100)])
                calls=[]
                def engine(page,pixels,timeout,**kwargs):
                    calls.append(kwargs['psm'])
                    return [word(94,110,114,118,literal,confidence)]
                with patch('abp_outline_tables.read',return_value=words):
                    result=extract_local(doc.tobytes(),region_engine=engine,
                        selector=lambda *a,**k:([[0,0,590,200]],1,False),retain_words=False)
                record=next(c for c in result['review_candidates'] if c['tag']=='AHU-7')
                self.assertIn(7,calls)
                self.assertEqual(record['review_values'].get('design_cfm'),expected)
                self.assertFalse(record['include']);self.assertEqual(record['values'],{})


class OutlineTableTests(unittest.TestCase):
    def test_unknown_and_measurement_tables_do_not_use_isolation(self):
        with pymupdf.open() as doc:
            page=doc.new_page()
            self.assertIsNone(read(page,[0,0,300,300],[],100000,1,None))
            native=[word(5,5,300,15,'EXHAUST FAN SCHEDULE ID E.S.P. CFM')]
            native.append(word(5,20,50,30,'ACTUAL'))
            self.assertIsNone(read(page,[0,0,400,400],native,100000,1,None))

    def test_cad_table_maps_ocr_back_to_source_without_mutation(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            native=[word(110,210,450,220,'EXHAUST FAN SCHEDULE ID E.S.P. CFM')]
            for i in range(25):
                shape=page.new_shape();shape.draw_line((110+i*7,250),(113+i*7,257))
                shape.finish(width=1);shape.commit()
            before=doc.tobytes(no_new_id=True);calls=[]
            def engine(page,pixels,timeout,**kwargs):
                calls.append((pixels,timeout,kwargs))
                return [word(20,60,30,68,'85',95)]
            found=read(page,[100,200,500,300],native,100000,2,engine)
            self.assertEqual(found[0]['box'],[110,250,120,258])
            self.assertEqual(found[1]['confidence'],100)
            self.assertEqual(calls[0][0],100000)
            self.assertLessEqual(calls[0][1],2)
            self.assertEqual(doc.tobytes(no_new_id=True),before)


if __name__ == '__main__':unittest.main()
