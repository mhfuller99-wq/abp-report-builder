import sys
import unittest

import pymupdf

from abp_schedule import parse_pdf
from abp_designation import designation_records
from abp_mechanical import page_words


def fixture(columns, data, title='EXHAUST FANS', sheet='MECHANICAL EQUIPMENT SCHEDULES'):
    with pymupdf.open() as doc:
        page = doc.new_page(width=850, height=400)
        page.insert_text((35, 35), sheet, fontsize=11)
        width = 100
        left = 30
        right = left + len(columns)*width
        bottom = 130 + len(data)*25
        for y in [75, 100, 130] + [155+25*i for i in range(len(data))]:
            page.draw_line((left, y), (right, y))
        for i in range(len(columns)+1):
            x = left + i*width
            page.draw_line((x, 75 if i in (0, len(columns)) else 100), (x, bottom))
        page.insert_text((left+8, 92), title, fontsize=10)
        for i, heading in enumerate(columns):
            page.insert_text((left+i*width+6, 119), heading, fontsize=8)
        for row_index, values in enumerate(data):
            for i, value in enumerate(values):
                page.insert_text((left+i*width+6, 146+25*row_index), value, fontsize=8)
        return doc.tobytes()


class DesignationTests(unittest.TestCase):
    def read(self, *args, **kwargs):
        rows, _, _ = parse_pdf('drawing.pdf', fixture(*args, **kwargs))
        return [r for r in rows if r.get('evidence','').startswith('DESIGNATION ')]

    def test_reordered_fan_fields_and_missing_cells(self):
        rows = self.read(['DESIGNATION', 'RPM', 'EXT. S.P. (IN. W.G.)','CFM'],
                         [['EF18','700','0.34','1,210'], ['EF19','800','-','870']])
        self.assertEqual([(r['tag'],r['values']) for r in rows],
                         [('EF-18',{'design_cfm':1210,'esp':0.34}), ('EF-19',{'design_cfm':870})])
        self.assertTrue(all(r['source']=='drawing.pdf' and r['reference']=='page 1' for r in rows))

    def test_preserve_explicit_zero_and_ignore_outdoor_counterpart(self):
        result = self.read(['DESIGNATION','O.A. CFM','EVAP. CFM (1)'],
                           [['AH3','0','670'],['AC3','-','-'],['AH4','35','880']],
                           title='MINI-SPLIT SYSTEMS')
        self.assertEqual([(r['tag'],r['values']) for r in result],
                         [('AH-3',{'osa_cfm':0,'design_cfm':670}),('AH-4',{'osa_cfm':35,'design_cfm':880})])

    def test_withhold_measurements_selections_and_duplicate_flow_headers(self):
        self.assertEqual(self.read(['DESIGNATION','ACTUAL CFM','CFM'],[['EF18','455','495']]),[])
        self.assertEqual(self.read(['DESIGNATION','CFM','CFM'],[['EF18','455','495']]),[])
        self.assertEqual(self.read(['DESIGNATION','CFM'],[['EF18','455']],sheet='FAN PERFORMANCE SELECTION'),[])
        self.assertEqual(self.read(['DESIGNATION','CFM'],[['EF18','455']],title='CEILING DIFFUSERS'),[])

    def test_rotation_preserves_the_original_page_and_the_field(self):
        data = fixture(['DESIGNATION','CFM'],[['EF8','640']])
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation), pymupdf.open(stream=data,filetype='pdf') as doc:
                page = doc[0]
                page.set_rotation(rotation)
                found = designation_records(page,page_words(page),'drawing.pdf')
                self.assertEqual([(r['tag'],r['values']) for r in found],[('EF-8',{'design_cfm':640})])
                self.assertEqual(page.rotation,rotation)

    @unittest.skipUnless(sys.platform == 'linux', 'Hosted scan supervision requires Linux')
    def test_supervised_source_scan_proposes_values_without_verifying_them(self):
        from abp_server import read_sources
        data = fixture(['DESIGNATION','SA CFM','OA CFM','ESP (IN. WC)'],
                       [['FCU-7','675','55','0.65']],title='FAN COIL UNITS')
        review = read_sources([('schedule.pdf', data)])
        record, = [r for r in review['records'] if r['tag'] == 'FCU-7']
        self.assertEqual(review['source_checkpoints'][0]['native_status'],'completed_native_stage')
        self.assertEqual(record['status'],'UNVERIFIED')
        for field, expected in [('design_cfm',675),('osa_cfm',55),('esp',0.65)]:
            self.assertIsNone(record[field])
            self.assertEqual(record['proposed'][field],expected)


if __name__ == '__main__':
    unittest.main()
