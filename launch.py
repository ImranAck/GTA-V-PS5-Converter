"""Launcher and frozen subprocess dispatcher for the GTA V PS5 converter.

Scripts inside motor/tools are bundled as data and executed with runpy, so
PyInstaller must explicitly package their standard-library dependencies.
"""
from __future__ import annotations

import os
import runpy
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def worker_path(argument: str) -> Path | None:
    try:
        source = Path(argument).resolve()
        tools = (BASE / 'motor' / 'tools').resolve()
        if source.is_file() and source.suffix.lower() == '.py' and source.is_relative_to(tools):
            return source
    except (ValueError, OSError):
        pass
    return None


def runtime_self_test(report_file: Path | None = None) -> bool:
    """Exercise real subprocess paths, not just the GUI launch.

    This catches missing bundled modules such as xml.dom.minidom immediately
    after the Windows EXE is built, before the user selects a vehicle.
    """
    lines = []
    failures = []
    try:
        import xml.dom.minidom
        import xml.etree.ElementTree
        import xml.parsers.expat
        import numpy
        from PIL import Image, ImageTk
        lines.append('IMPORTS=PASS xml.dom.minidom xml.etree.ElementTree xml.parsers.expat numpy PIL')
        sys.path[:0] = [str(BASE / 'app'), str(BASE / 'motor')]
        from progress_v4 import StageProgress
        assert StageProgress(lambda x, y: None).percent == 0
        assert (BASE / 'motor' / 'tools' / 'convert_vehicle.py').is_file()
    except Exception as exc:
        failures.append('IMPORTS=FAIL: ' + repr(exc))
        lines.extend(traceback.format_exc().splitlines()[-8:])

    if sys.platform == 'win32':
        try:
            import tkinter as tk
            from drop_import import create_root, register_tree
            root, enabled = create_root()
            try:
                root.withdraw()
                if not enabled:
                    raise RuntimeError('Native file drop unavailable: '+root.drop_diagnostic)
                frame = tk.Frame(root)
                frame.pack()
                received=[]
                register_tree(frame, lambda event: received.append(root.tk.splitlist(event.data)))
                if root.drop_backend is not None:
                    from win_file_drop import test_delivery
                    import tempfile
                    with tempfile.TemporaryDirectory(prefix='GTA V test ') as td:
                        source=Path(td)/'véhicule {1}.rpf'
                        source.write_bytes(b'RPF7')
                        test_delivery(root.drop_backend,frame,source)
                        if received != [(str(source),)]:
                            raise RuntimeError('Native HDROP path delivery failed: '+repr(received))
                    lines.append('WINDOWS_DRAG_DROP=PASS (WM_DROPFILES delivery, Unicode and braces)')
                else:
                    lines.append('WINDOWS_DRAG_DROP=PASS (TkDND registration; Explorer delivery not tested)')
            finally:
                root.destroy()
        except Exception as exc:
            failures.append('WINDOWS_DRAG_DROP=FAIL: ' + repr(exc))
    else:
        lines.append('WINDOWS_DRAG_DROP=NOT_RUN (requires Windows)')

    tools = (
        'convert_vehicle.py',
        'import_pc_assets.py',
        'validate_runtime_pack.py',
        'prepare_vehicle_layouts.py',
        'prepare_carcols.py',
        'repair_pc_auto.py',
        'repair_pc_pose_precision.py',
        'convert_pc_ytd_writer.py',
        'build_runtime_pack.py',
        'inspect_pc_vehicle_materials.py',
        'shader_preflight.py',
        'user_shader_library.py',
        'convert_pc_wheel.py',
        'finish_tuning_batch.py',
    )
    for tool in tools:
        filepath = BASE / 'motor' / 'tools' / tool
        if not filepath.is_file():
            failures.append(tool + ': missing from package')
            continue
        # Onedir frozen executable dispatches child scripts using this EXE.
        # In the source checkout, Python dispatches through launch.py.
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, str(filepath), '--help']
        else:
            cmd = [sys.executable, str(BASE / 'launch.py'), str(filepath), '--help']
        try:
            p = subprocess.run(
                cmd, cwd=str(BASE / 'motor'),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors='replace', timeout=90,
            )
            if p.returncode == 0:
                lines.append(tool + '=PASS (exit code 0)')
            else:
                failures.append(f'{tool}=FAIL rc={p.returncode}')
                lines.extend(p.stdout.splitlines()[-10:])
        except Exception as exc:
            failures.append(tool + '=FAIL: ' + repr(exc))
    lines.extend(failures)
    lines.append('V4_FROZEN_WORKER_TEST=' + ('FAIL' if failures else 'PASS'))
    if report_file:
        try:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        except Exception:
            return False
    else:
        for line in lines:
            print(line)
    return not failures


def _startup_log_path() -> Path:
    """Logs are created only for GUI startup, never for conversion workers."""
    appdata = os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP')
    base = Path(appdata) if appdata else Path.home()
    return base / 'GTAV-CarMods-PS5' / 'logs' / 'inicio-exe-portatil.log'


def _startup_log(message: str) -> Path | None:
    """Best-effort logging; a locked/unwritable user profile must not block startup."""
    paths = (_startup_log_path(), Path(os.environ.get('TEMP') or '.') / 'gtav-converter-startup.log')
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as output:
                output.write(datetime.now(timezone.utc).isoformat(timespec='seconds') + ' ' + message + '\n')
            return path
        except (OSError, ValueError):
            continue
    return None


def _notify_startup_error(message: str, log_path: Path | None) -> None:
    """Show errors when PyInstaller uses the silent windowed bootloader."""
    text = ('GTA V PS5 Converter could not start.\n\n'
            + message[:600] + '\n\n'
            + ('Diagnostic log: ' + str(log_path) if log_path else 'No diagnostic log could be written.'))
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, 'GTA V PS5 Converter', 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def _gui_startup(smoke_report: Path | None = None) -> None:
    log_path = _startup_log('GUI START; frozen=' + str(bool(getattr(sys, 'frozen', False)))
                            + '; python=' + sys.version.split()[0]
                            + '; runtime=' + str(BASE))
    ui = None
    try:
        import numpy
        from PIL import Image, ImageTk
        _startup_log('GUI IMPORTS OK; numpy=' + numpy.__version__)
        sys.path.insert(0, str(BASE / 'app'))
        from conversor_gui import ConverterUI
        ui = ConverterUI()
        _startup_log('GUI CREATED')

        def on_callback_error(exc_type, exc, tb):
            details = ''.join(traceback.format_exception(exc_type, exc, tb))
            path = _startup_log('TK CALLBACK ERROR\n' + details)
            _notify_startup_error(str(exc), path)

        ui.root.report_callback_exception = on_callback_error
        if smoke_report is not None:
            ui.root.update_idletasks()
            ui.root.update()
            # A real Tk main window must be initialized, not merely imported.
            ui.root.destroy()
            ui = None
            smoke_report.parent.mkdir(parents=True, exist_ok=True)
            smoke_report.write_text('GUI_STARTUP=PASS\n', encoding='utf-8')
            _startup_log('GUI SMOKE PASS')
            return
        ui.root.mainloop()
        _startup_log('GUI EXIT NORMAL')
    except Exception as exc:
        details = traceback.format_exc()
        path = _startup_log('GUI STARTUP FAILED\n' + details) or log_path
        if smoke_report is not None:
            try:
                smoke_report.parent.mkdir(parents=True, exist_ok=True)
                smoke_report.write_text('GUI_STARTUP=FAIL\n' + details, encoding='utf-8')
            except OSError:
                pass
        _notify_startup_error(repr(exc), path)
        raise SystemExit(1) from exc
    finally:
        if ui is not None and smoke_report is not None:
            try:
                ui.root.destroy()
            except Exception:
                pass


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        report = None
        if len(sys.argv) > 3 and sys.argv[2] == '--report':
            report = Path(sys.argv[3]).resolve()
        if not runtime_self_test(report):
            raise SystemExit(1)
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--smoke-ui':
        if len(sys.argv) != 4 or sys.argv[2] != '--report':
            raise SystemExit('Usage: --smoke-ui --report output.txt')
        _gui_startup(Path(sys.argv[3]).resolve())
        return
    if len(sys.argv) > 1:
        worker = worker_path(sys.argv[1])
        if worker:
            sys.path[:0] = [str(worker.parent), str(BASE / 'motor'), str(BASE / 'app')]
            os.chdir(BASE / 'motor')
            sys.argv = [str(worker), *sys.argv[2:]]
            runpy.run_path(str(worker), run_name='__main__')
            return
        raise SystemExit('Unknown argument; script execution refused.')
    _gui_startup()


if __name__ == '__main__':
    main()
