"""Smoke test for tools/build_deck.py: builds a mini deck of each type into an .apkg.

Needs genanki -> only present in the build container (anki-cards). On the host
without genanki the test skips itself. Run inside the container e.g. with:
    docker run --rm -v "$PWD":/work --entrypoint python anki-cards \
        -m unittest discover -s /work/tests
"""
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from _tools import load

try:
    bd = load("build_deck")
    HAVE_GENANKI = True
except ModuleNotFoundError as error:
    if error.name != "genanki":
        raise
    HAVE_GENANKI = False

def _png_1x1():
    """Smallest valid PNG (1x1 white pixel), so Anki can read the image."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
            + chunk(b"IEND", b""))


@unittest.skipUnless(HAVE_GENANKI, "genanki not installed (build container only)")
class TestBuildSmoke(unittest.TestCase):
    def test_builds_valid_apkg(self):
        with tempfile.TemporaryDirectory() as d:
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T::Smoke", "cards": [
                {"type": "basic", "front": "Q", "back": "A"},
                {"type": "cloze", "text": "The {{c1::answer}}."},
                {"type": "typein", "front": "Q2", "back": "A2"},
            ]}), encoding="utf-8")
            out = Path(d) / "t.apkg"
            bd.build(str(cards), str(out))
            self.assertTrue(out.exists())
            self.assertTrue(zipfile.is_zipfile(out))

    def test_field_images_are_embedded(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "fig.png"
            img.write_bytes(b"\x89PNG fake")
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T::Img", "cards": [
                {"type": "basic", "front": "Q",
                 "back": f'A<br><img src="{img}">'},
            ]}), encoding="utf-8")
            out = Path(d) / "t.apkg"
            bd.build(str(cards), str(out))
            with zipfile.ZipFile(out) as z:
                media = json.loads(z.read("media"))
            self.assertIn("fig.png", media.values())

    def test_media_basename_clash_rejected(self):
        # Two DIFFERENT files with the same basename would overwrite each other
        # in Anki's flat media -> one card shows the wrong image.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            (Path(d) / "b").mkdir()
            (Path(d) / "a" / "fig.png").write_bytes(b"AAA")
            (Path(d) / "b" / "fig.png").write_bytes(b"BBB")
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T", "cards": [
                {"type": "basic", "front": "Q1",
                 "back": f'<img src="{Path(d) / "a" / "fig.png"}">'},
                {"type": "basic", "front": "Q2",
                 "back": f'<img src="{Path(d) / "b" / "fig.png"}">'},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Media name clash"):
                bd.build(str(cards), str(Path(d) / "t.apkg"))

    def test_spaced_image_attribute_is_packaged_including_raw_more(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "actual image.png"
            img.write_bytes(b"synthetic image")
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T", "cards": [
                {"type": "typein", "front": "Q", "back": "A",
                 "more": f'<img data-src="ignored.png" src = "{img}">'}]}), encoding="utf-8")
            out = Path(d) / "t.apkg"
            bd.build(str(cards), str(out))
            with zipfile.ZipFile(out) as z:
                media = json.loads(z.read("media"))
                self.assertEqual(list(media.values()), ["actual image.png"])
                self.assertEqual(z.read(next(iter(media))), b"synthetic image")

    def test_tags_as_string_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T", "cards": [
                {"type": "basic", "front": "Q", "back": "A", "tags": "bio"}]}),
                encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tags"):
                bd.build(str(cards), str(Path(d) / "t.apkg"))

    def test_deck_description_passed_through(self):
        with tempfile.TemporaryDirectory() as d:
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({
                "deck": "T::Desc", "description": "Forged from notes.pdf",
                "cards": [{"type": "basic", "front": "Q", "back": "A"}]}),
                encoding="utf-8")
            out = Path(d) / "t.apkg"
            bd.build(str(cards), str(out))
            # The description lands in the deck JSON inside the collection DB.
            atc = load("apkg_to_cards")
            con, tmp = atc.open_collection(str(out))
            try:
                _, decks_json = con.execute(
                    "SELECT models, decks FROM col").fetchone()
                blob = json.dumps(json.loads(decks_json))
            finally:
                con.close()
                import os
                os.unlink(tmp)
            self.assertIn("Forged from notes.pdf", blob)


class TestCollectFieldImages(unittest.TestCase):
    @unittest.skipUnless(HAVE_GENANKI, "genanki not installed (build container only)")
    def test_rewrites_local_src_keeps_remote(self):
        card = {"back": '<img src="a/b/fig.png"> <img src="https://x/y.png">'}
        media = set()
        bd.collect_field_images(card, media)
        self.assertEqual(media, {"a/b/fig.png"})
        self.assertIn('<img src="fig.png">', card["back"])
        self.assertIn('src="https://x/y.png"', card["back"])


if __name__ == "__main__":
    unittest.main()


HAS_ENGINE = HAVE_GENANKI and importlib.util.find_spec("anki") is not None


@unittest.skipUnless(HAS_ENGINE, "needs optional anki and genanki packages")
class TestNativeOcclusionImport(unittest.TestCase):
    def test_anki_imports_a_native_image_occlusion_note(self):
        import anki.lang
        from anki.collection import Collection, ImportAnkiPackageRequest
        from anki.import_export_pb2 import ImportAnkiPackageOptions
        anki.lang.set_lang("en")
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "eye.png"
            img.write_bytes(_png_1x1())
            cards = Path(d) / "t.cards.json"
            cards.write_text(json.dumps({"deck": "T::IO", "cards": [
                {"type": "occlusion", "native": True, "mode": "hide-all",
                 "uniform_masks": True, "image": str(img), "header": "Eye",
                 "regions": [{"label": "A", "x": .1, "y": .1, "w": .1, "h": .05},
                             {"label": "B", "x": .5, "y": .5, "w": .3, "h": .05}]},
            ]}), encoding="utf-8")
            out = Path(d) / "t.apkg"
            bd.build(str(cards), str(out))
            col = Collection(str(Path(d) / "c.anki2"))
            try:
                col.import_anki_package(ImportAnkiPackageRequest(
                    package_path=str(out),
                    options=ImportAnkiPackageOptions(with_scheduling=False)))
                nid, = col.find_notes("deck:T::IO")
                self.assertEqual(len(col.get_note(nid).cards()), 2)
                # Only a note type Anki itself flags as Image Occlusion opens in
                # its mask editor; for others this raises.
                io = col.get_image_occlusion_note(nid).note
                self.assertTrue(io.occlude_inactive)
                self.assertEqual(io.image_file_name, "eye.png")
                widths = {p.value for o in io.occlusions for s in o.shapes
                          for p in s.properties if p.name == "width"}
                self.assertEqual(len(widths), 1)
            finally:
                col.close()
