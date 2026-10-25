import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import fitz
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oid_lab

class OidLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)

    def _manifest(self, pixels=(240,120), dpi=600, oid=56001):
        p=self.d/'oid_source.png'
        img=Image.new('RGBA',pixels,(255,255,255,0))
        img.putpixel((2,2),(0,0,0,255));img.save(p)
        cfg={'candidates':[{'id':'candidate-1','raw_oid':oid,'source':'manual-export-OidProducer',
                            'image':'oid_source.png','source_dpi':dpi}]}
        path=self.d/'candidates.json';path.write_text(json.dumps(cfg));return path

    def test_blank_sheet_has_explicit_warning_and_ruler(self):
        p=self.d/'blank.pdf';oid_lab.make_template(p)
        with fitz.open(p) as d:
            self.assertEqual(len(d),1)
            self.assertIn('NO OID',d[0].get_text())
            self.assertAlmostEqual(d[0].rect.width,210*oid_lab.MM,places=2)

    def test_exact_native_physical_dimensions_and_hash_audit(self):
        cfg=self._manifest()
        pdf,audit=oid_lab.make_candidate_sheet(cfg,self.d/'test.pdf')
        meta=json.loads(audit.read_text())['candidates'][0]
        self.assertEqual(meta['pixels'],[240,120])
        self.assertAlmostEqual(meta['printed_mm'][0],10.16,places=2)
        self.assertEqual(meta['sha256'],oid_lab.file_hash(self.d/'oid_source.png'))
        with fitz.open(pdf) as f:
            self.assertEqual(len(f),1)
            imgs=f[0].get_images(full=True)
            self.assertEqual(len(imgs),1)
            placement=f[0].get_image_rects(imgs[0][0])[0]
            self.assertAlmostEqual(placement.width/oid_lab.MM,10.16,places=2)
            self.assertAlmostEqual(placement.height/oid_lab.MM,5.08,places=2)
            self.assertIn('UNVERIFIED',f[0].get_text())

    def test_unsafe_paths_and_duplicate_ids_fail(self):
        cfg=self._manifest();raw=json.loads(cfg.read_text())
        raw['candidates'][0]['image']='../outside.png'
        cfg.write_text(json.dumps(raw))
        with self.assertRaises(ValueError): oid_lab.load_candidates(cfg)
        raw['candidates'][0]['image']='oid_source.png'
        raw['candidates'].append(raw['candidates'][0].copy());cfg.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'duplicate'):oid_lab.load_candidates(cfg)

    def test_oversize_fails_without_resampling(self):
        cfg=self._manifest(pixels=(2400,2400),dpi=600)
        with self.assertRaisesRegex(ValueError,'no downscaling'):oid_lab.load_candidates(cfg)

    def test_scan_log_is_aggregate_and_not_certified_for_small_sample(self):
        path=self.d/'results.csv'
        oid_lab.record(path,cid='c1',raw_oid=25001,expected='apple',observed='apple',attempts=20,correct=20)
        result=oid_lab.summarize(path)
        self.assertEqual(result[0]['accuracy'],1.0)
        self.assertEqual(result[0]['lab_status'],'NOT_CERTIFIED')
        oid_lab.record(path,cid='c1',raw_oid=25001,expected='apple',observed='apple',attempts=80,correct=79,wrong_audio=0)
        self.assertEqual(oid_lab.summarize(path)[0]['lab_status'],'PASS_LAB_THRESHOLD')
        oid_lab.record(path,cid='c1',raw_oid=25001,expected='apple',observed='dog',attempts=1,correct=0,wrong_audio=1)
        self.assertEqual(oid_lab.summarize(path)[0]['lab_status'],'NOT_CERTIFIED')

    def test_invalid_scan_counts_fail(self):
        with self.assertRaises(ValueError):
            oid_lab.record(self.d/'r.csv',cid='one',raw_oid=1,expected='a',observed='b',attempts=2,correct=3)

if __name__=='__main__':unittest.main()