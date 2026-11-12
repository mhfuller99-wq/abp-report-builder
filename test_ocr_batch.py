"""Synthetic batch OCR transport/geometry tests; no client source fixtures."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from abp_ocr_batch import tesseract_batch_words
from abp_ocr_regions import render_geometry


HEADER = 'level\tpage_num\tleft\ttop\twidth\theight\tconf\ttext\n'


def record(level, page, text='', *, left=2, top=3, width=12, height=8, conf=95):
    return f'{level}\t{page}\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}\n'


class ObservedPage:
    def __init__(self, page):
        self.page = page
        self.rect = page.rect
        self.display_reads = 0

    def get_displaylist(self):
        self.display_reads += 1
        return self.page.get_displaylist()


class BatchOCRTests(unittest.TestCase):
    def setUp(self):
        self.doc = pymupdf.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.jobs = [{'box': [20.17, 30.29, 70.39, 60.61], 'pixels': 100_000},
                     {'box': [220.21, 330.35, 280.43, 365.61], 'pixels': 100_000},
                     {'box': [420.11, 630.23, 490.37, 665.49], 'pixels': 100_000}]
        self.calls = []

    def tearDown(self):
        self.doc.close()

    def engine(self, tsv):
        def run(args, **kwargs):
            position = args.index('tesseract')
            images = Path(args[position + 1]).read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(images), len(set(images)))
            self.assertTrue(all(Path(path).is_file() for path in images))
            self.calls.append((args, kwargs, images))
            Path(args[position + 2] + '.tsv').write_text(tsv, encoding='utf-8')
            return subprocess.CompletedProcess(args, 0)
        return run

    def test_one_display_list_one_process_and_exact_origin_with_empty_middle_crop(self):
        observed = ObservedPage(self.page)
        tsv = HEADER + record(1, 1) + record(5, 1, '12"') + record(1, 2) + record(1, 3) + record(5, 3, '171CFM')
        with patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(tsv)):
            found = tesseract_batch_words(observed, self.jobs, 10)
        self.assertEqual(observed.display_reads, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([words[0]['text'] if words else None for words in found], ['12"', None, '171CFM'])
        for index in (0, 2):
            rect = pymupdf.Rect(self.jobs[index]['box'])
            zoom, _ = render_geometry(rect, self.jobs[index]['pixels'], 4.)
            pix = self.page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect,
                                       colorspace=pymupdf.csGRAY, alpha=False)
            self.assertEqual(found[index][0]['box'], [(pix.x+2)/zoom, (pix.y+3)/zoom,
                                                      (pix.x+14)/zoom, (pix.y+11)/zoom])
        self.assertTrue(all(not Path(path).exists() for path in self.calls[0][2]))
        self.assertIn('--exec-with-parent', self.calls[0][0])
        self.assertLessEqual(self.calls[0][1]['timeout'], 10)

    def test_rotated_page_coordinates_follow_displayed_crop(self):
        self.page.set_rotation(90)
        jobs = [{'box': [100.17, 40.29, 160.39, 70.61], 'pixels': 100_000}]
        with patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(HEADER + record(1, 1) + record(5, 1, '4'))):
            found = tesseract_batch_words(self.page, jobs, 10, psm=10)
        rect = pymupdf.Rect(jobs[0]['box'])
        zoom, _ = render_geometry(rect, jobs[0]['pixels'], 4.)
        pix = self.page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect,
                                   colorspace=pymupdf.csGRAY, alpha=False)
        self.assertEqual(found[0][0]['box'][:2], [(pix.x+2)/zoom, (pix.y+3)/zoom])
        args = self.calls[0][0]
        self.assertEqual(args[args.index('--psm') + 1], '10')

    def test_missing_duplicate_unknown_and_headerless_pages_fail_closed(self):
        for tsv in (HEADER + record(1, 1),
                    HEADER + record(1, 1) + record(1, 1) + record(1, 2) + record(1, 3),
                    HEADER + record(1, 4), HEADER + record(5, 1, '100'), 'bad\theader\n'):
            with self.subTest(tsv=tsv), patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(tsv)):
                with self.assertRaises(ValueError):
                    tesseract_batch_words(self.page, self.jobs, 10)

    def test_nonfinite_confidence_or_out_of_bounds_word_fails_closed(self):
        for options in ({'conf': 'nan'}, {'conf': 101}, {'left': -1}, {'width': 10000}, {'height': 0}):
            tsv = HEADER + record(1, 1) + record(5, 1, '100', **options)
            with self.subTest(options=options), patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(tsv)):
                with self.assertRaises(ValueError):
                    tesseract_batch_words(self.page, self.jobs[:1], 10)

    def test_count_pixel_and_parameter_limits_checked_before_render(self):
        observed = ObservedPage(self.page)
        for jobs, options in ((self.jobs * 11, {}), (self.jobs, {'max_total_pixels': 100}),
                              ([{'box': self.jobs[0]['box'], 'pixels': 1.5}], {}),
                              (self.jobs, {'max_zoom': 6}), (self.jobs, {'psm': 11}),
                              (self.jobs, {'max_total_pixels': 40_000_001})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                tesseract_batch_words(observed, jobs, 10, **options)
        self.assertEqual(observed.display_reads, 0)
        self.assertEqual(tesseract_batch_words(observed, [], 10), [])

    def test_word_and_tsv_size_caps_apply_across_batch(self):
        tsv = HEADER + record(1, 1) + record(5, 1, '100') + record(1, 2) + record(5, 2, '200')
        for options in ({'max_words': 1}, {'max_tsv_bytes': 10}):
            with patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(tsv)):
                with self.assertRaises(ValueError):
                    tesseract_batch_words(self.page, self.jobs[:2], 10, **options)

    def test_render_deadline_stops_before_ocr_and_process_failure_propagates(self):
        with patch('abp_ocr_batch.time.monotonic', side_effect=[0, 0, 2]), patch('abp_ocr_batch.subprocess.run') as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                tesseract_batch_words(self.page, self.jobs, 1)
            run.assert_not_called()
        with patch('abp_ocr_batch.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'tesseract')):
            with self.assertRaises(subprocess.CalledProcessError):
                tesseract_batch_words(self.page, self.jobs, 10)

    def test_blank_images_are_valid_empty_results_with_all_page_headers(self):
        tsv = HEADER + ''.join(record(1, page) for page in (1, 2, 3))
        with patch('abp_ocr_batch.subprocess.run', side_effect=self.engine(tsv)):
            self.assertEqual(tesseract_batch_words(self.page, self.jobs, 10), [[], [], []])


if __name__ == '__main__':
    unittest.main()
