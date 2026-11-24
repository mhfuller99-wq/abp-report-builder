"""Synthetic layouts, independent of the private source answers."""
import unittest
from abp_schedule import parse_page
from abp_transposed import candidates
from abp_ocr import equipment_candidates
from abp_design import inferred_form


def word(x,y,text):
    return (x,y,x+len(text)*4,y+8,text)


def fixture():
    data=[word(10,10,'FURNACE'),word(42,10,'SCHEDULE:'),word(10,25,'TAG'),
          word(180,25,'F-7'),word(280,25,'F-8')]
    for y,label,a,b in [(40,'CFM','910','1330'),(55,'OUTSIDE AIR CFM','85','110'),
                        (70,'HEAT INPUT (MBH)','45','75'),(85,'MCA','12','16'),
                        (100,'MOCP','20','25'),(115,'MODEL NUMBER','SAMPLE-A','SAMPLE-B')]:
        x=10
        for token in label.split():
            data.append(word(x,y,token));x+=len(token)*4+4
        data += [word(180,y,a),word(280,y,b)]
    return data


class TransposedTests(unittest.TestCase):
    def test_column_identity_units_and_provenance(self):
        found=candidates(fixture(),4,'synthetic.pdf')
        self.assertEqual([x['tag'] for x in found],['F-7','F-8'])
        self.assertEqual(found[0]['values'],{'design_cfm':910,'osa_cfm':85,'heating_input_btu':45000,'unit_mca':12,'unit_mop':20})
        self.assertEqual(found[1]['values']['design_cfm'],1330)
        self.assertEqual(found[0]['text']['model'],'SAMPLE-A')
        self.assertEqual(found[0]['field_evidence']['osa_cfm']['printed_label'],'OUTSIDE AIR CFM')
        self.assertNotIn('motor_fla',found[0]['values'])
        self.assertEqual(len(parse_page(fixture(),4,'synthetic.pdf')),2)
        self.assertEqual(inferred_form('F-7',{'text_proposed':found[0]['text']}),'Air Moving Equipment.xlsx')
        self.assertIsNone(inferred_form('F-7'))

    def test_identity_is_schedule_local(self):
        self.assertEqual(candidates(fixture()[2:],1,'missing-title'),[])
        changed=[(*w[:4],w[4].replace('FURNACE','EQUIPMENT')) for w in fixture()]
        self.assertEqual(candidates(changed,1,'unrelated-table'),[])
        self.assertEqual(parse_page([word(10,10,'F-7'),word(40,10,'910')],1,'grid-reference'),[])
        self.assertEqual(candidates([word(-10,10,'SEE')]+fixture(),1,'prose-reference'),[])

    def test_neighboring_table_and_duplicate_fields(self):
        second=[(w[0]+400,w[1],w[2]+400,w[3],w[4].replace('F-7','F-9').replace('F-8','F-10').replace('910','650')) for w in fixture()]
        found=candidates(fixture()+second,1,'adjacent')
        self.assertEqual([(r['tag'],r['values']['design_cfm']) for r in found],[('F-7',910),('F-8',1330),('F-9',650),('F-10',1330)])
        changed=fixture()+[word(10,130,'CFM'),word(180,130,'900'),word(280,130,'1400')]
        self.assertTrue(all('design_cfm' not in x['values'] for x in candidates(changed,1,'conflict')))

    def test_ocr_identity_label_and_value_are_all_required(self):
        def ocr(change=None):
            return [{'box':list(w[:4]),'text':w[4],'confidence':50 if change and change(w) else 96} for w in fixture()]
        found=equipment_candidates(ocr(), 'image',1,'ocr')
        self.assertEqual(found[0]['review_values']['design_cfm'],910)
        self.assertEqual(found[0]['review_text']['unit_type'],'FURNACE')
        self.assertFalse(found[0]['include']);self.assertEqual(found[0]['values'],{})
        found=equipment_candidates(ocr(lambda w:w[4]=='910'), 'image',1,'ocr')
        self.assertNotIn('design_cfm',found[0]['review_values'])
        self.assertEqual(found[0]['review_values']['osa_cfm'],85)
        self.assertNotIn('design_cfm',found[0]['field_evidence'])
        found=equipment_candidates(ocr(lambda w:w[4]=='F-7'), 'image',1,'ocr')
        self.assertEqual([r['tag'] for r in found],['F-8'])
        self.assertEqual(equipment_candidates(ocr(lambda w:w[4]=='FURNACE'), 'image',1,'ocr'),[])

    def test_no_unlabeled_airflow_or_measurements(self):
        changed=[(*w[:4],'AIRFLOW' if w[4]=='CFM' and w[1]==40 else w[4]) for w in fixture()]
        self.assertTrue(all('design_cfm' not in r['values'] for r in candidates(changed,1,'no-unit')))
        measured=fixture()+[word(10,30,'ACTUAL')]
        self.assertEqual(candidates(measured,1,'measurements'),[])


if __name__=='__main__':unittest.main()
