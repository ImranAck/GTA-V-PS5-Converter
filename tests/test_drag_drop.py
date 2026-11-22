"""File-list parsing and common import route, without requiring a desktop."""
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from drop_import import dropped_source
from conversor_gui import ConverterUI
from gui_locales import translate

class DropTests(unittest.TestCase):
    def setUp(self):
        self.tcl=tk.Tcl()
        self.tmp=tempfile.TemporaryDirectory(prefix='Véhicule test ')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'dlc.RPF'
        self.path.write_bytes(b'RPF7')
    def test_supported_and_unicode(self):
        for suffix in ('.RPF','.zip','.rar','.7z','.oiv'):
            p=self.path.with_suffix(suffix);p.touch()
            self.assertEqual(dropped_source(self.tcl,'{'+str(p)+'}'),p)
    def test_multiple_empty_and_invalid(self):
        for payload in ('','{'+str(self.path)+'} {'+str(self.path)+'}','{'+self.tmp.name+'}','/missing.rpf'):
            with self.assertRaises(ValueError):dropped_source(self.tcl,payload)
        wrong=self.path.with_suffix('.exe');wrong.touch()
        with self.assertRaises(ValueError):dropped_source(self.tcl,'{'+str(wrong)+'}')
    def test_route_and_busy(self):
        ui=SimpleNamespace(root=SimpleNamespace(tk=self.tcl),working=False,_load_source=Mock())
        event=SimpleNamespace(data='{'+str(self.path)+'}')
        self.assertEqual(ConverterUI._drop_source(ui,event),'copy')
        ui._load_source.assert_called_once_with(str(self.path))
        ui.working=True
        self.assertEqual(ConverterUI._drop_source(ui,event),'refuse_drop')
        self.assertEqual(ui._load_source.call_count,1)
    def test_invalid_does_not_import(self):
        ui=SimpleNamespace(root=SimpleNamespace(tk=self.tcl),working=False,_load_source=Mock(),tr=lambda x:x)
        with patch('conversor_gui.messagebox.showwarning') as warning:
            self.assertEqual(ConverterUI._drop_source(ui,SimpleNamespace(data='no.exe')),'refuse_drop')
        warning.assert_called_once();ui._load_source.assert_not_called()
    def test_browse_uses_same_route(self):
        ui=SimpleNamespace(root=None,working=False,tr=lambda x:x,_load_source=Mock())
        with patch('conversor_gui.filedialog.askopenfilename',return_value=str(self.path)):
            ConverterUI.choose_source(ui)
        ui._load_source.assert_called_once_with(str(self.path))
    def test_translations(self):
        for language in ('en','fr'):
            self.assertNotEqual(translate('Arrastra aquí un RPF o un archivo de mod',language),'Arrastra aquí un RPF o un archivo de mod')
