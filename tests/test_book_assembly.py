import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import fitz
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ant_reader
import book_assembly as asm

ROOT=Path(__file__).resolve().parents[1]


class BookAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.d=Path(self.t.name)
        book_file=self.d/'mybook.json'
        book_file.write_text(json.dumps({'book_id':'unit_test_01','title':'Read Test', 'items':[
            {'key':'apple','english':'Apple','chinese':'苹果','sentence':'This is an apple.'}]}))
        ant_reader.prepare(SimpleNamespace(book=str(book_file),out=str(self.d/'prep'),tts='none'))
        self.b=self.d/'prep'/'books'/'unit_test_01'
        self.cfg=self.d/'binding.json'
        ids=[a['logical_id'] for a in ant_reader.read_json(self.b/'regions.json')['regions']]
        self.ids=ids
        self.bind={'format':'ant-reader-a8s-bindings/1','book_id':'unit_test_01',
                   'cover':self._pattern('entrance',56001),
                   'regions':{ids[0]:self._pattern('word',25001),ids[1]:self._pattern('sentence',25002)}}
        self._write()

    def _pattern(self,name,oid,*,side=240):
        path=self.d/f'{name}.png'
        im=Image.new('RGBA',(side,side),(255,255,255,0))
        for x in range(0,side,6):
            for y in range(0,side,6):
                im.putpixel((x,y),(0,0,0,255))
        im.save(path)
        return {'raw_oid':oid,'source':'SYNTHETIC GEOMETRY ONLY - NOT VALID OID','image':path.name,'source_dpi':600,'tested_on_a8s':False}

    def _write(self):
        self.cfg.write_text(json.dumps(self.bind),encoding='utf-8')

    def test_tiling_geometry_does_not_scale(self):
        positions=asm.tile_positions(fitz.Rect(0,0,50*asm.MM,25*asm.MM),[10.16,10.16])
        self.assertEqual(len(positions),8)
        self.assertAlmostEqual(positions[0].width/asm.MM,10.16,places=3)
        self.assertAlmostEqual(positions[-1].height/asm.MM,10.16,places=3)

    def test_generate_experimental_only_with_distinct_cover_and_audio_missing(self):
        out=self.d/'out'
        result=asm.compose(self.b,self.cfg,out,allow_missing_audio=True)
        self.assertEqual(result['status'],'EXPERIMENTAL_NOT_A8S_VERIFIED')
        self.assertEqual(len(result['missing_audio']),2)
        self.assertEqual(len(result['regions']),2)
        self.assertTrue((out/'vendor_handoff_NOT_PLAYABLE.zip').is_file())
        self.assertEqual(len(list((out/'handoff_mp3_by_raw_oid').iterdir())),0)
        with fitz.open(out/'EXPERIMENTAL_print_book.pdf') as doc:
            self.assertEqual(len(doc),2)
            self.assertIn('NOT known',doc[0].get_text())
            self.assertIn('UNVERIFIED',doc[1].get_text())
            self.assertGreater(len(doc[1].get_image_rects(doc[1].get_images()[0][0])),0)
            # Every original PNG must retain its native 10.16mm physical tile size.
            for page in doc:
                for img in page.get_images(full=True):
                    for rect in page.get_image_rects(img[0]):
                        self.assertAlmostEqual(rect.width/asm.MM,10.16,delta=.03)
                        self.assertAlmostEqual(rect.height/asm.MM,10.16,delta=.03)

    def test_missing_audio_is_default_hard_stop(self):
        with self.assertRaisesRegex(ValueError,'Missing audio'):
            asm.compose(self.b,self.cfg,self.d/'out')

    def test_duplicate_cover_content_oid_rejected(self):
        self.bind['cover']['raw_oid']=25001
        self._write()
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            asm.compose(self.b,self.cfg,self.d/'out',allow_missing_audio=True)

    def test_incomplete_binding_rejected(self):
        del self.bind['regions'][self.ids[0]]
        self._write()
        with self.assertRaisesRegex(ValueError,'cover every'):
            asm.compose(self.b,self.cfg,self.d/'out',allow_missing_audio=True)

    def test_opaque_overlay_fails_safe(self):
        file=self.d/'word.png'
        Image.new('RGB',(240,240),'white').save(file)
        with self.assertRaisesRegex(ValueError,'RGBA'):
            asm.compose(self.b,self.cfg,self.d/'out',allow_missing_audio=True)

    def test_too_large_tile_for_region_fails_no_scaling(self):
        self.bind['regions'][self.ids[1]]=self._pattern('huge',25002,side=1200)
        self._write()
        with self.assertRaisesRegex(ValueError,'larger than 50 mm|No full OID tile'):
            asm.compose(self.b,self.cfg,self.d/'out',allow_missing_audio=True)

    def test_audio_handoff_named_raw_oid_not_logical_id(self):
        for a in ant_reader.read_json(self.b/'audio_manifest.json'):
            p=self.b/a['path'];p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(b'ID3'+b'0'*350)
        result=asm.compose(self.b,self.cfg,self.d/'out')
        self.assertEqual(result['missing_audio'],[])
        self.assertTrue((self.d/'out'/'handoff_mp3_by_raw_oid'/'25001.mp3').exists())
        self.assertTrue((self.d/'out'/'handoff_mp3_by_raw_oid'/'25002.mp3').exists())

if __name__=='__main__':unittest.main()
