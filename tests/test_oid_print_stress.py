import unittest

from PIL import Image
from scripts import oid_print_stress as st
from scripts.sonix_oid2 import render


class OidPrintStressTests(unittest.TestCase):
    def test_baseline_600_and_1200(self):
        for dpi in (600, 1200):
            im = render(1345, dpi=dpi, width_mm=5, height_mm=5)
            r = st.measure(st.distort(im,"baseline"),raw_oid=1345,dpi=dpi)
            self.assertEqual(r['correct'],r['total_tiles'])
            self.assertEqual(r['wrong_oid'],0)

    def test_all_profiles_account_for_tiles(self):
        r=st.run(1345,1200,5,5)
        self.assertEqual(len(r['profiles']),len(st.PROFILES))
        for profile in r['profiles']:
            self.assertEqual(profile['total_tiles'],profile['correct']+profile['wrong_oid']+profile['unreadable'])
            self.assertGreater(profile['total_tiles'],0)

    def test_known_corruption_cannot_be_marked_perfect(self):
        im=render(1331,dpi=600,width_mm=4,height_mm=4)
        r=st.measure(st.distort(im,'dot_loss_1'),raw_oid=1331,dpi=600)
        self.assertEqual(r['correct'],0)

    def test_report_labels_not_hardware(self):
        r=st.run(1347,600,4,4)
        self.assertIn('A8S_UNVERIFIED',r['status'])
        self.assertIn('do not predict A8S recognition',r['warning'])

    def test_wrong_oid_does_not_pass(self):
        im=render(123,dpi=1200,width_mm=4,height_mm=4)
        r=st.measure(st.distort(im,'baseline'),raw_oid=124,dpi=1200)
        self.assertEqual(r['correct'],0)
        self.assertEqual(r['wrong_oid'],r['total_tiles'])

    def test_wrong_dpi_and_tiny_image(self):
        with self.assertRaises(ValueError):st.run(1345,300)
        with self.assertRaises(ValueError):st.measure(Image.new('L',(10,10),'white'),raw_oid=1,dpi=600)

    def test_blank_is_unreadable(self):
        gray=Image.new('L',(64,64),255)
        r=st.measure(gray,raw_oid=0,dpi=600)
        self.assertEqual(r['unreadable'],4)

    def test_reject_unknown_profile(self):
        with self.assertRaises(ValueError):st.distort(Image.new('RGB',(32,32),'white'),'nonexistent')


if __name__=='__main__':unittest.main()
