"""Tests for tools/_occlusion.py (mask geometry shared by build and lint)."""
import unittest

from _tools import load

occ = load("_occlusion")

SMALL = {"label": "A", "x": .10, "y": .10, "w": .10, "h": .04}
LARGE = {"label": "Longer label", "x": .50, "y": .50, "w": .30, "h": .08}


class TestMaskBoxes(unittest.TestCase):
    def test_regions_are_kept_as_given_by_default(self):
        boxes = occ.mask_boxes({"regions": [SMALL, LARGE]})
        self.assertEqual(boxes, [(.10, .10, .10, .04), (.50, .50, .30, .08)])

    def test_uniform_masks_take_the_largest_size_centered_on_each_label(self):
        boxes = occ.mask_boxes({"uniform_masks": True, "regions": [SMALL, LARGE]})
        for box in boxes:
            self.assertAlmostEqual(box[2], .30)
            self.assertAlmostEqual(box[3], .08)
        # The small label stays at the center of its now larger mask.
        x, y, w, h = boxes[0]
        self.assertAlmostEqual(x + w / 2, SMALL["x"] + SMALL["w"] / 2)
        self.assertAlmostEqual(y + h / 2, SMALL["y"] + SMALL["h"] / 2)
        self.assertEqual(boxes[1], (.50, .50, .30, .08))

    def test_uniform_masks_are_shifted_back_inside_the_image(self):
        edge = {"label": "E", "x": .0, "y": .97, "w": .02, "h": .02}
        boxes = occ.mask_boxes({"uniform_masks": True, "regions": [edge, LARGE]})
        x, y, w, h = boxes[0]
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(y + h, 1.0 + 1e-9)
        self.assertAlmostEqual(w, .30)

    def test_uniform_masks_of_close_labels_are_trimmed_instead_of_overlapping(self):
        # A label stack (one per line) plus one tall two-line label elsewhere:
        # full-size masks would overlap their neighbors.
        stack = [{"label": str(n), "x": .1, "y": .1 + .05 * n, "w": .06, "h": .04}
                 for n in range(4)]
        side = [{"label": "S", "x": .12, "y": .8, "w": .04, "h": .04}]
        tall = {"label": "Two\nlines", "x": .6, "y": .5, "w": .2, "h": .08}
        regions = stack + side + [tall]
        boxes = occ.mask_boxes({"uniform_masks": True, "regions": regions})
        self.assertEqual(occ.overlapping_pairs(boxes), [])
        for region, (x, y, w, h) in zip(regions, boxes):
            with self.subTest(label=region["label"]):  # still hides its own label
                self.assertLessEqual(x, region["x"] + 1e-9)
                self.assertLessEqual(y, region["y"] + 1e-9)
                self.assertGreaterEqual(x + w, region["x"] + region["w"] - 1e-9)
                self.assertGreaterEqual(y + h, region["y"] + region["h"] - 1e-9)
        # Masks with room keep the common size.
        for n in (4, 5):
            self.assertAlmostEqual(boxes[n][2], .2)
            self.assertAlmostEqual(boxes[n][3], .08)

    def test_trimmed_uniform_masks_still_do_not_overlap_once_padded(self):
        # Labels .02 apart: room for both paddings, so padded masks just touch.
        stack = [{"label": str(n), "x": .1, "y": .1 + .06 * n, "w": .06, "h": .04}
                 for n in range(3)]
        tall = {"label": "T", "x": .6, "y": .5, "w": .2, "h": .08}
        boxes = occ.mask_boxes({"uniform_masks": True, "regions": stack + [tall]})
        self.assertEqual(occ.overlapping_pairs([occ.padded(b) for b in boxes]), [])

    def test_overlapping_regions_are_left_for_the_lint(self):
        regions = [{"label": "A", "x": .1, "y": .1, "w": .2, "h": .1},
                   {"label": "B", "x": .2, "y": .15, "w": .2, "h": .1}]
        boxes = occ.mask_boxes({"uniform_masks": True, "regions": regions})
        self.assertEqual(occ.overlapping_pairs(boxes), [(0, 1)])

    def test_padding_never_leaves_0_1(self):
        x, y, w, h = occ.padded((0.0, 0.0, 1.0, 1.0))
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 1.0)
        self.assertLessEqual(y + h, 1.0)


class TestOverlaps(unittest.TestCase):
    def test_disjoint_masks_do_not_overlap(self):
        self.assertEqual(occ.overlapping_pairs([(.1, .1, .1, .1), (.3, .1, .1, .1)]), [])

    def test_touching_masks_do_not_overlap(self):
        self.assertEqual(occ.overlapping_pairs([(.1, .1, .1, .1), (.2, .1, .1, .1)]), [])

    def test_overlapping_masks_are_reported_once(self):
        boxes = [(.1, .1, .2, .1), (.2, .15, .2, .1), (.8, .8, .1, .1)]
        self.assertEqual(occ.overlapping_pairs(boxes), [(0, 1)])


class TestNativeOcclusionField(unittest.TestCase):
    def test_one_cloze_per_region_with_anki_number_style(self):
        field = occ.native_occlusion_field(
            [(.1, .25, .3, .05), (.5, 0.0, 1.0, .125)], hide_all=False)
        self.assertEqual(
            field,
            "{{c1::image-occlusion:rect:left=.1:top=.25:width=.3:height=.05}}<br>"
            "{{c2::image-occlusion:rect:left=.5:top=0:width=1:height=.125}}")

    def test_hide_all_marks_every_shape_occlude_inactive(self):
        field = occ.native_occlusion_field([(.1, .1, .1, .1), (.3, .3, .1, .1)], hide_all=True)
        self.assertEqual(field.count(":oi=1}}"), 2)

    def test_coordinates_are_rounded_to_four_decimals(self):
        field = occ.native_occlusion_field([(1 / 3, .123456, .1, .1)], hide_all=False)
        self.assertIn("left=.3333:top=.1235:", field)


if __name__ == "__main__":
    unittest.main()
