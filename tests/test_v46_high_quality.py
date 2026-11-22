"""High-quality writer cap, non-degrading UI and opt-in quality policy."""
import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/'app',ROOT/'motor'/'tools'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
from gtavmenu_tools import ps5_texture_writer as w
from gtavmenu_tools.asset_formats import Limits
from gtavmenu_tools.texture_names import SOURCE_NAME_POLICY
from app import v3_engine as e
from app import conversor_v2_core as c

class HighQualityTests(unittest.TestCase):
    def test_large_ps5_dictionary_plannable(self):
        # Five independent 16-MiB allocations exceed the old 64-MiB limit.
        rows=[w.Ps5TextureStorage('large'+str(i),16<<20,65536) for i in range(5)]
        plan=w.plan_ps5_texture_dictionary(rows, Limits(max_total_bytes=1<<31),
            name_policy=SOURCE_NAME_POLICY,graphics_page_bytes=16<<20)
        self.assertGreater(plan['payloadBytes'],64<<20)
        self.assertLessEqual(plan['payloadBytes'],128<<20)
        self.assertEqual(plan['issues'],[])
    def test_original_quality_skips_trim_switch(self):
        argv=c.make_command(Path('mod.rpf'),'teslax','gtavmenu-teslax','Tesla X',Path('tpl'),Path('layout'),Path('packs'),0)
        self.assertNotIn('--max-texture-size',argv)
    def test_high_quality_defaults(self):
        import inspect
        p=inspect.signature(e.convert).parameters
        self.assertEqual(p['texture_size'].default,0)
        self.assertEqual(p['auto_texture_fit'].default,False)
        source=(ROOT/'app'/'conversor_gui.py').read_text(encoding='utf8')
        self.assertIn("self.auto_texture_fit=tk.BooleanVar(value=False)",source)
        self.assertIn("self.quality=tk.StringVar(value=self.tr('Original · sin reducción'))",source)
        self.assertNotIn('Ajustar automáticamente si PS5 exige',source)
if __name__=='__main__':unittest.main()
