from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PythonStartupTests(unittest.TestCase):
    def test_batch_launches_source_and_does_not_prefer_old_exe(self):
        b = (ROOT/'INICIAR-CONVERSOR.bat').read_text(encoding='utf-8')
        self.assertIn('"%RUNPY%" -u "launch.py"',b)
        self.assertNotIn('dist\\GTAV-PS5-Converter.exe',b)
        self.assertIn('PYTHONUTF8=1',b)
        self.assertIn('LOGFILE=',b)
    def test_no_rockstar_models_bundled(self):
        self.assertFalse(any(p.suffix.lower() in ('.pft','.pdr','.ptd') for p in ROOT.rglob('*') if p.is_file()))
    def test_python_launcher_sources_exist(self):
        self.assertTrue((ROOT/'launch.py').is_file())
        self.assertTrue((ROOT/'motor'/'tools'/'convert_vehicle.py').is_file())
        self.assertTrue((ROOT/'app'/'conversor_gui.py').is_file())
