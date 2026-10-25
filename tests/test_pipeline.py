import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ant_reader


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.book = Path(__file__).resolve().parents[1] / "examples" / "starter_en.json"

    def test_stable_ids(self):
        book = ant_reader.validate_book(ant_reader.read_json(self.book))
        ledger = {"ids": {}}
        ids1 = ant_reader.assign_ids(ledger, book)
        ids2 = ant_reader.assign_ids(ledger, book)
        self.assertEqual(ids1, ids2)
        self.assertEqual(len(set(ids1.values())), 8)

    def test_duplicate_rejected(self):
        book = ant_reader.read_json(self.book)
        book["items"][1]["key"] = book["items"][0]["key"]
        with self.assertRaises(ValueError):
            ant_reader.validate_book(book)

    def test_prepare_creates_regions_without_fake_oid(self):
        ant_reader.prepare(SimpleNamespace(book=str(self.book), out=str(self.base), tts="none"))
        d = self.base/"books"/"starter_en_01"
        manifest = ant_reader.read_json(d/"regions.json")
        self.assertEqual(len(manifest["regions"]), 8)
        self.assertTrue((d/"artwork.pdf").exists())
        self.assertTrue(all(x["raw_oid"] is None for x in manifest["regions"]))

    def test_compose_rejects_missing_patterns(self):
        ant_reader.prepare(SimpleNamespace(book=str(self.book), out=str(self.base), tts="none"))
        m = self.base/"mapping.json"
        m.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Missing pattern"):
            ant_reader.compose(SimpleNamespace(out=str(self.base), book_id="starter_en_01", mapping=str(m),dpi=72,experimental=True))

    def test_experimental_composition_geometry_only(self):
        from PIL import Image
        ant_reader.prepare(SimpleNamespace(book=str(self.book), out=str(self.base), tts="none"))
        d = self.base/"books"/"starter_en_01"
        areas = ant_reader.read_json(d/"regions.json")["regions"]
        mapping={}
        for i, zone in enumerate(areas):
            w=round(zone["width_mm"]*72/25.4)
            h=round(zone["height_mm"]*72/25.4)
            # A single dot is a geometry test, NOT an optical OID code.
            im=Image.new("RGBA",(w,h),(255,255,255,0))
            im.putpixel((0,0),(0,0,0,255))
            asset=self.base/f"geometry_{i}.png"
            im.save(asset)
            mapping[zone["logical_id"]]={"raw_oid":70000+i,"pattern_png":asset.name,"tested_on_a8s":False}
        m=self.base/"mapping.json"
        m.write_text(json.dumps(mapping),encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Not marked tested"):
            ant_reader.compose(SimpleNamespace(out=str(self.base),book_id="starter_en_01",mapping=str(m),dpi=72,experimental=False))
        ant_reader.compose(SimpleNamespace(out=str(self.base),book_id="starter_en_01",mapping=str(m),dpi=72,experimental=True))
        self.assertTrue((d/"experimental_print.pdf").exists())


if __name__ == "__main__":
    unittest.main()
