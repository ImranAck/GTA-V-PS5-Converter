"""File drops: Windows Shell backend, optional TkDND on other platforms."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk

SUPPORTED = frozenset({'.rpf', '.zip', '.rar', '.7z', '.oiv'})


def create_root():
    root = tk.Tk()
    root.drop_backend = None
    root.drop_diagnostic = ''
    if sys.platform == 'win32':
        try:
            from win_file_drop import WindowsFileDrop
            root.drop_backend = WindowsFileDrop(root)
            root.drop_diagnostic = 'Windows Shell / WM_DROPFILES'
            return root, True
        except Exception as exc:
            root.drop_diagnostic = 'Windows Shell: ' + repr(exc)
    try:
        from tkinterdnd2 import TkinterDnD
        TkinterDnD._require(root)
        root.drop_diagnostic += ' TkDND disponible'
        return root, True
    except (ImportError, RuntimeError, tk.TclError, OSError) as exc:
        root.drop_diagnostic += ' TkDND: ' + repr(exc)
        return root, False


def dropped_source(tcl, data):
    paths = tcl.splitlist(data)
    if len(paths) != 1:
        raise ValueError('single')
    path = Path(paths[0])
    if path.suffix.lower() not in SUPPORTED or not path.is_file():
        raise ValueError('invalid')
    return path


def register_tree(widget, callback):
    """Register the import card and child controls; never accept shell commands."""
    root = widget._root()
    backend = getattr(root, 'drop_backend', None)
    if backend is not None:
        backend.register(widget, callback)
    else:
        from tkinterdnd2 import DND_FILES
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind('<<Drop>>', callback)
    for child in widget.winfo_children():
        register_tree(child, callback)


def dispatch_paths(widget, callback, paths):
    # Typed tuple is accepted directly by Tcl.splitlist, preserving Unicode,
    # literal braces and spaces without manual quote or backslash handling.
    if widget.winfo_exists():
        return callback(SimpleNamespace(data=tuple(paths)))
    return 'refuse_drop'
