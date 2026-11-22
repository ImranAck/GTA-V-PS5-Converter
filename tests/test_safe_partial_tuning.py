"""Tests for optional-part recovery. The base fragment remains strict.

These unit tests do not claim an untested mod loads on physical PS5.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'motor' / 'tools'))
sys.path.insert(0, str(ROOT / 'app'))
import convert_vehicle as cv
import prepare_carcols
import v3_engine
import ftp_manager


class OptionalRecoveryTests(unittest.TestCase):
    def test_fast_path_no_extra_calls(self):
        names = ['door.yft', 'bumper.yft', 'roof.yft']
        calls, skipped = [], []
        def attempt(group):
            calls.append(group[:])
        self.assertEqual(cv.salvage_optional_groups(names, attempt, lambda *row: skipped.append(row)), names)
        self.assertEqual(calls, [names])
        self.assertEqual(skipped, [])

    def test_isolate_only_one_bad_part(self):
        names = [f'part-{i}.yft' for i in range(12)]
        calls, skipped = [], []
        def attempt(group):
            calls.append(group[:])
            if 'part-7.yft' in group:
                raise cv.ConvertError('unsupported independent fragment')
        kept = cv.salvage_optional_groups(names, attempt, lambda *row: skipped.append(row))
        self.assertEqual(kept, [m for m in names if m != 'part-7.yft'])
        self.assertEqual(skipped, [('part-7.yft', 'unsupported independent fragment')])
        self.assertLess(len(calls), len(names))

    def test_all_parts_incompatible_still_no_fake_success(self):
        names=['bad1.yft','bad2.yft']
        skipped=[]
        def attempt(group):
            raise cv.ConvertError('unsupported model')
        self.assertEqual(cv.salvage_optional_groups(names, attempt, lambda *row: skipped.append(row)), [])
        self.assertEqual([m for m, _ in skipped], names)

    def test_unexpected_errors_are_not_silenced(self):
        with self.assertRaises(OSError):
            cv.salvage_optional_groups(['a.yft'], lambda group: (_ for _ in ()).throw(OSError('disk full')), lambda *_: None)

    def test_public_warning_has_model_and_no_private_path(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            cv.omitted_tuning('x64/mods.rpf!/bumper_02.yft', r'bad at C:\\Users\\someone\\secret: duplicate bone')
        self.assertIn('WARNING_TUNING_EXCLUDED: bumper_02.yft:', out.getvalue())
        self.assertIn('huesos', out.getvalue())
        self.assertNotIn('secret', out.getvalue())

    def test_carcols_does_not_offer_skipped_part(self):
        carcols='''<CVehicleModelInfoVarGlobal><Kits><Item><kitName>example_modkit</kitName>
        <id value="1"/><visibleMods>
        <Item><modelName>good_part</modelName><type>VMT_BUMPER_F</type><linkedModels><Item>bad_part</Item></linkedModels></Item>
        <Item><modelName>bad_part</modelName><type>VMT_BUMPER_R</type></Item>
        </visibleMods><linkMods><Item><modelName>bad_part</modelName></Item></linkMods></Item></Kits>
        <Lights/><Sirens/></CVehicleModelInfoVarGlobal>'''
        variations='<CVehicleModelInfoVariation><variationData/></CVehicleModelInfoVariation>'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'c.meta').write_text(carcols)
            (p/'v.meta').write_text(variations)
            args=['--carcols',str(p/'c.meta'),'--variations',str(p/'v.meta'),
                  '--kit-id','4609','--light-id','224','--prefix','GMTEST_',
                  '--ship-model','good_part','--out-carcols',str(p/'new-carcols.meta'),
                  '--out-variations',str(p/'new-variations.meta')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(prepare_carcols.main(args),0)
            result=(p/'new-carcols.meta').read_text()
            self.assertIn('<modelName>good_part</modelName>',result)
            self.assertNotIn('<modelName>bad_part</modelName>',result)
            self.assertNotIn('<Item>bad_part</Item>',result)

    def test_zip_contains_a_visible_omissions_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            resources=p/'pack'/'resources'
            resources.mkdir(parents=True)
            (resources/'pack.cfg').write_text('GTAVPACK,1\npack\tpack\n')
            (resources/'car.rpf').write_bytes(b'RPF8test')
            warning='WARNING_TUNING_EXCLUDED: bumper_02.yft: geometría de la pieza incompatible'
            z=v3_engine.make_zip(resources.parent,p,warnings=[warning])
            with zipfile.ZipFile(z) as pkg:
                self.assertEqual(pkg.testzip(),None)
                report=pkg.read('AVISO-CONVERSION-PARCIAL.txt').decode()
                self.assertIn('bumper_02.yft',report)
                self.assertIn('NO se han incluido',report)
            info = ftp_manager.validate_local_pack(z)
            self.assertEqual(info.ident, 'pack')
            self.assertEqual({m[0] for m in info.members}, {'pack.cfg', 'car.rpf'})
            z2=v3_engine.make_zip(resources.parent,p,alternate=True,warnings=[])
            with zipfile.ZipFile(z2) as pkg:
                self.assertNotIn('AVISO-CONVERSION-PARCIAL.txt',pkg.namelist())

if __name__ == '__main__':
    unittest.main()
