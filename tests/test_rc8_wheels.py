import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'motor/tools')]
import v3_engine as e
class WheelRouteTests(unittest.TestCase):
    def test_no_drawables_no_wheel_route(self):
        self.assertEqual(e._wheel_rows([(None,SimpleNamespace(name='car.yft'))]),[])
    def test_only_declared_wheel_with_drawable(self):
        models=[(None,SimpleNamespace(name='custom.ydr'))]
        xml=SimpleNamespace(name='carcols.meta')
        window=SimpleNamespace(chain='',read_member=lambda *args:b'<Wheels/>')
        from convert_pc_wheel import Wheel
        rows=[Wheel(0,'custom',None,None,.34,False,'test'),Wheel(0,'missing',None,None,.34,False,'test')]
        with patch('convert_pc_wheel.parse_wheels',return_value=rows):
            self.assertEqual([w.name for w in e._wheel_rows(models+[(window,xml)])],['custom'])
    def test_missing_pinned_reference_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(e,'cache_root',return_value=root),patch.object(e,'configured',return_value=True):
                with self.assertRaisesRegex(ValueError,'wheel_loride_01'):
                    e.convert_wheel_pack(root/'dlc.rpf','gtavmenu-wheels',root/'out')
                self.assertFalse((root/'out').exists())
    def test_wheel_zip_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pack=root/'gtavmenu-wheels';(pack/'resources').mkdir(parents=True)
            (pack/'resources'/'pack.cfg').write_text('GTAVPACK,1\n')
            out=root/'out';out.mkdir();z=e.make_zip(pack,out)
            self.assertEqual(e.list_packages(out),[(pack.name,z)])
            with self.assertRaises(ValueError):e.make_zip(pack,out)
if __name__=='__main__':unittest.main()
