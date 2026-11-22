# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile build with full dependency analysis of data-executed tools.

Run: python -m PyInstaller --noconfirm --clean GTAV-PS5-Converter.spec
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()
import sys
sys.path.insert(0, str(ROOT))
from build_imports import collect_source_imports

stdlib_imports = collect_source_imports(ROOT)
np_datas, np_binaries, np_imports = collect_all('numpy')
pil_datas, pil_binaries, pil_imports = collect_all('PIL')
# Bundle the build PC's own 7-Zip console and its DLL; end users need no 7-Zip install.
# The Windows builder checks availability and the distribution license first.
seven_zip = ROOT / 'vendor' / '7zip'
seven_zip_datas = [(str(seven_zip / n), 'tools/7zip') for n in ('7z.exe','7z.dll','License.txt')]
for path, _ in seven_zip_datas:
    if not Path(path).is_file():
        raise SystemExit('Falta el componente 7-Zip requerido para el EXE portátil: '+path)

# Native Windows drop uses system DLLs through ctypes. TkDND is not required.
dnd_datas, dnd_binaries, dnd_imports = [], [], []
xml_imports = collect_submodules('xml')
# All standard-library imports in motor/tools and motor/gtavmenu_tools are
# reachable only via runpy.run_path, so they must be explicit hidden imports.
hiddenimports = sorted(set(stdlib_imports) | set(np_imports) | set(pil_imports) | set(dnd_imports) | set(xml_imports) | {'win_file_drop', 'drop_import'})

analysis = Analysis(
    [str(ROOT / 'launch.py')],
    pathex=[str(ROOT / 'app'), str(ROOT / 'motor'), str(ROOT / 'motor' / 'tools')],
    binaries=np_binaries + pil_binaries + dnd_binaries,
    datas=[
        (str(ROOT / 'app'), 'app'),
        (str(ROOT / 'assets'), 'assets'),
        (str(ROOT / 'motor'), 'motor'),
    ] + np_datas + pil_datas + dnd_datas + seven_zip_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    exclude_binaries=False,
    name='GTAV-PS5-Converter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / 'assets' / 'app.ico'),
)
