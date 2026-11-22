"""General regression guards for fast lossless-to-old-output BC3 authoring and invalid light ids."""
import sys,unittest,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'motor/tools'))
import bc_encode
from prepare_carcols import point


def reference_bc3(rgba):
    blocks=bc_encode._blocks(rgba.astype(np.uint8))
    out=bytearray()
    for block in blocks:
        out += bc_encode._bc4_block(block[:,3])+bc_encode._color_block(block[:,:3].astype(np.float32))
    return bytes(out)

class GeneralFixes(unittest.TestCase):
    def test_bc3_exact_across_different_images(self):
        rng=np.random.default_rng(2702)
        samples=[]
        for h,w in [(1,1),(5,9),(64,64),(70,134),(128,256),(256,256)]:
            samples.append(rng.integers(0,256,(h,w,4),dtype=np.uint8))
        gray=np.arange(256,dtype=np.uint8)
        gradient=np.empty((128,256,4),dtype=np.uint8)
        gradient[:,:,:3]=gray[None,:,None]
        gradient[:,:,3]=np.arange(128,dtype=np.uint8)[:,None]
        samples += [gradient,np.full((32,32,4),(33,33,33,255),dtype=np.uint8),np.zeros((31,31,4),dtype=np.uint8)]
        for k,image in enumerate(samples):
            with self.subTest(i=k):
                self.assertEqual(bc_encode.encode('BC3',image),reference_bc3(image))

    def test_bad_unbound_light_outside_runtime_id_falls_back_with_note(self):
        notes=[]
        result=point('<lightSettings value="998" />', 'light', {}, None, None, notes)
        self.assertEqual(result,'<lightSettings value="0" />')
        self.assertIn('appearance may differ',notes[0])

    def test_in_range_unbound_light_still_refused(self):
        with self.assertRaises(SystemExit):
            point('<lightSettings value="240" />','light',{},None,None,[])

    def test_metadata_precedes_expensive_textures(self):
        source=(ROOT/'motor/tools/convert_vehicle.py').read_text(encoding='utf-8')
        self.assertLess(source.index('data, labels = metas(plan, args, fixture, stage, part_names)'),
                        source.index('plan.run("textures", command'))

    def test_census_requires_stock_default(self):
        with self.assertRaises(SystemExit):
            point('<lightSettings value="998" />','light',{}, {'lights':{10},'sirens':{0},'kits':set()},None,[])

    def test_light_id_998_remapped_when_mod_has_real_item(self):
        notes=[]
        self.assertEqual(point('<lightSettings value="998" />','light',{998:224},None,224,notes),'<lightSettings value="224" />')

if __name__=='__main__':unittest.main()
