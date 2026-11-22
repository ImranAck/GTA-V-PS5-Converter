"""Smoke mode and startup logging regressions; no external display is needed."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launch


class PortableStartupTests(unittest.TestCase):
    def test_startup_log_contains_timestamp_and_unicode(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'coche de pruéba' / 'inicio.log'
            with patch.object(launch, '_startup_log_path', return_value=log):
                self.assertEqual(launch._startup_log('Ready ✓'), log)
            self.assertIn('Ready ✓', log.read_text(encoding='utf-8'))

    def test_single_exe_builder_does_full_ui_smoke_from_unrelated_cwd(self):
        builder = (ROOT / 'BUILD-EXE.bat').read_text(encoding='utf-8')
        self.assertIn('--smoke-ui --report', builder)
        self.assertIn('pushd "%TEMP%"', builder)
        self.assertIn('GUI_STARTUP=PASS', builder)
        self.assertIn('py -3.12', builder)

    def test_smoke_mode_does_not_accept_invalid_arguments(self):
        with patch.object(sys, 'argv', ['launch.py', '--smoke-ui']):
            with self.assertRaises(SystemExit) as context:
                launch.main()
        self.assertIn('--smoke-ui --report', str(context.exception))

    def test_non_gui_workers_do_not_write_gui_log(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'start.log'
            with patch.object(launch, '_startup_log_path', return_value=log):
                self.assertIsNone(launch.worker_path(str(Path(td) / 'not_a_worker.py')))
                self.assertFalse(log.exists())

    def test_launcher_catches_gui_init_errors_and_reports(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'startup.log'
            report = Path(td) / 'smoke.txt'
            with patch.object(launch, '_startup_log_path', return_value=log), \
                 patch.object(launch, '_notify_startup_error') as notify, \
                 patch.dict(sys.modules, {'numpy': None}):
                with self.assertRaises(SystemExit) as exc:
                    launch._gui_startup(report)
            self.assertEqual(exc.exception.code, 1)
            self.assertIn('GUI_STARTUP=FAIL', report.read_text('utf-8'))
            self.assertIn('GUI STARTUP FAILED', log.read_text('utf-8'))
            notify.assert_called_once()

if __name__ == '__main__':
    unittest.main()
