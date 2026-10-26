"""All print QA inputs are synthetic. No A8S device or physical scan used."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
import fitz
import numpy as np
import cv2
from PIL import Image
from scripts import sonix_oid2
from scripts import oid_book_preflight as qa
from scripts import oid_book_pipeline


class BookPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.book=self.root/'book_a'
        self.book.mkdir()
        ids=['book_a:apple:word','book_a:apple:sentence']
        self.ids=ids
        doc=fitz.open();doc.new_page(width=210*72/25.4,height=297*72/25.4)
        doc.save(self.book/'artwork.pdf');doc.close()
        (self.book/'regions.json').write_text(json.dumps({'regions':[
            {'logical_id':ids[0], 'audio_index':1,'page':1,'x_mm':20,'y_mm':30,'width_mm':51,'height_mm':29},
            {'logical_id':ids[1], 'audio_index':2,'page':1,'x_mm':20,'y_mm':80,'width_mm':51,'height_mm':29}]}))
        audio=[]
        for i,key in enumerate(ids,1):
            f=self.book/'audio'/f'{i:06}.mp3'
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(b'ID3'+bytes([i])*360)
            audio.append({'logical_id':key,'audio_index':i,'path':f'audio/{i:06}.mp3','audio_ready':True})
        (self.book/'audio_manifest.json').write_text(json.dumps(audio))
        self.patterns=self.root/'assets';self.patterns.mkdir()
        self.binding=self.patterns/'bindings.json'
        self.map={'format':'ant-reader-a8s-bindings/1','book_id':'book_a',
                  'cover':self.pattern(1331,'cover.png'),
                  'regions':{ids[0]:self.pattern(1345,'word.png'),ids[1]:self.pattern(1347,'sentence.png')}}
        self.flush()

    def pattern(self,raw,name,source='Sonix OID2: pixel-exact Python experiment'):
        p=self.patterns/name
        sonix_oid2.render(raw,dpi=600,width_mm=10.16,height_mm=10.16).save(p,'PNG')
        return {'raw_oid':raw,'source_dpi':600,'image':name,'source':source,'tested_on_a8s':False}

    def flush(self): self.binding.write_text(json.dumps(self.map))

    def test_complete_book_three_assets(self):
        r=qa.analyze(self.book,self.binding)
        self.assertEqual(r['status'],'READY_FOR_EXPERIMENT_PRINT')
        self.assertEqual(r['region_count'],2)
        self.assertEqual(r['checked_code_assets'],3)
        self.assertEqual([x['raw_oid'] for x in r['regions']],[1331,1345,1347])
        self.assertTrue(all(x['optical_asset']['digital_code_status']=='EXACT_REFERENCE_MATCH' for x in r['regions']))
        self.assertEqual(r['a8s_compatible'],'UNTESTED')
        self.assertFalse(r['native_nob_generated'])
        self.assertTrue(all(x['full_tiles_in_pdf_region']>=1 for x in r['regions']))

    def test_one_pixel_corruption_is_blocked(self):
        p=self.patterns/'word.png'
        with Image.open(p) as image: im=image.copy()
        im.putpixel((5,5),(0,0,0,255))
        im.save(p)
        r=qa.analyze(self.book,self.binding)
        self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual(r['summary']['blocked_digital_ids'],[self.ids[0]])
        self.assertGreater(r['regions'][1]['optical_asset']['pixel_alpha_mismatches'],0)

    def test_wrong_raw_oid_is_blocked(self):
        self.map['regions'][self.ids[0]]['raw_oid']=1400
        self.flush()
        self.assertEqual(qa.analyze(self.book,self.binding)['status'],'BLOCKED')

    def test_external_codec_not_falsely_certified(self):
        self.map['regions'][self.ids[0]]['source']='Vendor supplied external OID art'
        self.flush()
        r=qa.analyze(self.book,self.binding)
        self.assertEqual(r['status'],'INCOMPLETE')
        self.assertEqual(r['summary']['external_codec_unchecked_ids'],[self.ids[0]])

    def test_missing_audio_is_reported(self):
        (self.book/'audio'/'000001.mp3').unlink()
        r=qa.analyze(self.book,self.binding)
        self.assertEqual(r['status'],'INCOMPLETE')
        self.assertEqual(r['summary']['missing_audio_ids'],[self.ids[0]])

    def test_geometry_too_small_prevents_release(self):
        regs=json.loads((self.book/'regions.json').read_text())
        regs['regions'][0]['height_mm']=5
        (self.book/'regions.json').write_text(json.dumps(regs))
        with self.assertRaisesRegex(ValueError,'No full OID tile'):
            qa.analyze(self.book,self.binding)

    def test_scans_must_have_known_ids_and_safe_paths(self):
        path=self.root/'scans.json'
        path.write_text(json.dumps({'format':qa.SCAN_SCHEMA,'book_id':'book_a',
                                    'capture_kind':'physical_scan','regions':{'unknown':{'image':'x.png','scan_dpi':600}}}))
        with self.assertRaisesRegex(ValueError,'Unexpected scan'):
            qa.analyze(self.book,self.binding,scans=path)
        path.write_text(json.dumps({'format':qa.SCAN_SCHEMA,'book_id':'book_a',
                                    'capture_kind':'physical_scan','regions':{self.ids[0]:{'image':'../x.png','scan_dpi':600}}}))
        with self.assertRaisesRegex(ValueError,'parent-traversal'):
            qa.analyze(self.book,self.binding,scans=path)

    def test_one_prealigned_synthetic_scan(self):
        pat=self.patterns/'word.png'
        with Image.open(pat) as im:
            data=255-np.array(im.getchannel('A'))
        scan=self.root/'crop.png';cv2.imwrite(str(scan),data)
        manifest=self.root/'scans.json'
        manifest.write_text(json.dumps({'format':qa.SCAN_SCHEMA,'book_id':'book_a',
                                        'capture_kind':'synthetic','regions':{self.ids[0]:{'image':'crop.png','scan_dpi':600}}}))
        r=qa.analyze(self.book,self.binding,scans=manifest)
        self.assertEqual(r['status'],'INCOMPLETE') # cover and sentence not scanned
        self.assertEqual(r['regions'][1]['scan_qa']['status'],'GEOMETRY_DIGITAL_MATCH')
        self.assertEqual(r['capture_kind'],'synthetic')
        self.assertEqual(r['a8s_compatible'],'UNTESTED')

    def test_assembly_audit_and_pdf_hash(self):
        import book_assembly as asm
        out=self.root/'assembled'
        asm.compose(self.book,self.binding,out)
        r=qa.analyze(self.book,self.binding,assembly_audit=out/'audit.json')
        self.assertEqual(r['assembly_check']['status'],'MATCHED_AUDIT_AND_PDF_HASH')
        with (out/'EXPERIMENTAL_print_book.pdf').open('ab') as f:f.write(b'bad')
        r=qa.analyze(self.book,self.binding,assembly_audit=out/'audit.json')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual(r['assembly_check']['status'],'MISMATCH')

    def test_save_csv_and_no_overwrite(self):
        report=qa.analyze(self.book,self.binding)
        out=self.root/'qa.json';csvpath=self.root/'qa.csv'
        qa.save(report,out,csvpath)
        self.assertEqual(json.loads(out.read_text())['status'],'READY_FOR_EXPERIMENT_PRINT')
        with csvpath.open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[1]['digital_code_status'],'EXACT_REFERENCE_MATCH')
        with self.assertRaises(FileExistsError):qa.save(report,out,csvpath)

    def test_build_one_command_end_to_end(self):
        out=self.root/'full_build'
        r=oid_book_pipeline.build(self.book,self.binding,out)
        self.assertEqual(r['status'],'READY_FOR_EXPERIMENT_PRINT')
        self.assertTrue((out/'preflight.json').exists())
        self.assertTrue((out/'preflight.csv').exists())
        self.assertTrue((out/'EXPERIMENTAL_print_book.pdf').exists())
        self.assertTrue((out/'vendor_handoff_NOT_PLAYABLE.zip').exists())
        self.assertEqual(json.loads((out/'preflight.json').read_text())['assembly_check']['status'],'MATCHED_AUDIT_AND_PDF_HASH')

    def test_build_refuses_invalid_oid_before_writing_pdf(self):
        self.map['regions'][self.ids[0]]['raw_oid']=1400
        self.flush()
        out=self.root/'dont_create'
        with self.assertRaisesRegex(ValueError,'Preflight blocked'):
            oid_book_pipeline.build(self.book,self.binding,out)
        self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
