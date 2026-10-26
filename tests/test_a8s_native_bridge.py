"""No actual A8S hardware/files; evidence gating and synthetic vendor input only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts import a8s_native_bridge as m


def r(raw, vendor, book='book_a', confirmed=True):
    return {'book_id':book,'raw_oid':raw,'vendor_code':vendor,
            'evidence':'vendor_client_measured' if confirmed else 'unverified_hypothesis',
            'confirmed':confirmed,'source_note':'Synthetic unit test observation'}


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)

    def spec(self,rows):
        p=self.d/'observations.json'
        p.write_text(json.dumps({'format':m.SCHEMA,'observations':rows}),encoding='utf-8')
        return p

    def test_hypotheses_never_become_verified(self):
        rows=m.observations(self.spec([r(1345,101,confirmed=False)]))
        report=m.analyze(rows)
        self.assertFalse(report['ready_for_vendor_staging'])
        self.assertEqual(report['confirmed_observations'],0)

    def test_confirmed_records_can_be_analyzed(self):
        info=m.analyze(m.observations(self.spec([r(1345,101),r(1347,102)])))
        self.assertTrue(info['ready_for_vendor_staging'])
        self.assertEqual(info['hypotheses']['identity_raw_to_vendor']['matches'],0)
        self.assertFalse(info['hypotheses']['identity_raw_to_vendor']['proof'])

    def test_cross_book_same_raw_not_false_conflict(self):
        info=m.analyze(m.observations(self.spec([r(1345,101),r(1345,202,book='book_b')])))
        self.assertEqual(info['mapping_conflicts'],[])
        self.assertEqual(info['cross_book_variation'],[{'raw_oid':1345,'contexts':2}])

    def test_same_book_conflicting_codes_rejected(self):
        info=m.analyze(m.observations(self.spec([r(1345,101),r(1345,102)])))
        self.assertTrue(info['mapping_conflicts'])

    def test_same_vendor_code_to_two_raws_rejected(self):
        info=m.analyze(m.observations(self.spec([r(1345,101),r(1347,101)])))
        self.assertTrue(info['mapping_conflicts'])

    def test_cannot_confirm_hypothesis(self):
        row=r(1345,101,confirmed=False);row['confirmed']=True
        with self.assertRaisesRegex(ValueError,'Hypotheses'):
            m.observations(self.spec([row]))

    def test_bad_code_bool_bad_provenance(self):
        for bad in (True,-1,65536,1.5):
            with self.subTest(bad=bad):
                row=r(bad,101)
                with self.assertRaises(ValueError):m.observations(self.spec([row]))
        row=r(1345,101);row['evidence']='guessed'
        with self.assertRaises(ValueError):m.observations(self.spec([row]))

    def test_oidproducer_comparison_is_only_hypothesis(self):
        table=list(range(65536));table[1345],table[101]=table[101],table[1345]
        info=m.analyze([r(1345,101)],table)
        hypothesis=info['hypotheses']['oidproducer1020_raw_to_internal']
        self.assertEqual(hypothesis['matches'],1)
        self.assertFalse(hypothesis['proof'])

    def test_stage_hard_fails_on_example_hypotheses(self):
        book=self.d/'book_a';book.mkdir()
        (book/'regions.json').write_text(json.dumps({'regions':[{'logical_id':'book_a:apple:word','audio_index':1}]}))
        (book/'audio_manifest.json').write_text(json.dumps([{'logical_id':'book_a:apple:word','audio_index':1,'path':'audio/1.mp3'}]))
        binding=self.d/'binding.json'
        binding.write_text(json.dumps({'format':'ant-reader-a8s-bindings/1','book_id':'book_a',
                                       'cover':{'raw_oid':1331},'regions':{'book_a:apple:word':{'raw_oid':1345}}}))
        evidence=self.spec([r(1331,100,confirmed=False),r(1345,101,confirmed=False)])
        with self.assertRaisesRegex(ValueError,'No confirmed'):
            m.stage(book,binding,evidence,self.d/'out')
        self.assertFalse((self.d/'out').exists())

    def test_stage_creates_vendor_client_input_not_nob(self):
        book=self.d/'book_a';(book/'audio').mkdir(parents=True)
        (book/'audio'/'1.mp3').write_bytes(b'ID3'+b'\x00'*330)
        (book/'regions.json').write_text(json.dumps({'regions':[{'logical_id':'book_a:apple:word','audio_index':1}]}))
        (book/'audio_manifest.json').write_text(json.dumps([{'logical_id':'book_a:apple:word','audio_index':1,'path':'audio/1.mp3'}]))
        binding=self.d/'binding.json'
        binding.write_text(json.dumps({'format':'ant-reader-a8s-bindings/1','book_id':'book_a',
                                       'cover':{'raw_oid':1331},'regions':{'book_a:apple:word':{'raw_oid':1345}}}))
        evidence=self.spec([r(1331,100),r(1345,101)])
        out=self.d/'out'
        info=m.stage(book,binding,evidence,out)
        self.assertFalse(info['resource_pack_generated'])
        self.assertEqual(info['entry_vendor_code'],100)
        self.assertEqual((out/'vendor_client_input'/'101.mp3').read_bytes(),b'ID3'+b'\x00'*330)
        self.assertFalse(list(out.rglob('*.nob')))
        with self.assertRaises(FileExistsError):m.stage(book,binding,evidence,out)

    def test_stage_missing_audio_fails_before_outputs(self):
        book=self.d/'book_a';book.mkdir()
        (book/'regions.json').write_text(json.dumps({'regions':[{'logical_id':'book_a:apple:word','audio_index':1}]}))
        (book/'audio_manifest.json').write_text(json.dumps([{'logical_id':'book_a:apple:word','audio_index':1,'path':'audio/1.mp3'}]))
        binding=self.d/'binding.json'
        binding.write_text(json.dumps({'format':'ant-reader-a8s-bindings/1','book_id':'book_a',
                                       'cover':{'raw_oid':1331},'regions':{'book_a:apple:word':{'raw_oid':1345}}}))
        evidence=self.spec([r(1331,100),r(1345,101)])
        with self.assertRaisesRegex(ValueError,'audio'):
            m.stage(book,binding,evidence,self.d/'out')
        self.assertFalse((self.d/'out').exists())

if __name__=='__main__':unittest.main()
