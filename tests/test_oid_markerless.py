"""Markerless *local patch* OID2 decoding tests. NO A8S hardware claim."""
import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from scripts import sonix_oid2 as oid
from scripts import oid_markerless as m


def printed(raw, *, dpi=1200):
    return 255-np.asarray(oid.render(raw,dpi=dpi,width_mm=20,height_mm=20).getchannel('A'))


def transform(src, angle=0., scale=1.0):
    h,w=src.shape
    rotated=cv2.warpAffine(src,cv2.getRotationMatrix2D((w/2,h/2),angle,scale),(w,h),borderValue=255)
    cut=int(.12*w)
    return rotated[cut:-cut,cut:-cut]


class MarkerlessTests(unittest.TestCase):
    def test_multiple_raw_ids(self):
        for raw in (0, 1331, 1345, 1347, 65535):
            with self.subTest(raw=raw):
                result,_=m.decode_markerless(transform(printed(raw)),approx_pitch_px=16)
                self.assertEqual(result['raw_oid'],raw)
                self.assertGreater(result['tiles_majority'],10)
                self.assertEqual(result['a8s_compatible'],'UNTESTED')

    def test_600_and_1200_dpi(self):
        for dpi in (600,1200):
            with self.subTest(dpi=dpi):
                result,_=m.decode_markerless(transform(printed(1345,dpi=dpi)),approx_pitch_px=8*(dpi//600))
                self.assertEqual(result['raw_oid'],1345)

    def test_arbitrary_rotation_without_any_markers(self):
        for angle in (-15, 0, 13, 25, 45, 90):
            with self.subTest(angle=angle):
                result,_=m.decode_markerless(transform(printed(1345),angle=angle,scale=1.06),approx_pitch_px=17)
                self.assertEqual(result['raw_oid'],1345)

    def test_blur_noise_and_contrast(self):
        rng=np.random.default_rng(2026)
        image=transform(printed(1347),angle=17)
        blur=cv2.GaussianBlur(image,(0,0),0.8)
        noisy=np.uint8(np.clip(blur*.85+30+rng.normal(0,3,blur.shape),0,255))
        result,_=m.decode_markerless(noisy,approx_pitch_px=16)
        self.assertEqual(result['raw_oid'],1347)

    def test_mixed_codes_must_not_pass(self):
        a=printed(1345);b=printed(1347)
        combined=np.where(np.arange(a.shape[1])[None,:]<a.shape[1]//2,a,b)[170:770,170:770].astype(np.uint8)
        result,_=m.decode_markerless(combined,approx_pitch_px=16)
        self.assertEqual(result['status'],'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(result['raw_oid'])

    def test_blank_and_noise_rejected(self):
        for image in (np.full((600,600),255,np.uint8),np.random.default_rng(41).integers(0,256,(600,600),dtype=np.uint8)):
            result,_=m.decode_markerless(image,approx_pitch_px=16)
            self.assertEqual(result['status'],'INSUFFICIENT_EVIDENCE')
            self.assertIsNone(result['raw_oid'])

    def test_wrong_expected_is_not_suppressed(self):
        result,_=m.decode_markerless(transform(printed(1345)),approx_pitch_px=16,expected_raw_oid=1331)
        self.assertEqual(result['raw_oid'],1345)
        self.assertFalse(result['matches_expected'])

    def test_input_validation(self):
        for kw in ({'approx_pitch_px':0},{'approx_pitch_px':100},{'expected_raw_oid':True},{'expected_raw_oid':65536}):
            with self.assertRaises(ValueError):m.decode_markerless(np.ones((500,500),np.uint8),**kw)
        with self.assertRaises(ValueError):m.decode_markerless(np.ones((100,100),np.uint8))
        with self.assertRaises(ValueError):m.decode_markerless(np.ones((3000,3000),np.uint8))

    def test_cli_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);scan=d/'crop.png';out=d/'report.json';rect=d/'normalized.png'
            cv2.imwrite(str(scan),transform(printed(1345)))
            m.main(['--image',str(scan),'--approx-pitch-px','16','--expected-raw-oid','1345',
                    '--out',str(out),'--normalized',str(rect)])
            result=json.loads(out.read_text())
            self.assertEqual(result['raw_oid'],1345)
            self.assertTrue(result['matches_expected'])
            self.assertTrue(rect.is_file())
            with self.assertRaises(SystemExit):
                m.main(['--image',str(scan),'--out',str(out)])


if __name__=='__main__':unittest.main()
