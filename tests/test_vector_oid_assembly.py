import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import fitz
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
import ant_reader
from scripts.vector_oid_assembly import assemble, SCHEMA, MM


class VectorOIDTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        b=self.root/'mybook.json'
        b.write_text(json.dumps({'book_id':'vector_test', 'title':'Vectored codes', 'items':[
            {'key':'apple','english':'Apple','chinese':'苹果','sentence':'This is an apple.'}]}),encoding='utf8')
        ant_reader.prepare(SimpleNamespace(book=str(b),out=str(self.root/'prepped'),tts='none'))
        self.book=self.root/'prepped'/'books'/'vector_test'
        self.codes=self.root/'dots.pdf'
        with fitz.open() as doc:
            for i in range(3):
                page=doc.new_page(width=30*MM,height=30*MM)
                for x in range(7):
                    for y in range(7):
                        # synthetic vector geometry only; NOT valid OID
                        c=(6+x*2.5)*MM;d=(6+y*2.5)*MM
                        page.draw_circle(fitz.Point(c,d),0.08*MM,color=None,fill=(0,0,0))
                page.insert_text((1*MM,29*MM),'outside crop',fontsize=6)
            doc.save(self.codes)
        names=[x['logical_id'] for x in ant_reader.read_json(self.book/'regions.json')['regions']]
        self.names=names
        self.spec=self.root/'bind.json'
        def entry(n):
            return {'raw_oid':50000+n,'source':'SYNTHETIC DEBUG VECTOR ONLY','pdf':'dots.pdf','page':n+1,
                    'rect_mm':[5,5,19,19]}
        self.binding={'format':SCHEMA,'book_id':'vector_test','cover':entry(0),
                      'regions':{names[0]:entry(1),names[1]:entry(2)}}
        self.save()
    def save(self):self.spec.write_text(json.dumps(self.binding),encoding='utf8')
    def assemble(self,**kwargs):return assemble(self.book,self.spec,self.root/'generated',allow_missing_audio=True,**kwargs)

    def test_vector_book_without_bitmap_images(self):
        result=self.assemble()
        self.assertEqual(result['status'],'UNVERIFIED_A8S')
        self.assertEqual(len(result['regions']),2)
        self.assertFalse(result['entrance']['source_has_raster'])
        self.assertGreater(result['entrance']['vector_drawings_in_crop'],30)
        with fitz.open(self.root/'generated'/'EXPERIMENTAL_vector_book.pdf') as doc:
            self.assertEqual(len(doc),2)
            self.assertGreater(len(doc[1].get_drawings()),100)
            self.assertEqual(len(doc[0].get_images()),0)
            self.assertEqual(len(doc[1].get_images()),0)
        self.assertTrue((self.root/'generated'/'vendor_handoff.csv').is_file())

    def test_duplicate_oid_rejected(self):
        self.binding['regions'][self.names[0]]['raw_oid']=50000
        self.save()
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.assemble()

    def test_missing_audio_is_failure_by_default(self):
        with self.assertRaisesRegex(ValueError,'Missing audio'):
            assemble(self.book,self.spec,self.root/'generated')

    def test_text_over_crop_rejected(self):
        self.binding['cover']['rect_mm']=[0,19,19,10]
        self.save()
        with self.assertRaisesRegex(ValueError,'Text intersects'):
            self.assemble()

    def test_source_traversal_rejected(self):
        self.binding['cover']['pdf']='../secret.pdf'
        self.save()
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            self.assemble()

    def test_pdf_raster_source_requires_explicit_opt_in(self):
        from PIL import Image
        import io
        pic=Image.new('RGB',(30,30),'black')
        by=io.BytesIO();pic.save(by,format='PNG')
        with fitz.open() as doc:
            p=doc.new_page(width=30*MM,height=30*MM)
            p.insert_image(fitz.Rect(0,0,30*MM,30*MM),stream=by.getvalue())
            doc.save(self.root/'raster.pdf')
        self.binding['cover']['pdf']='raster.pdf';self.binding['cover']['page']=1
        self.save()
        with self.assertRaisesRegex(ValueError,'raster images'):
            self.assemble()


if __name__=='__main__': unittest.main()