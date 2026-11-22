"""Build and source-code tests must not depend on the Windows ANSI codepage."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WindowsEncodingTests(unittest.TestCase):
    def test_main_ui_source_decodes_explicit_utf8_not_cp1252(self):
        src = ROOT/'app/conversor_gui.py'
        self.assertIn('self.include_tuning.set(bool(count))', src.read_text(encoding='utf-8'))
        # Prove this was the problematic input, not a test that passes on any file.
        with self.assertRaises(UnicodeDecodeError):
            src.read_text(encoding='cp1252')

    def test_build_environment_is_utf8_and_inherited(self):
        bat = (ROOT/'BUILD-EXE.bat').read_text(encoding='utf-8')
        self.assertIn('set "PYTHONUTF8=1"', bat)
        self.assertIn('set "PYTHONIOENCODING=utf-8"', bat)
        self.assertLess(bat.index('set "PYTHONUTF8=1"'), bat.index('python -m unittest discover'))

    def test_metadata_regression_uses_explicit_encoding(self):
        source = (ROOT/'tests/test_rc4_metadata.py').read_text(encoding='utf-8')
        self.assertIn("(ROOT/'app/conversor_gui.py').read_text(encoding='utf-8')", source)

if __name__ == '__main__':
    unittest.main()
