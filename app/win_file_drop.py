"""Native Windows Shell file-drop target for Tk, no external DLL dependency.
All native calls are on the Tk GUI thread. Subclass callback lifetime follows
its Tk root. HDROP handles are consumed exactly once; callback queues paths.
"""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
from collections import deque
from drop_import import dispatch_paths

WM_DROPFILES = 0x0233
WM_NCDESTROY = 0x0082


class WindowsFileDrop:
    def __init__(self, root):
        self.root = root
        self.shell = C.WinDLL('shell32', use_last_error=True)
        self.common = C.WinDLL('comctl32', use_last_error=True)
        self.user = C.WinDLL('user32', use_last_error=True)
        self.subproc_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, C.c_size_t, C.c_ssize_t, C.c_size_t, C.c_size_t)
        self.proc = self.subproc_type(self._window_proc)
        self.subid = 1
        self.targets = {}
        self.pending = deque()
        self.shell.DragAcceptFiles.argtypes = [W.HWND, W.BOOL]
        self.shell.DragAcceptFiles.restype = None
        self.shell.DragQueryFileW.argtypes = [W.HANDLE, W.UINT, W.LPWSTR, W.UINT]
        self.shell.DragQueryFileW.restype = W.UINT
        self.shell.DragFinish.argtypes = [W.HANDLE]
        self.shell.DragFinish.restype = None
        self.common.SetWindowSubclass.argtypes = [W.HWND, self.subproc_type, C.c_size_t, C.c_size_t]
        self.common.SetWindowSubclass.restype = W.BOOL
        self.common.RemoveWindowSubclass.argtypes = [W.HWND, self.subproc_type, C.c_size_t]
        self.common.RemoveWindowSubclass.restype = W.BOOL
        self.common.DefSubclassProc.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
        self.common.DefSubclassProc.restype = C.c_ssize_t
        self.user.GetParent.argtypes = [W.HWND]
        self.user.GetParent.restype = W.HWND
        self.root.after(50, self._poll)

    def register(self, widget, callback):
        self.root.update_idletasks()
        hwnd = int(widget.winfo_id())
        if hwnd not in self.targets:
            if not self.common.SetWindowSubclass(hwnd, self.proc, self.subid, 0):
                raise OSError('SetWindowSubclass failed: '+str(C.get_last_error()))
            self.targets[hwnd] = (widget, callback)
            self.shell.DragAcceptFiles(hwnd, True)
        else:
            self.targets[hwnd] = (widget, callback)
        # Tk's toplevel has a separate native wrapper window. Register that
        # wrapper as a fallback for Explorer drops over themed child controls.
        top = int(self.root.winfo_id())
        wrapper = self.user.GetParent(top)
        if wrapper and wrapper not in self.targets:
            if self.common.SetWindowSubclass(wrapper, self.proc, self.subid, 0):
                self.targets[wrapper] = (widget, callback)
                self.shell.DragAcceptFiles(wrapper, True)
        elif wrapper in self.targets:
            self.targets[wrapper] = (widget, callback)

    def _window_proc(self, hwnd, message, wparam, lparam, subclass, ref):
        if message == WM_DROPFILES:
            try:
                target = self.targets.get(hwnd)
                if target is not None:
                    n = self.shell.DragQueryFileW(wparam, 0xffffffff, None, 0)
                    # Import supports exactly one item. Do not allocate for a
                    # huge selection, and still report the normal UI warning.
                    paths = [] if n == 0 else ['',''] if n != 1 else []
                    if n == 1:
                        size = self.shell.DragQueryFileW(wparam, 0, None, 0)
                        if 0 < size <= 32767:
                            buf = C.create_unicode_buffer(size+1)
                            if self.shell.DragQueryFileW(wparam, 0, buf, size+1) == size:
                                paths.append(buf.value)
                    self.pending.append((*target, paths))
            except Exception as exc:
                self.root.drop_diagnostic = 'WM_DROPFILES: '+repr(exc)
            finally:
                self.shell.DragFinish(wparam)
            return 0
        if message == WM_NCDESTROY:
            self.targets.pop(hwnd, None)
            self.common.RemoveWindowSubclass(hwnd, self.proc, self.subid)
        return self.common.DefSubclassProc(hwnd, message, wparam, lparam)

    def drain(self):
        while self.pending:
            dispatch_paths(*self.pending.popleft())

    def _poll(self):
        try:
            self.drain()
        finally:
            if self.root.winfo_exists():
                self.root.after(50, self._poll)


def test_delivery(backend, widget, path):
    """Exercise genuine Win32 HDROP message delivery (not Explorer UI)."""
    import struct
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.GlobalAlloc.argtypes=[W.UINT,C.c_size_t]
    kernel.GlobalAlloc.restype=W.HANDLE
    kernel.GlobalLock.argtypes=[W.HANDLE]
    kernel.GlobalLock.restype=C.c_void_p
    kernel.GlobalUnlock.argtypes=[W.HANDLE]
    kernel.GlobalUnlock.restype=W.BOOL
    kernel.GlobalFree.argtypes=[W.HANDLE]
    kernel.GlobalFree.restype=W.HANDLE
    backend.user.SendMessageW.argtypes=[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t]
    backend.user.SendMessageW.restype=C.c_ssize_t
    payload=struct.pack('<IiiII',20,0,0,0,1)+(str(path)+'\0\0').encode('utf-16-le')
    h=kernel.GlobalAlloc(0x42,len(payload))  # GMEM_MOVEABLE | GMEM_ZEROINIT
    if not h:raise OSError('GlobalAlloc failed')
    addr=kernel.GlobalLock(h)
    if not addr:
        kernel.GlobalFree(h)
        raise OSError('GlobalLock failed')
    C.memmove(addr,payload,len(payload))
    kernel.GlobalUnlock(h)
    # The receiver takes ownership and calls DragFinish, even on failure.
    backend.user.SendMessageW(int(widget.winfo_id()),WM_DROPFILES,h,0)
    backend.drain()
