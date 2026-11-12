"""Synthetic keyed-note joins; no private project evidence or source fixtures."""
import math
import unittest
import pymupdf
from abp_keynotes import keynote_regions, keynote_candidates


def w(x, y, text, confidence=95):
    return {'box': [x, y, x + max(5, len(text) * 5), y + 8], 'text': text, 'confidence': confidence}


def fixture():
    markers = [[600, 200 + i * 50, 616, 216 + i * 50] for i in range(3)]
    markers += [[100, 100, 116, 116], [200, 100, 216, 116], [300, 100, 316, 116]]
    regions = [[584, 160, 1100, 350]]
    words = [w(620, 175, 'KEYED'), w(655, 175, 'NOTES:')]
    for index, (model, flow) in enumerate([('6100', '225CFM'), ('6100R', ''), ('7200', '135CFM')]):
        y = 203 + index * 50
        words += [w(605, y, str(index + 1)), w(625, y, model), w(660, y, 'LINEAR'),
                  w(695, y, 'SLOT'), w(720, y, 'GRILLE.'), w(760, y, '10-INCH'), w(805, y, 'DUCT.')]
        if flow:
            words.append(w(625, y + 13, flow))
    words += [w(105, 103, '1'), w(205, 103, '3'), w(305, 103, '3')]
    return words, markers, regions


class KeynoteTests(unittest.TestCase):
    def parse(self, words=None, markers=None, regions=None, **kwargs):
        defaults = fixture()
        return keynote_candidates(words if words is not None else defaults[0],
                                  markers if markers is not None else defaults[1],
                                  regions if regions is not None else defaults[2],
                                  'synthetic.pdf', 1, plan_confirmed=True, **kwargs)

    def test_note_marker_is_not_outlet_and_equal_devices_stay_distinct(self):
        found = self.parse()
        self.assertEqual([x['review_values'] for x in found], [{'design_cfm': 225}, {'design_cfm': 135}, {'design_cfm': 135}])
        self.assertEqual(len({tuple(x['position']) for x in found}), 3)
        self.assertTrue(all(not x['include'] and x['values'] == {} and x['status'] == 'UNVERIFIED' for x in found))
        self.assertTrue(all(x['size'] == x['system'] == x['location'] == '' for x in found))

    def test_return_no_flow_and_ambiguous_flow_excluded(self):
        words, markers, regions = fixture()
        words.append(w(405, 103, '2')); markers.append([400, 100, 416, 116])
        self.assertEqual(len(self.parse(words, markers, regions)), 3)
        words.append(w(680, 216, '325CFM'))
        self.assertEqual(len(self.parse(words, markers, regions)), 2)

    def test_low_confidence_flow_withheld_and_number_never_guessed(self):
        words, markers, regions = fixture()
        next(x for x in words if x['text'] == '225CFM')['confidence'] = 40
        found = self.parse(words, markers, regions)
        self.assertEqual(found[0]['review_values'], {})
        next(x for x in words if x['text'] == '1' and x['box'][0] == 105)['confidence'] = 40
        self.assertEqual(len(self.parse(words, markers, regions)), 2)
        next(x for x in words if x['text'] == '3' and x['box'][0] == 205)['text'] = 'B'
        self.assertEqual(len(self.parse(words, markers, regions)), 1)

    def test_heading_plan_context_and_conflicting_digits_required(self):
        words, markers, regions = fixture()
        self.assertEqual(keynote_candidates(words, markers, regions, 'x', 1), [])
        words[0]['text'] = 'GENERAL'
        self.assertEqual(self.parse(words, markers, regions), [])
        words, markers, regions = fixture()
        words.append(w(105, 103, '2'))
        self.assertEqual(len(self.parse(words, markers, regions)), 2)

    def test_duplicate_note_numbers_invalidate_join(self):
        words, markers, regions = fixture()
        next(x for x in words if x['text'] == '2' and x['box'][0] == 605)['text'] = '1'
        self.assertEqual(len(self.parse(words, markers, regions)), 2)

    def test_exact_number_reread_can_confirm_but_conflicting_number_cannot(self):
        words, markers, regions = fixture()
        words.append(w(105, 103, '1', 20))
        self.assertEqual(len(self.parse(words, markers, regions)), 3)
        words.append(w(105, 103, '2', 20))
        self.assertEqual(len(self.parse(words, markers, regions)), 2)

    def test_missing_or_nonfinite_confidence_never_proposes_flow(self):
        for confidence in (None, float('nan'), float('inf')):
            words, markers, regions = fixture()
            next(x for x in words if x['text'] == '225CFM')['confidence'] = confidence
            found = self.parse(words, markers, regions)
            self.assertEqual(found[0]['review_values'], {})
            self.assertEqual(found[0]['confidence_min'], 0)

    def test_pentagon_geometry_rotation_bounds_and_nonclosed_rejection(self):
        doc = pymupdf.open(); page = doc.new_page(width=900, height=900)
        for x, y in [(100, 100), (600, 200), (600, 250), (600, 300)]:
            points = [(x + 8 + 8 * math.sin(i * 2 * math.pi / 5), y + 8 - 8 * math.cos(i * 2 * math.pi / 5)) for i in range(5)]
            shape = page.new_shape(); shape.draw_polyline(points); shape.finish(closePath=True); shape.commit()
        page.draw_rect(pymupdf.Rect(20, 20, 36, 36))
        points = [(408 + 8 * math.sin(i * 2 * math.pi / 5), 108 - 8 * math.cos(i * 2 * math.pi / 5)) for i in range(5)]
        shape = page.new_shape(); shape.draw_polyline([points[i] for i in [0, 2, 4, 1, 3]])
        shape.finish(closePath=True); shape.commit()
        shape = page.new_shape(); shape.draw_polyline([(x + 50, y) for x, y in points])
        shape.finish(closePath=False); shape.commit()
        boxes, regions, truncated = keynote_regions(page)
        self.assertEqual(len(boxes), 4); self.assertEqual(len(regions), 1); self.assertFalse(truncated)
        _, _, truncated = keynote_regions(page, max_markers=2)
        self.assertTrue(truncated)
        page.set_rotation(90)
        rotated, _, _ = keynote_regions(page)
        self.assertEqual(len(rotated), 4)
        self.assertTrue(all(pymupdf.Rect(b) in page.rect for b in rotated))
        self.assertEqual(keynote_regions(page, max_paths=1), ([], [], True))

    def test_limits_are_fail_closed(self):
        words, markers, regions = fixture()
        self.assertEqual(self.parse(words, markers, regions, max_words=2), [])
        self.assertEqual(self.parse(words, markers, regions, max_markers=2), [])


if __name__ == '__main__':
    unittest.main()
