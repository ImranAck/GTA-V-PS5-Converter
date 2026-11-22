import hashlib, tempfile, unittest, sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'motor/tools')]
from gtavmenu_tools.asset_textures import ResourceView,SYSTEM_BASE
from gtavmenu_tools.asset_formats import AssetError
from gtavmenu_tools.hashes import joaat
from repair_pc_texture_names import fixed,string_at
import v3_engine as engine
from progress_v4 import StageProgress
class RC7Tests(unittest.TestCase):
    def test_latin1_name_repair_preserves_byte_width(self):
        raw=b'cot\xe9 disque_n\0'; v=ResourceView(raw,len(raw),0)
        name=v.name(SYSTEM_BASE); self.assertEqual(joaat(name),0xa38d414c)
        self.assertEqual(string_at(raw,SYSTEM_BASE),(0,name))
        self.assertEqual(fixed(name),'cot__disque_n')
        self.assertEqual(len(fixed(name).encode('ascii')),len(raw)-1)
    def test_controls_and_path_separators_still_refused(self):
        for raw in [b'a\x81b\0',b'../a\0',b'a/b\0',b'a\\b\0',b'\xe9']:
            with self.subTest(raw=raw),self.assertRaises(AssetError):ResourceView(raw,len(raw),0).name(SYSTEM_BASE)
    def test_optional_reference_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'game.dat151.rel'; source.write_bytes(b'test-data'); rel='retail-audio/game.dat151.rel'
            pins={rel:(9,hashlib.sha256(b'test-data').hexdigest())}
            with patch.object(engine,'cache_root',return_value=root/'cache'),patch.object(engine,'OPTIONAL_REFERENCES',pins):
                self.assertEqual(engine.import_optional_reference(source),rel)
                dest=root/'cache/recursos/plantillas'/rel;self.assertEqual(dest.read_bytes(),b'test-data')
                source.write_bytes(b'bad-data!')
                with self.assertRaises(ValueError):engine.import_optional_reference(source)
                self.assertEqual(dest.read_bytes(),b'test-data')
    def test_dynamic_progress(self):
        seen=[];p=StageProgress(lambda n,s:seen.append((n,s)),expected_steps=88)
        for n in (1,18,87,100):p.line(f'[{n:02}] convert')
        self.assertEqual(len(seen),4);self.assertLess(seen[1][0],50);self.assertLess(seen[-1][0],100)
        p.complete();self.assertEqual(seen[-1][0],100)
if __name__=='__main__':unittest.main()
