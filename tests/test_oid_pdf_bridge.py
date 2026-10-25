import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
def load_module(name):
    p=ROOT/"scripts"/(name+".py")
    s=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(s)
    s.loader.exec_module(module)
    return module

bridge=load_module("oid_pdf_bridge")
binder=load_module("make_oid_binding")

class OidPdfBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.pdf=self.base/"sample.pdf"
        doc=fitz.open()
        page=doc.new_page(width=210*72/25.4,height=297*72/25.4)
        for r in range(8):
            for c in range(8):
                page.draw_circle(((20+c*.7)*72/25.4,(30+r*.7)*72/25.4),.14,
                                 color=(0,0,0),fill=(0,0,0))
        doc.save(self.pdf);doc.close()
        self.spec=self.base/"spec.json"
        self.config={"format":bridge.SCHEMA,"source_pdf":"sample.pdf",
                     "source":"SYNTHETIC TEST DOTS, NOT A8S", "dpi":600,
                     "tiles":[{"id":"word","raw_oid":3211,"page":1,"rect_mm":[19,29,10,10]}]}
        self.write_spec()

    def write_spec(self):
        self.spec.write_text(json.dumps(self.config),encoding="utf-8")

    def test_external_pdf_extract_and_audit(self):
        result=bridge.import_pdf(self.spec,self.base/"output")
        self.assertEqual(result["status"],"UNVERIFIED_A8S")
        import sys
        sys.path.insert(0,str(ROOT))
        import oid_lab
        candidates=oid_lab.load_candidates(self.base/"output/oid_candidates.json")
        self.assertEqual(candidates[0]["raw_oid"],3211)
        with Image.open(self.base/"output/tiles/word.png") as img:
            self.assertEqual(img.mode,"RGBA")
            self.assertEqual(img.getchannel("A").getextrema(),(0,255))

    def test_empty_crop_rejected(self):
        self.config["tiles"][0]["rect_mm"]=[90,90,10,10]
        self.write_spec()
        with self.assertRaisesRegex(ValueError,"dark pixel density"):
            bridge.import_pdf(self.spec,self.base/"output")

    def test_duplicate_oid_rejected(self):
        self.config["tiles"].append({**self.config["tiles"][0],"id":"duplicate"})
        self.write_spec()
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            bridge.import_pdf(self.spec,self.base/"output")

    def test_traversal_rejected(self):
        self.config["source_pdf"]="../private.pdf"
        self.write_spec()
        with self.assertRaisesRegex(ValueError,"relative path"):
            bridge.import_pdf(self.spec,self.base/"output")

    def test_crop_outside_page_rejected(self):
        self.config["tiles"][0]["rect_mm"]=[205,280,20,20]
        self.write_spec()
        with self.assertRaisesRegex(ValueError,"outside page"):
            bridge.import_pdf(self.spec,self.base/"output")

    def test_bind_two_regions_and_entry(self):
        bridge.import_pdf(self.spec,self.base/"output")
        manifest=self.base/"output/oid_candidates.json"
        candidates=json.loads(manifest.read_text())
        for label,oid in [("sentence",3212),("entry",3213)]:
            (self.base/"output/tiles"/(label+".png")).write_bytes(
                (self.base/"output/tiles/word.png").read_bytes())
            candidates["candidates"].append({**candidates["candidates"][0],
                                              "id":label,"raw_oid":oid,
                                              "image":"tiles/"+label+".png"})
        manifest.write_text(json.dumps(candidates))
        book=self.base/"books/demo";book.mkdir(parents=True)
        (book/"regions.json").write_text(json.dumps({"regions":[
            {"logical_id":"demo:apple:word"},{"logical_id":"demo:apple:sentence"}]}))
        assignment=self.base/"assignment.json"
        assignment.write_text(json.dumps({"cover":"entry","regions":{
            "demo:apple:word":"word","demo:apple:sentence":"sentence"}}))
        result=binder.bind(manifest,assignment,book,self.base/"bound")
        self.assertFalse(result["cover"]["tested_on_a8s"])
        self.assertEqual(len(result["regions"]),2)

    def test_duplicate_binding_rejected(self):
        bridge.import_pdf(self.spec,self.base/"output")
        book=self.base/"books/demo";book.mkdir(parents=True)
        (book/"regions.json").write_text(json.dumps({"regions":[{"logical_id":"word"}]}))
        assignment=self.base/"assignment.json"
        assignment.write_text(json.dumps({"cover":"word","regions":{"word":"word"}}))
        with self.assertRaisesRegex(ValueError,"reused"):
            binder.bind(self.base/"output/oid_candidates.json",assignment,book,self.base/"bound")

if __name__=="__main__":
    unittest.main()
