import unittest
from scripts import sonix_oid2 as oid

# Independently generated upstream Albi_tuzka PNGs; SHA of raw RGBA pixels.
GOLDEN={
1331:"83f33b447826e68f11d388aaa03727535ee739ac16ac068c7b802fe241b7ef31",
1345:"693f68ac6040bdf4cdbe82f831cebc9a89bfd87cddf6dab395fb468589dd1c25",
1347:"2d09b30df30d22c6c574ff1d5c0c5e894ba2758477095a394ea2255268cc8be3",
}
class SonixOid2Tests(unittest.TestCase):
    def test_pixel_exact_golden(self):
        for raw,digest in GOLDEN.items():
            with self.subTest(raw=raw):
                png=oid.render(raw,dpi=1200,width_mm=20,height_mm=20)
                self.assertEqual(png.size,(944,944))
                self.assertEqual(oid.digest_pixels(png),digest)
                self.assertEqual(oid.decode_ideal_tile(png),raw)
    def test_roundtrip(self):
        for raw in (0,1,6,123,1331,1345,1347,65535):
            with self.subTest(raw=raw):
                self.assertEqual(oid.decode_symbols(oid.encode_symbols(raw)),raw)
                self.assertEqual(oid.decode_ideal_tile(oid.render(raw,dpi=600,width_mm=5,height_mm=5),dpi=600),raw)
    def test_checksum_corruption(self):
        x=oid.encode_symbols(1345)
        x[0]^=1
        with self.assertRaises(ValueError):oid.decode_symbols(x)
    def test_invalid(self):
        for v in (-1,65536,True,"12"):
            with self.assertRaises(ValueError):oid.encode_symbols(v)
        with self.assertRaises(ValueError):oid.render(12,dpi=300)
    def test_frame(self):
        self.assertEqual(len(oid.tile_dots(1331)),16)
        self.assertIn((1,16),oid.tile_dots(1331))
    def test_table_literal_parse(self):
        t=oid.import_upstream_internal_table("@oid_tbl_int2raw=(0..65535);")
        self.assertEqual(len(t),65536)
        self.assertEqual(t[100],100)
    def test_table_does_not_execute_perl(self):
        with self.assertRaises(ValueError):
            oid.import_upstream_internal_table('@oid_tbl_int2raw=(0..65534,system("evil"));')
