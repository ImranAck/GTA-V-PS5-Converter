"""Regression for xml.dom missing from PyInstaller's dynamically-run scripts."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_imports import collect_source_imports


class FrozenImportsTests(unittest.TestCase):
    def test_include_dynamic_xml_dependencies(self):
        modules = set(collect_source_imports(ROOT))
        self.assertTrue({'xml.dom.minidom', 'xml.etree.ElementTree', 'xml.parsers.expat'} <= modules)

    def test_convert_worker_imports_as_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'result.txt'
            outcome = subprocess.run(
                [sys.executable, str(ROOT / 'launch.py'), '--self-test', '--report', str(report)],
                cwd=ROOT, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn('V4_FROZEN_WORKER_TEST=PASS', report.read_text('utf-8'))
            self.assertIn('convert_vehicle.py=PASS', report.read_text('utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
