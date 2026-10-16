"""Mask geometry for occlusion cards (stdlib only, shared by build and lint).

Regions are fractions of the image size (0..1): x/y = top-left corner,
w/h = width/height. A "box" is the (x, y, w, h) tuple of one mask.
"""

# A bit of air around each box so mask/outline don't squeeze the (often small)
# text skin-tight -> much easier to recognize and read. Native masks use less:
# they stay editable in Anki, and labels there are usually measured tightly.
BOX_PAD = 0.01
NATIVE_BOX_PAD = 0.005


def box_pad(card):
    """Padding of a card's masks: classic self-rendered or Anki-native."""
    return NATIVE_BOX_PAD if card.get("native") else BOX_PAD


def _centered(region, w, h):
    """Box of size w*h centered on the region, shifted back inside 0..1."""
    cx = region["x"] + region["w"] / 2
    cy = region["y"] + region["h"] / 2
    x = min(max(cx - w / 2, 0.0), max(1.0 - w, 0.0))
    y = min(max(cy - h / 2, 0.0), max(1.0 - h, 0.0))
    return (x, y, w, h)


def _gap(a0, a1, b0, b1):
    """Free space between two intervals (negative when they overlap)."""
    return max(b0 - a1, a0 - b1)


def _trim(box_a, box_b, ra, rb, pad):
    """Shrinks two overlapping boxes up to the middle of the gap between their
    regions, along the axis where the regions lie further apart. Each box
    keeps covering its own region; overlapping regions are left as they are."""
    gap_x = _gap(ra["x"], ra["x"] + ra["w"], rb["x"], rb["x"] + rb["w"])
    gap_y = _gap(ra["y"], ra["y"] + ra["h"], rb["y"], rb["y"] + rb["h"])
    if max(gap_x, gap_y) < 0:
        return
    pos, size = (0, 2) if gap_x >= gap_y else (1, 3)
    key_pos, key_size = ("x", "w") if pos == 0 else ("y", "h")
    if ra[key_pos] > rb[key_pos]:
        box_a, box_b, ra, rb = box_b, box_a, rb, ra
    # box_a/ra lie before box_b/rb on the chosen axis. Stop `pad` short of
    # the middle line, so the padded masks meet there instead of overlapping,
    # but never cut into the region itself.
    ra_end, rb_start = ra[key_pos] + ra[key_size], rb[key_pos]
    line = (ra_end + rb_start) / 2
    a_end = max(line - pad, ra_end)
    b_start = min(line + pad, rb_start)
    if box_a[pos] + box_a[size] > a_end:
        box_a[size] = a_end - box_a[pos]
    if box_b[pos] < b_start:
        box_b[size] -= b_start - box_b[pos]
        box_b[pos] = b_start


# A region more than this factor taller than the (lower) median holds several
# lines. The lower median keeps one-line labels as the reference even when
# half of a figure's labels span two lines.
_MULTILINE_FACTOR = 1.5


def _one_line_height(regions):
    heights = sorted(r["h"] for r in regions)
    median = heights[(len(heights) - 1) // 2]
    return max(h for h in heights if h <= _MULTILINE_FACTOR * median)


def mask_boxes(card):
    """Unpadded mask box per region, in region order.

    With "uniform_masks": true every mask gets the width of the widest region
    and the height of the tallest one-line region, centered on its own label:
    the mask size then no longer hints at the length of the hidden answer.
    Multi-line labels keep their own height (it only tells that the answer
    spans several lines, which the figure shows anyway). Where two such masks
    would overlap, both are trimmed to the middle of the gap between their
    labels ("as uniform as possible").
    """
    regions = card["regions"]
    if not (card.get("uniform_masks") and regions):
        return [(r["x"], r["y"], r["w"], r["h"]) for r in regions]
    w = max(r["w"] for r in regions)
    h = _one_line_height(regions)
    boxes = [list(_centered(r, w, max(h, r["h"]))) for r in regions]
    pad = box_pad(card)
    # Trimming only shrinks boxes, so it never creates a new overlap and one
    # pass over all pairs suffices.
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if overlapping_pairs([padded(boxes[i], pad), padded(boxes[j], pad)]):
                _trim(boxes[i], boxes[j], regions[i], regions[j], pad)
    return [tuple(b) for b in boxes]


def padded(box, pad=BOX_PAD):
    """Box enlarged by `pad` on every side, clamped to the image."""
    bx, by, bw, bh = box
    x = max(0.0, bx - pad)
    y = max(0.0, by - pad)
    w = min(1.0 - x, bw + 2 * pad)
    h = min(1.0 - y, bh + 2 * pad)
    return (x, y, w, h)


def overlapping_pairs(boxes):
    """Index pairs (i, j), i < j, of boxes sharing a non-empty area.

    Overlapping masks leak answers: revealing one uncovers part of another
    label, or one mask hides part of the queried one. Boxes that merely touch
    (up to float noise) do not overlap."""
    eps = 1e-9
    pairs = []
    for i, (ax, ay, aw, ah) in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            bx, by, bw, bh = boxes[j]
            if (min(ax + aw, bx + bw) - max(ax, bx) > eps
                    and min(ay + ah, by + bh) - max(ay, by) > eps):
                pairs.append((i, j))
    return pairs


def _io_number(value):
    """Anki's own style for IO coordinates: 4 decimals, no leading zero."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text[1:] if text.startswith("0.") else text


def native_occlusion_field(boxes, hide_all):
    """Content of the 'Occlusion' field of Anki's native Image Occlusion note.

    One cloze number per box -> one card per box. oi=1 ("occlude inactive")
    is Anki's "Hide all, guess one" mode; without it: "Hide one, guess one".
    """
    oi = ":oi=1" if hide_all else ""
    return "<br>".join(
        f"{{{{c{n}::image-occlusion:rect:left={_io_number(x)}:top={_io_number(y)}"
        f":width={_io_number(w)}:height={_io_number(h)}{oi}}}}}"
        for n, (x, y, w, h) in enumerate(boxes, start=1)
    )
