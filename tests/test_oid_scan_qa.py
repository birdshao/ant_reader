"""Physical-layout OID2 quality tests; NO Xiaokedou A8S hardware involved."""
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts import oid_scan_qa as qa


class OidScanQaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, img):
        path = self.root/name
        if not cv2.imwrite(str(path), img):
            raise RuntimeError('Failed writing test image')
        return path

    def test_exact_600_1200_both_decode(self):
        for dpi in (600, 1200):
            for raw in (0, 1345, 65535):
                with self.subTest(dpi=dpi,raw=raw):
                    target = np.asarray(qa.make_target(raw,dpi).convert('L'))
                    result, region = qa.analyze_image(self.write(f't_{raw}_{dpi}.png',target), dpi, raw)
                    self.assertEqual(result['raw_oid'],raw)
                    self.assertEqual(result['tiles_majority'],196)
                    self.assertTrue(result['matches_expected'])
                    self.assertEqual(result['a8s_compatible'],'UNTESTED')
                    self.assertEqual(region.shape[0],qa.pixel_size(20,dpi))

    def test_perspective_registration(self):
        dpi=1200
        inp=np.asarray(qa.make_target(1331,dpi).convert('L'))
        h,w=inp.shape
        src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
        dst=np.float32([[65,95],[w+100,55],[w+50,h+125],[90,h+80]])
        H=cv2.getPerspectiveTransform(src,dst)
        warped=cv2.warpPerspective(inp,H,(w+170,h+160),borderValue=255)
        result,_=qa.analyze_image(self.write('perspective.png',warped),dpi,1331)
        self.assertEqual(result['raw_oid'],1331)
        self.assertGreaterEqual(result['tiles_majority'],150)

    def test_ninety_degree_rotation(self):
        img=np.asarray(qa.make_target(1347,600).convert('L'))
        # ArUco IDs recover orientation; scan has been rotated 90 degrees.
        rotated=cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE)
        r,_=qa.analyze_image(self.write('rotated.png',rotated),600,1347)
        self.assertEqual(r['raw_oid'],1347)

    def test_blur_and_noise_on_synthetic_image(self):
        np.random.seed(77)
        img=np.asarray(qa.make_target(1345,1200).convert('L'))
        blur=cv2.GaussianBlur(img,(0,0),.8)
        noise=np.random.normal(0,5,blur.shape)
        noisy=np.uint8(np.clip(blur.astype(float)+noise,0,255))
        r,_=qa.analyze_image(self.write('blur.png',noisy),1200,1345)
        self.assertEqual(r['raw_oid'],1345)
        self.assertGreaterEqual(r['tiles_majority'],150)

    def test_blank_code_region_never_reports_oid(self):
        dpi=600
        arr=np.array(qa.make_target(1331,dpi).convert('L'))
        x=qa.pixel_size(qa.CODE_ORIGIN_MM,dpi)
        side=qa.pixel_size(qa.CODE_SIZE_MM,dpi)
        arr[x:x+side,x:x+side]=255
        r,_=qa.analyze_image(self.write('empty.png',arr),dpi,1331)
        self.assertIsNone(r['raw_oid'])
        self.assertEqual(r['status'],'INSUFFICIENT_EVIDENCE')
        self.assertFalse(r['matches_expected'])

    def test_missing_markers_fails_loudly(self):
        im=np.full((800,800),255,np.uint8)
        with self.assertRaisesRegex(ValueError,'No ArUco'):
            qa.analyze_image(self.write('blank.png',im),1200,1345)

    def test_wrong_expected_detected(self):
        image=np.array(qa.make_target(1331,600).convert('L'))
        r,_=qa.analyze_image(self.write('correct.png',image),600,1345)
        self.assertEqual(r['raw_oid'],1331)
        self.assertFalse(r['matches_expected'])

    def test_bad_dpi_and_code(self):
        with self.assertRaises(ValueError): qa.make_target(22,300)
        with self.assertRaises(ValueError): qa.make_target(65536,600)

    def test_pdf_has_correct_physical_card(self):
        import fitz
        pdf=self.root/'page.pdf'
        qa.write_pdf(qa.make_target(1331,600),600,pdf)
        with fitz.open(pdf) as doc:
            self.assertEqual(len(doc),1)
            self.assertAlmostEqual(doc[0].rect.width*25.4/72,210.,places=2)
            self.assertAlmostEqual(doc[0].rect.height*25.4/72,297.,places=2)
            self.assertEqual(len(doc[0].get_images()),1)

    def test_source_not_overwritten(self):
        png=self.root/'x.png'
        self.write('x.png',np.array(qa.make_target(1331,600).convert('L')))
        output=self.root/'report.json'
        rc=qa.main(['scan','--image',str(png),'--dpi','600','--out',str(output)])
        self.assertIsNone(rc)
        self.assertEqual(json.loads(output.read_text())['status'],'DECODED_RESEARCH_ONLY')
        with self.assertRaises(SystemExit):
            qa.main(['scan','--image',str(png),'--dpi','600','--out',str(output)])


if __name__=='__main__':unittest.main()
