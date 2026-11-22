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


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        report = None
        if len(sys.argv) > 3 and sys.argv[2] == '--report':
            report = Path(sys.argv[3]).resolve()
        if not runtime_self_test(report):
            raise SystemExit(1)
        return
    if len(sys.argv) > 1:
        worker = worker_path(sys.argv[1])
        if worker:
            sys.path[:0] = [str(worker.parent), str(BASE / 'motor'), str(BASE / 'app')]
            os.chdir(BASE / 'motor')
            sys.argv = [str(worker), *sys.argv[2:]]
            runpy.run_path(str(worker), run_name='__main__')
            return
        raise SystemExit('Unrecognized arguments; script execution refused.')
    # Source launch must not run with a different interpreter missing dependencies.
    try:
        import numpy
        from PIL import Image, ImageTk
    except ImportError as exc:
        if not getattr(sys, 'frozen', False):
            raise SystemExit(f"Missing dependency: {exc}. Run START-CONVERTER.bat or BUILD-EXE.bat.") from exc
        raise
    sys.path.insert(0, str(BASE / 'app'))
    from conversor_gui import ConverterUI
    ConverterUI().root.mainloop()


if __name__ == '__main__':
    main()
