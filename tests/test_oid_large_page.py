"""Synthetic/tile-memory tests. These are NOT paper or A8S hardware tests."""
import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
import tifffile

from scripts import oid_large_page as big
from scripts import sonix_oid2 as oid


def synthetic(width=2450, height=2100):
    page=np.full((height,width),255,np.uint8)
    for x,y,raw in ((100,120,1331),(1020,520,1345),(1710,1280,1347)):
        area=255-np.asarray(oid.render(raw,dpi=1200,width_mm=13,height_mm=13).getchannel('A'))
        page[y:y+area.shape[0],x:x+area.shape[1]]=area
    cv2.putText(page,'APPLE', (740,380),cv2.FONT_HERSHEY_SIMPLEX,1.8,0,4)
    return page


class LargePageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_starts_cover_page_and_dont_exceed_bounds(self):
        self.assertEqual(big.starts(800,1600,720),[0])
        self.assertEqual(big.starts(2500,1600,720),[0,880,900])
        self.assertEqual(big.starts(4200,1600,720),[0,880,1760,2600])
        for width in (100,400,1600,1601,2500,8800):
            ss=big.starts(width,1600,720)
            self.assertEqual(ss[0],0)
            self.assertEqual(ss[-1],max(0,width-1600))
            self.assertLessEqual(max(np.diff(ss)) if len(ss)>1 else 0,880)

    def test_merge_same_code_and_distinct_codes(self):
        def candidate(code,bbox,index):
            return {'bbox_px':bbox,'raw_oid':code,'status':'DECODED_RESEARCH_ONLY',
                    'decode_details':{'tiles_majority':20},'source_tile_index':index}
        src=[candidate(1331,[100,100,400,400],0),candidate(1331,[260,150,400,400],1),
             candidate(1345,[280,180,400,400],2)]
        merged,diag=big.merge_regions(src)
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[0]['raw_oid'],1331)
        self.assertEqual(merged[0]['bbox_px'],[100,100,560,450])
        self.assertEqual(merged[0]['observations'],2)
        self.assertEqual(len(diag['conflicting_overlaps']),2)

    def test_merge_ignores_unverified_and_reports_truncation(self):
        entries=[{'bbox_px':[i*800,0,500,500],'raw_oid':1300+i,'status':'DECODED_RESEARCH_ONLY',
                  'source_tile_index':i} for i in range(3)]
        entries.append({'bbox_px':[0,0,500,500],'raw_oid':None,'status':'INSUFFICIENT_EVIDENCE'})
        r,stats=big.merge_regions(entries,max_regions=2)
        self.assertEqual(len(r),2)
        self.assertTrue(stats['truncated'])
        self.assertEqual(stats['raw_valid_candidates'],3)

    def test_tiff_is_read_only_memory_map(self):
        a=synthetic(2450,2100)
        f=self.root/'page.tif'
        tifffile.imwrite(f,a,compression=None,photometric='minisblack')
        before=f.stat().st_size
        with big.open_page(f) as (data,mode):
            self.assertEqual(mode,'TIFF_READ_ONLY_MEMMAP')
            self.assertIsInstance(data,np.memmap)
            self.assertFalse(data.flags.writeable)
            self.assertEqual(big.gray_tile(data,300,300,80,60).shape,(60,80))
        self.assertEqual(f.stat().st_size,before)

    def test_compressed_tiff_rejected(self):
        f=self.root/'compressed.tif'
        tifffile.imwrite(f,np.full((350,500),255,np.uint8),compression='deflate')
        with self.assertRaisesRegex(ValueError,'uncompressed contiguous TIFF'):
            with big.open_page(f):pass

    def test_reject_giant_png_by_header_before_decode(self):
        f=self.root/'huge.png'
        from PIL import Image
        Image.new('1',(6500,5000),1).save(f)
        with self.assertRaisesRegex(ValueError,'30 MP'):
            with big.open_page(f):pass

    def test_small_png_fallback(self):
        f=self.root/'small.png'
        cv2.imwrite(str(f),np.full((400,500),255,np.uint8))
        with big.open_page(f) as (data,mode):
            self.assertEqual(mode,'IN_MEMORY_IMAGE')
            self.assertEqual(data.shape,(400,500))

    def test_1200dpi_a4_memory_map_and_small_preview(self):
        # Real A4-sized dimensions (9921 x 14031); sparse 8-bit TIFF fixture.
        # This proves opening/previewing need not materialize 139 MP at once.
        f=self.root/'a4_1200dpi.tif'
        mapped=tifffile.memmap(f,shape=(14031,9921),dtype='uint8',photometric='minisblack')
        mapped[70:80,90:100]=255
        mapped.flush()
        del mapped
        with big.open_page(f) as (page,mode):
            self.assertEqual(mode,'TIFF_READ_ONLY_MEMMAP')
            self.assertEqual(page.shape,(14031,9921))
            self.assertEqual(page[70,90],255)
            self.assertEqual(big.gray_tile(page,80,60,40,40).shape,(40,40))
            preview=big.preview_page(page,{'regions':[]})
            self.assertLessEqual(max(preview.shape[:2]),1800)

    def test_rgb_tiff_tile_keeps_channel_order(self):
        f=self.root/'color.tif'
        rgb=np.zeros((500,700,3),np.uint8)
        rgb[:,:,:]=[255,0,0]
        tifffile.imwrite(f,rgb,compression=None,photometric='rgb')
        with big.open_page(f) as (page,mode):
            patch=big.gray_tile(page,100,120,80,70)
            self.assertEqual(patch.shape,(70,80))
            self.assertGreater(int(patch.mean()),70)
            self.assertLess(int(patch.mean()),80)

    def test_invalid_controls(self):
        pg=np.full((700,700),255,np.uint8)
        for kwargs in ({'tile_size':400,'overlap':350},{'tile_size':2400},
                       {'overlap':159},{'max_regions':True},{'per_tile_regions':13},
                       {'approx_pitch_px':3}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                big.analyze_page(pg,**kwargs)

    def test_high_resolution_tiled_end_to_end_and_preview(self):
        source=self.root/'synthetic.tif'
        tifffile.imwrite(source,synthetic(),compression=None,photometric='minisblack')
        report=self.root/'report.json'; preview=self.root/'preview.png'
        big.main(['--image',str(source),'--out',str(report),'--preview',str(preview),
                  '--tile-size','1600','--overlap','720'])
        data=json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(data['reader_mode'],'TIFF_READ_ONLY_MEMMAP')
        self.assertEqual(data['decoded_count'],3)
        self.assertEqual([a['raw_oid'] for a in data['regions']],[1331,1345,1347])
        self.assertGreater(data['candidate_count'],3)
        self.assertTrue(any(a['observations']>1 for a in data['regions']))
        self.assertTrue(preview.is_file())
        self.assertLess(max(cv2.imread(str(preview)).shape[:2]),1801)
        with self.assertRaises(SystemExit):
            big.main(['--image',str(source),'--out',str(report)])


if __name__=='__main__':unittest.main()
