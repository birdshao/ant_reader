"""Synthetic colored-page QA regressions. Not physical scans or A8S tests."""
import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
import tifffile

from scripts import oid_color_qa as c
from scripts import oid_large_page as big
from scripts import sonix_oid2 as oid


def rgb_page(colorful=True, noise=0):
    h,w=1650,2300
    yy,xx=np.indices((h,w),dtype=np.float32)
    # Smooth tinted illustrations/gradients, plus a dark saturated band.
    rgb=np.empty((h,w,3),np.uint8)
    rgb[:,:,0]=np.uint8(20+60*(xx/w)) if colorful else 255
    rgb[:,:,1]=np.uint8(50+110*(yy/h)) if colorful else 255
    rgb[:,:,2]=np.uint8(85+65*((xx+yy)/(w+h))) if colorful else 255
    for x,y,raw in ((105,110,1345),(1450,120,1347),(860,910,1331)):
        alpha=np.asarray(oid.render(raw,dpi=1200,width_mm=13,height_mm=13).getchannel('A'))
        region=rgb[y:y+alpha.shape[0],x:x+alpha.shape[1]]
        region[alpha>128]=[0,0,0]
    # Colored large illustration rectangles and nearby thick text must not be recognized.
    cv2.rectangle(rgb,(700,40),(1250,160),(220,150,30),-1)
    cv2.putText(rgb,'APPLE', (750,800),cv2.FONT_HERSHEY_SIMPLEX,1.8,(0,0,0),4)
    if noise:
        rng=np.random.default_rng(2026)
        mask=rng.random((h,w))<noise
        rgb[mask]=0
    return rgb


class ColorQaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_color_mode_recovers_three_codes(self):
        data=c.analyze_page(rgb_page(),mode='ink',tile_size=1600,overlap=720)
        self.assertEqual(data['decoded_count'],3)
        self.assertEqual({x['raw_oid'] for x in data['regions']},{1331,1345,1347})
        self.assertEqual(data['a8s_compatible'],'UNTESTED')
        self.assertTrue(all('optical_metrics' in x for x in data['regions']))

    def test_auto_mode_handles_tinted_page(self):
        data=c.analyze_page(rgb_page(),mode='auto')
        self.assertEqual({x['raw_oid'] for x in data['regions']},{1331,1345,1347})
        self.assertEqual(data['decoded_count'],3)

    def test_white_page_still_works(self):
        data=c.analyze_page(rgb_page(False),mode='ink')
        self.assertEqual(data['decoded_count'],3)

    def test_gray_and_rgb_residual_consistency(self):
        gray=np.full((200,200),95,np.uint8)
        gray[40:42,60:62]=0
        rgb=np.repeat(gray[:,:,None],3,axis=2)
        a=c.enhance_ink(gray,16)
        b=c.enhance_ink(rgb,16)
        self.assertTrue(np.array_equal(a,b))
        self.assertEqual(int(a[40,60]),0)
        self.assertEqual(int(a[100,100]),255)

    def test_negative_examples(self):
        h,w=700,850
        samples=[np.full((h,w,3),(25,60,90),dtype=np.uint8),
                 np.random.default_rng(1).integers(0,256,(h,w,3),dtype=np.uint8)]
        for i,s in enumerate(samples):
            with self.subTest(i=i):
                r=c.analyze_page(s,mode='ink',tile_size=850,overlap=200)
                self.assertEqual(r['decoded_count'],0)

    def test_rgb_png_color_preserved(self):
        source=self.root/'sample.png'
        rgb=np.full((300,400,3),[20,60,120],np.uint8)
        cv2.imwrite(str(source),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
        with big.open_page(source,preserve_color=True) as (data,method):
            self.assertEqual(method,'IN_MEMORY_IMAGE')
            self.assertEqual(tuple(data[10,10]),(20,60,120))
        with big.open_page(source) as (data,method):
            self.assertEqual(data.ndim,2)

    def test_rgb_tiff_memmap_readonly(self):
        f=self.root/'rgb.tif'; src=rgb_page()
        tifffile.imwrite(f,src,compression=None,photometric='rgb')
        with big.open_page(f,preserve_color=True) as (img,reader):
            self.assertEqual(reader,'TIFF_READ_ONLY_MEMMAP')
            self.assertFalse(img.flags.writeable)
            self.assertTrue(np.array_equal(img[100,100],src[100,100]))
            report=c.analyze_page(img,mode='ink')
            self.assertEqual(report['decoded_count'],3)

    def test_cli_outputs_report_and_preview(self):
        f=self.root/'rgb.png';report=self.root/'results.json';prev=self.root/'preview.png'
        cv2.imwrite(str(f),cv2.cvtColor(rgb_page(),cv2.COLOR_RGB2BGR))
        c.main(['--image',str(f),'--out',str(report),'--preview',str(prev),'--mode','ink'])
        output=json.loads(report.read_text())
        self.assertEqual(output['decoded_count'],3)
        self.assertEqual(output['source_file'],f.name)
        self.assertTrue(prev.is_file())
        with self.assertRaises(SystemExit):
            c.main(['--image',str(f),'--out',str(report)])

    def test_invalid_controls(self):
        p=rgb_page(False)[:500,:500]
        for kwargs in ({'mode':'magic'},{'tile_size':390},{'overlap':159},
                       {'tile_size':400,'overlap':300},{'max_regions':True},
                       {'approx_pitch_px':80}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                c.analyze_page(p,**kwargs)
        with self.assertRaises(ValueError):
            c.enhance_ink(p,80)

    def test_grades_are_not_hardware_certification(self):
        r=c.analyze_page(rgb_page(),mode='ink')
        self.assertTrue(all(x['evidence_grade'].endswith('DIGITAL') for x in r['regions']))
        self.assertNotIn('A8S_VALIDATED',str(r))


if __name__=='__main__':
    unittest.main()
