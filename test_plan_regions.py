"""Synthetic outlined-text geometry; no private drawing content."""
import unittest
from unittest.mock import patch

import pymupdf

from abp_plan_regions import paired_text_regions


class Page:
    rect = pymupdf.Rect(0, 0, 600, 800)
    rotation_matrix = pymupdf.Matrix(1, 1)

    def __init__(self, paths):
        self.paths = paths

    def get_cdrawings(self):
        return self.paths


def row(x, y, count=5, height=6):
    # Deliberately not real letters: geometry selects a crop only.
    return [{'rect': (x + i * 5.5, y, x + i * 5.5 + 4, y + height),
             'fill': None, 'items': [('l', (0, 0), (1, 1))]}
            for i in range(count)]


def pair(x=100, y=100):
    return row(x, y) + row(x - 1, y + 10, 6)


class PairedTextRegionTests(unittest.TestCase):
    def test_both_lines_retained_with_margin_and_without_layer_hints(self):
        boxes, truncated = paired_text_regions(Page(pair()))
        self.assertFalse(truncated)
        self.assertEqual(len(boxes), 1)
        self.assertLess(boxes[0][0], 99)
        self.assertLess(boxes[0][1], 100)
        self.assertGreater(boxes[0][2], 130)
        self.assertGreater(boxes[0][3], 116)

    def test_multiple_equal_geometry_locations_stay_separate(self):
        boxes, truncated = paired_text_regions(Page(pair() + pair(300, 600)))
        self.assertFalse(truncated)
        self.assertEqual(len(boxes), 2)
        self.assertGreater(boxes[1][1], 590)

    def test_duplicate_overprinted_glyph_paths_do_not_duplicate_crop(self):
        self.assertEqual(len(paired_text_regions(Page(pair() * 3))[0]), 1)

    def test_single_line_long_prose_filled_symbols_and_unaligned_lines(self):
        for paths in (row(100, 100), row(100, 100, 25) + row(100, 110, 25),
                      row(100, 100) + row(200, 110),
                      [{**p, 'fill': (0, 0, 0)} for p in pair()]):
            self.assertEqual(paired_text_regions(Page(paths)), ([], False))

    def test_outside_and_nonfinite_geometry_is_not_a_crop(self):
        paths = pair(-300, 100) + [{'rect': (0, 0, float('inf'), 6), 'fill': None, 'items': [()]}]
        self.assertEqual(paired_text_regions(Page(paths)), ([], False))

    def test_rotation_uses_displayed_coordinates(self):
        page = Page(pair())
        page.rotation_matrix = pymupdf.Matrix(-1, 0, 0, -1, 600, 800)
        boxes, truncated = paired_text_regions(page)
        self.assertFalse(truncated)
        self.assertEqual(len(boxes), 1)
        self.assertTrue(pymupdf.Rect(boxes[0]).contains(pymupdf.Rect(470, 684, 501, 700)))

    def test_path_glyph_line_and_region_caps_explicitly_truncate(self):
        page = Page(pair() + pair(300, 600))
        for options in ({'max_paths': 3}, {'max_glyphs': 3}, {'max_lines': 1}):
            self.assertEqual(paired_text_regions(page, **options), ([], True))
        boxes, truncated = paired_text_regions(page, max_regions=1)
        self.assertTrue(truncated)
        self.assertEqual(len(boxes), 1)

    def test_expired_deadline_does_not_read_paths(self):
        page = Page(pair())
        with patch.object(page, 'get_cdrawings', side_effect=AssertionError('must not read')):
            self.assertEqual(paired_text_regions(page, deadline=0), ([], True))

    def test_dense_band_pair_work_and_output_are_bounded(self):
        # Hundreds of short lines in two baselines share the same search
        # bucket. They must not cause an unbounded all-pairs/dedup pass.
        page = Page([path for x in range(100, 12100, 60) for path in pair(x, 100)])
        page.rect = pymupdf.Rect(0, 0, 13000, 800)
        boxes, truncated = paired_text_regions(page, max_regions=4)
        self.assertTrue(truncated)
        self.assertEqual(len(boxes), 4)
        boxes, truncated = paired_text_regions(page, max_pair_checks=1)
        self.assertTrue(truncated)
        self.assertEqual(boxes, [])

    def test_dense_geometry_respects_running_deadline(self):
        page = Page([path for x in range(100, 12100, 60) for path in pair(x, 100)])
        page.rect = pymupdf.Rect(0, 0, 13000, 800)
        # A clock that advances on each check makes the deadline deterministic
        # even on fast CI machines; no sleep or timing tolerance is needed.
        with patch('abp_plan_regions.time.monotonic', side_effect=(i / 1000 for i in range(10000))):
            boxes, truncated = paired_text_regions(page, deadline=2.5, max_regions=1000)
        self.assertTrue(truncated)
        self.assertLess(len(boxes), 200)


if __name__ == '__main__':
    unittest.main()
