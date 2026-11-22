"""Enumerate stdlib imports from data-executed conversion scripts.

PyInstaller sees the GUI imports but does not see imports of tools invoked
by runpy.run_path at runtime. We must add these explicitly.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

SOURCE_DIRS = ('app', 'motor')
EXTERNAL = {'PIL', 'numpy'}
REQUIRED = {
    'xml.dom',
    'xml.dom.minidom',
    'xml.parsers',
    'xml.parsers.expat',
    'xml.etree',
    'xml.etree.ElementTree',
    'pyexpat',
}


def available_module(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ValueError, ModuleNotFoundError, ImportError, AttributeError):
        return False


def collect_source_imports(root: Path) -> list[str]:
    wanted: set[str] = set(REQUIRED)
    files = [root / 'launch.py']
    for folder in SOURCE_DIRS:
        files.extend((root / folder).rglob('*.py'))
    for file in files:
        # Fail the build on invalid source; never silently omit worker imports.
        tree = ast.parse(file.read_text(encoding='utf-8-sig'), filename=str(file))
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                candidates = [node.module] + [node.module + '.' + alias.name for alias in node.names if alias.name != '*']
            for module in candidates:
                root_name = module.split('.')[0]
                if root_name in sys.stdlib_module_names or root_name in EXTERNAL:
                    if available_module(module):
                        wanted.add(module)
    absent = [x for x in REQUIRED if not available_module(x)]
    if absent:
        raise RuntimeError('Faltan bibliotecas estándar necesarias en el Python de compilación: ' + ', '.join(sorted(absent)))
    return sorted(wanted)


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    for name in collect_source_imports(root):
        print(name)
