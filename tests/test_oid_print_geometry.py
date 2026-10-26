"""Known-code paired OID2 crop QA: all samples are GENERATED DIGITAL images."""
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from scripts import oid_print_geometry as qa
from scripts import sonix_oid2 as oid


def sample(raw=1345, dpi=600, mm=11):
    return 255-np.asarray(oid.render(raw,dpi=dpi,width_mm=mm,height_mm=mm).getchannel('A'))


class PrintGeometryTests(unittest.TestCase):
    def test_correct_multiple_oids(self):
        for raw in (1331,1345,1347):
            with self.subTest(raw=raw):
                report,_=qa.analyze(sample(raw),raw_oid=raw,source_dpi=600)
                self.assertEqual(report['status'],'GEOMETRY_DIGITAL_MATCH')
                self.assertEqual(report['data_symbol_checks']['leading_decoded_oid'],raw)
                self.assertEqual(report['data_symbol_checks']['tiles_other_oid'],0)
                self.assertGreaterEqual(report['matched_fraction'],.98)
                self.assertEqual(report['a8s_compatible'],'UNTESTED')

    def test_wrong_oid_cannot_pass_merely_by_dot_proximity(self):
        report,_=qa.analyze(sample(1347),raw_oid=1345,source_dpi=600)
        self.assertEqual(report['status'],'MISMATCH_EXPECTED_CODE')
        self.assertEqual(report['data_symbol_checks']['leading_decoded_oid'],1347)
        # Different OID bitfields still share most dot positions.
        self.assertGreater(report['matched_fraction'],.85)

    def test_600_and_1200_dpi(self):
        for dpi in (600,1200):
            r,_=qa.analyze(sample(1345,dpi=dpi),raw_oid=1345,source_dpi=dpi)
            self.assertEqual(r['status'],'GEOMETRY_DIGITAL_MATCH')
            self.assertAlmostEqual(r['estimated_pitch_mm'],32*25.4/600,places=4)
            self.assertEqual(r['pitch_deviation_percent'],0)

    def test_known_translation_registration(self):
        im=sample()
        H=np.float32([[1.,0.,2.],[0.,1.,-1.]])
        scan=cv2.warpAffine(im,H,im.shape[::-1],borderValue=255)
        r,_=qa.analyze(scan,raw_oid=1345,source_dpi=600)
        self.assertEqual(r['status'],'GEOMETRY_DIGITAL_MATCH')
        self.assertGreater(r['matched_fraction'],.96)
        self.assertLess(abs(r['registration']['affine_2x3'][0][2]-2),.4)

    def test_scale_change_reported_not_hidden(self):
        im=sample(dpi=1200,mm=12)
        h,w=im.shape
        H=cv2.getRotationMatrix2D((w/2,h/2),0,1.015)
        H[:,2]+=[2.,-1.]
        scan=cv2.warpAffine(im,H,im.shape[::-1],flags=cv2.INTER_LINEAR,borderValue=255)
        r,_=qa.analyze(scan,raw_oid=1345,source_dpi=1200)
        self.assertEqual(r['status'],'GEOMETRY_DIGITAL_MATCH')
        self.assertAlmostEqual(r['pitch_deviation_percent'],1.5,delta=.6)
        self.assertEqual(r['data_symbol_checks']['leading_decoded_oid'],1345)

    def test_larger_ink_dots_change_measured_diameter(self):
        im=sample(dpi=1200)
        # Ink spreading: black features get wider.
        dark=cv2.dilate(255-im,np.ones((3,3),np.uint8))
        thick=np.uint8(255-dark)
        a,_=qa.analyze(im,raw_oid=1345,source_dpi=1200)
        b,_=qa.analyze(thick,raw_oid=1345,source_dpi=1200)
        self.assertGreater(b['median_dot_diameter_px'],a['median_dot_diameter_px'])

    def test_missing_dots_measured(self):
        im=sample(dpi=1200)
        damaged=im.copy()
        # Remove one complete primitive tile of data.
        damaged[64:128,64:128]=255
        r,_=qa.analyze(damaged,raw_oid=1345,source_dpi=1200)
        self.assertGreater(r['missing_dots'],0)
        self.assertGreater(r['data_symbol_checks']['tiles_data_incomplete_or_ambiguous'],0)

    def test_blank_never_fabricates_print_pass(self):
        r,_=qa.analyze(np.full((350,350),255,np.uint8),raw_oid=1345,source_dpi=600)
        self.assertEqual(r['status'],'INSUFFICIENT_DOTS')
        self.assertEqual(r['matched_dots'],0)

    def test_report_physical_dpi_is_assumed_not_measured(self):
        r,_=qa.analyze(sample(),raw_oid=1345,source_dpi=600,scan_dpi=1200)
        self.assertEqual(r['scan_dpi_assumed'],1200)
        self.assertAlmostEqual(r['pitch_deviation_percent'],-50,delta=.1)
        self.assertFalse(r['real_print_verified'])

    def test_reject_invalid_input(self):
        im=sample()
        for kw in ({'raw_oid':-1},{'raw_oid':65536},{'raw_oid':True},
                   {'raw_oid':1345,'source_dpi':300},
                   {'raw_oid':1345,'scan_dpi':float('nan')},
                   {'raw_oid':1345,'scan_dpi':12000}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):qa.analyze(im,**kw)
        with self.assertRaises(ValueError):qa.analyze(np.zeros((100,100),np.uint8),raw_oid=1345)
        with self.assertRaises(ValueError):qa.analyze(np.zeros((320,320),np.float32),raw_oid=1345)

    def test_cli_writes_evidence_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'scan.png';out=root/'out.json';overlay=root/'compare.png'
            self.assertTrue(cv2.imwrite(str(src),sample()))
            qa.main(['--image',str(src),'--raw-oid','1345','--source-dpi','600',
                     '--out',str(out),'--overlay',str(overlay)])
            data=json.loads(out.read_text())
            self.assertEqual(data['status'],'GEOMETRY_DIGITAL_MATCH')
            self.assertTrue(overlay.exists())
            self.assertEqual(src.read_bytes(),src.read_bytes())
            with self.assertRaises(SystemExit):
                qa.main(['--image',str(src),'--raw-oid','1345','--out',str(out)])


if __name__=='__main__':unittest.main()
