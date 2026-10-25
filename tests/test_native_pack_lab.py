import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts import native_pack_lab as p


class NativePackLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def new(self, name, data):
        f = self.root / name
        f.write_bytes(data)
        return f

    def test_signature_only_evidence(self):
        a = self.new('x.nob', b'PK\x03\x04' + b'\x00' * 100)
        result = p.inspect(a)
        self.assertEqual(result['magic_evidence'], 'ZIP-local-header')
        self.assertEqual(result['a8s_supported'], 'UNKNOWN')
        self.assertIsNone(result['decoded_oids'])

    def test_extensions_do_not_prove_format(self):
        a = self.new('fake.nod', b'xyz' * 20)
        self.assertEqual(p.inspect(a)['magic_evidence'], 'unknown-signature')

    def test_entropy_bounds(self):
        self.assertEqual(p.entropy(b'\0' * 100), 0)
        self.assertAlmostEqual(p.entropy(bytes(range(256)) * 5), 8.0, places=4)

    def test_small_file_one_window(self):
        self.assertEqual(p.sample_offsets(2), [0])
        a = self.new('tiny.nos', b'AZ')
        self.assertEqual(p.inspect(a)['samples'][0]['read_bytes'], 2)

    def test_digest(self):
        x = b'foo' * 20
        a = self.new('x.nob', x)
        self.assertEqual(p.inspect(a)['sha256'], hashlib.sha256(x).hexdigest())

    def test_read_only(self):
        a = self.new('x.nob', b'abcd' * 2000)
        before = a.read_bytes()
        p.inspect(a)
        self.assertEqual(a.read_bytes(), before)

    def test_compare_differences(self):
        a = self.new('a.nob', b'A'*1000+b'xyz'+b'Z'*999)
        b = self.new('b.nob', b'A'*1000+b'qqq'+b'Z'*999)
        r=p.compare(a,b,block_size=1024)
        self.assertEqual(r['common_prefix_bytes'],1000)
        self.assertEqual(r['common_suffix_bytes_nonoverlapping'],999)
        self.assertEqual(r['aligned_blocks_checked'],2)
        self.assertEqual(r['aligned_blocks_equal'],1)

    def test_equal_contents_in_distinct_files(self):
        a=self.new('a.nod',b'abc'*10000)
        b=self.new('b.nod',a.read_bytes())
        r=p.compare(a,b)
        self.assertEqual(r['common_prefix_bytes'],a.stat().st_size)
        self.assertEqual(r['common_suffix_bytes_nonoverlapping'],0)
        self.assertEqual(r['aligned_blocks_equal'],1)

    def test_comparison_reject_self(self):
        a=self.new('x.nob',b'abcd')
        with self.assertRaises(ValueError):
            p.compare(a,a)

    def test_empty_reject(self):
        a=self.new('empty.nob',b'')
        with self.assertRaises(ValueError):
            p.inspect(a)

    def test_symlink_reject(self):
        a=self.new('base',b'ABCD')
        b=self.root/'link.nob'
        try:
            b.symlink_to(a)
        except (PermissionError, NotImplementedError, OSError):
            self.skipTest('No symlink support')
        with self.assertRaises(ValueError):
            p.inspect(b)

    def test_write_no_overwrite(self):
        target=self.root/'test.json'
        p.save_report(target,{'a':1})
        with self.assertRaises(FileExistsError):
            p.save_report(target,{'a':2})
        self.assertEqual(json.loads(target.read_text()), {'a':1})

    def test_no_absolute_path_leak(self):
        a=self.new('sample.nod', b'\x12\x34'*9999)
        info=p.inspect(a)
        self.assertNotIn(str(self.root),str(info))


if __name__ == '__main__':
    unittest.main()