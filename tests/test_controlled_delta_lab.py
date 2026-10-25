import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts import controlled_delta_lab as lab


class ControlledDeltaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'private_samples').mkdir()

    def file(self, name, data):
        p=self.root/'private_samples'/name
        p.write_bytes(data)
        return p

    def spec(self, cases, **extra):
        s={'format':lab.SCHEMA,'baseline':'private_samples/base.nob','cases':cases,**extra}
        p=self.root/'spec.json'
        p.write_text(json.dumps(s),encoding='utf-8')
        return p

    def case(self, **extra):
        return {'id':'testcase','changed_only':'raw_oid','variant':'private_samples/new.nob',
                'before_oid':25001,'after_oid':25002,**extra}

    def test_oid_uint_matches(self):
        old=b'HEAD'+(25001).to_bytes(4,'little')+b'X'*80
        new=b'HEAD'+(25002).to_bytes(4,'little')+b'X'*80
        self.file('base.nob',old);self.file('new.nob',new)
        r=lab.analyze(self.spec([self.case()]))
        case=r['cases'][0]
        self.assertEqual(case['exact_changed_spans'],[[4,5]])
        self.assertIn({'offset':4,'encoding_hypothesis':'u32_little','width':4},case['numeric_substitution_hypotheses'])
        self.assertEqual(r['status'],'HYPOTHESES_ONLY_NOT_A8S_DECODER')
        self.assertNotIn(str(self.root),str(r))

    def test_unequal_size_no_false_offset(self):
        self.file('base.nob',b'12345');self.file('new.nob',b'123456')
        r=lab.analyze(self.spec([self.case()]))['cases'][0]
        self.assertFalse(r['same_size'])
        self.assertEqual(r['numeric_substitution_hypotheses'],[])
        self.assertEqual(r['exact_changed_spans'],[])

    def test_audio_case_does_not_guess_oid(self):
        self.file('base.nob',b'25001');self.file('new.nob',b'25002')
        r=lab.analyze(self.spec([{'id':'audio','variant':'private_samples/new.nob','changed_only':'audio'}]))
        self.assertEqual(r['cases'][0]['numeric_substitution_hypotheses'],[])

    def test_cross_case_same_offset(self):
        a=b'XYZ'+(25001).to_bytes(4,'little')+b'blah'
        b=b'XYZ'+(25002).to_bytes(4,'little')+b'blah'
        c=b'XYZ'+(25003).to_bytes(4,'little')+b'blah'
        self.file('base.nob',a);self.file('new.nob',b);self.file('third.nob',c)
        cases=[self.case(id='first'),self.case(id='second',variant='private_samples/third.nob',after_oid=25003)]
        r=lab.analyze(self.spec(cases))
        self.assertTrue(any(z['offset']==3 and z['cases']==2 for z in r['cross_case_same_offset_hypotheses']))

    def test_reject_path_traversal(self):
        self.file('base.nob',b'base');self.file('new.nob',b'new')
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case(variant='../other.nob')]))

    def test_reject_symlink(self):
        self.file('base.nob',b'base')
        target=self.file('new.nob',b'new')
        try:
            (self.root/'private_samples'/'link.nob').symlink_to(target)
        except OSError:
            self.skipTest('symlink unavailable')
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case(variant='private_samples/link.nob')]))

    def test_reject_ambiguous_spec(self):
        self.file('base.nob',b'base');self.file('new.nob',b'new')
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case(before_oid=25001,after_oid=25001)]))
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case(changed_only='audio')]))

    def test_reject_duplicate_ids(self):
        self.file('base.nob',b'base');self.file('new.nob',b'new')
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case(), self.case()]))

    def test_file_unchanged(self):
        x=self.file('base.nob',b'hello'+b'\x00'*1024)
        y=self.file('new.nob',b'hellO'+b'\x00'*1024)
        before=(hashlib.sha256(x.read_bytes()).hexdigest(),hashlib.sha256(y.read_bytes()).hexdigest())
        lab.analyze(self.spec([{'id':'metadata','changed_only':'metadata','variant':'private_samples/new.nob'}]))
        self.assertEqual(before,(hashlib.sha256(x.read_bytes()).hexdigest(),hashlib.sha256(y.read_bytes()).hexdigest()))

    def test_changed_spans_multiple(self):
        x=b'A'*3+b'B'*4+b'A'*4+b'Z'
        y=b'A'*3+b'C'*4+b'A'*4+b'X'
        a=self.file('base.nob',x);b=self.file('new.nob',y)
        self.assertEqual(lab._exact_spans(a,b,12)[0],[[3,7],[11,12]])

    def test_length_mismatch_ascii_skipped(self):
        self.file('base.nob',b'25001');self.file('new.nob',b'250011')
        case=self.case(before_oid=25001,after_oid=250011)
        x=lab.analyze(self.spec([case]))['cases'][0]
        self.assertEqual(x['numeric_substitution_hypotheses'],[])

    def test_scan_mib_bound(self):
        self.file('base.nob',b'a');self.file('new.nob',b'b')
        with self.assertRaises(ValueError):
            lab.analyze(self.spec([self.case()]),scan_mib=33)


if __name__=='__main__':
    unittest.main()
