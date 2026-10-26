"""Whole-image *synthetic* multi-code spotting; no real printed sheet or A8S pen."""
import json
import tempfile
from pathlib import Path
import unittest
import cv2
import numpy as np
from scripts import oid_page_locator as p
from scripts import sonix_oid2 as oid


def page_with_three(dpi=1200,noise=0):
    pg=np.full((1650,2250),255,np.uint8)
    size=13 if dpi==1200 else 17
    for x,y,raw in ((120,90,1345),(1390,125,1347),(840,980,1331)):
        src=255-np.asarray(oid.render(raw,dpi=dpi,width_mm=size,height_mm=size).getchannel('A'))
        pg[y:y+src.shape[0],x:x+src.shape[1]]=src
    cv2.putText(pg,'HELLO APPLE 123',(220,830),cv2.FONT_HERSHEY_SIMPLEX,1.6,0,4)
    if noise:
        rng=np.random.default_rng(2026)
        pg[rng.random(pg.shape)<noise]=0
    return pg

class OidPageLocatorTests(unittest.TestCase):
    def test_multi_id_1200(self):
        r=p.analyze(page_with_three())
        self.assertEqual(r['candidate_count'],3)
        self.assertEqual(r['decoded_count'],3)
        self.assertEqual([x['raw_oid'] for x in r['candidates']],[1345,1347,1331])
        self.assertEqual(r['a8s_compatible'],'UNTESTED')

    def test_multi_id_600(self):
        r=p.analyze(page_with_three(dpi=600),approx_pitch_px=8)
        self.assertEqual(r['decoded_count'],3)
        self.assertEqual({x['raw_oid'] for x in r['candidates']},{1331,1345,1347})

    def test_noise_1200(self):
        r=p.analyze(page_with_three(noise=.001))
        self.assertEqual(r['decoded_count'],3)

    def test_blur_1200(self):
        img=cv2.GaussianBlur(page_with_three(),(0,0),.4)
        r=p.analyze(img)
        self.assertEqual(r['decoded_count'],3)

    def test_text_only_has_no_decoded(self):
        img=np.full((800,1600),255,np.uint8)
        for y in (120,210,330,460,620):
            cv2.putText(img,'APPLE 123 abc! hello',(40,y),cv2.FONT_HERSHEY_SIMPLEX,1.5,0,3)
        r=p.analyze(img)
        self.assertEqual(r['decoded_count'],0)

    def test_blank_noise_and_checker_no_decode(self):
        rng=np.random.default_rng(10)
        samples=[np.full((600,900),255,np.uint8),rng.integers(0,256,(600,900),dtype=np.uint8),
                 (np.indices((600,900)).sum(axis=0)%2*255).astype(np.uint8)]
        for sample in samples:
            with self.subTest(i=len(sample)):
                r=p.analyze(sample)
                self.assertEqual(r['decoded_count'],0)

    def test_connected_mixed_codes_are_rejected(self):
        a=255-np.asarray(oid.render(1345,dpi=1200,width_mm=13,height_mm=13).getchannel('A'))
        b=255-np.asarray(oid.render(1347,dpi=1200,width_mm=13,height_mm=13).getchannel('A'))
        a[:,a.shape[1]//2:]=b[:,b.shape[1]//2:]
        pg=np.full((900,1100),255,np.uint8)
        pg[90:90+a.shape[0],90:90+a.shape[1]]=a
        r=p.analyze(pg)
        self.assertEqual(r['decoded_count'],0)
        self.assertTrue(all(x['raw_oid'] is None for x in r['candidates']))

    def test_input_validation_and_capacity(self):
        for data,kw in ((np.ones((80,100),np.uint8),{}),
                        (np.ones((400,400),np.float32),{}),
                        (np.ones((400,400),np.uint8),{'approx_pitch_px':4}),
                        (np.ones((400,400),np.uint8),{'max_regions':True}),
                        (np.ones((400,400),np.uint8),{'max_regions':30})):
            with self.assertRaises(ValueError):p.analyze(data,**kw)
        with self.assertRaisesRegex(ValueError,'30 MP'):
            p.locate_candidates(np.zeros((6000,6000),np.uint8))

    def test_cli_report_annotation_and_non_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'page.png';report=d/'out.json';ann=d/'annotated.png'
            cv2.imwrite(str(source),page_with_three())
            p.main(['--image',str(source),'--out',str(report),'--annotated',str(ann)])
            result=json.loads(report.read_text())
            self.assertEqual(result['decoded_count'],3)
            self.assertTrue(ann.is_file())
            self.assertEqual(result['source_file'],'page.png')
            with self.assertRaises(SystemExit):p.main(['--image',str(source),'--out',str(report)])

if __name__=='__main__':unittest.main()
