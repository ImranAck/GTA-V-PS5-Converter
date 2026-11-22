import hashlib
import json
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'motor'/'tools')]
import drop_import as d
import user_shader_library as lib
from gtavmenu_tools import drawable_contracts

class NativeDropRoutes(unittest.TestCase):
    def test_unicode_and_braces(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'voiture {é}.rpf';p.touch()
            widget=SimpleNamespace(winfo_exists=lambda:True)
            self.assertEqual(d.dispatch_paths(widget,lambda e:d.dropped_source(tk.Tcl(),e.data),[str(p)]),p)
    def test_destroyed_widget(self):
        f=Mock()
        self.assertEqual(d.dispatch_paths(SimpleNamespace(winfo_exists=lambda:False),f,['file.rpf']),'refuse_drop')
        f.assert_not_called()
    def test_native_tree_uses_backend(self):
        backend=Mock(); root=SimpleNamespace(drop_backend=backend)
        child=SimpleNamespace(_root=lambda:root,winfo_children=lambda:[])
        card=SimpleNamespace(_root=lambda:root,winfo_children=lambda:[child])
        callback=Mock();d.register_tree(card,callback)
        self.assertEqual(backend.register.call_count,2)
        backend.register.assert_any_call(child,callback)

class MaterialLibraryTests(unittest.TestCase):
    def test_merge_pdr_preserves_existing_verified_pft(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); old=root/'old';old.mkdir();new=root/'new';new.mkdir()
            pft=old/'a.pft';pdr=new/'b.pdr';pft.write_bytes(b'old');pdr.write_bytes(b'new')
            h1,h2=map(int,list(drawable_contracts.load()['shader']['mappings'])[:2])
            def read(p):return hashlib.sha256(p.read_bytes()).hexdigest(),[{'schema':{'nameHash':h1 if p==pft else h2}}]
            catalog=root/'library.json'
            with patch.object(lib,'read_materials',side_effect=read):
                lib.scan(old,catalog)
                result=lib.scan(new,catalog,merge=True)
                self.assertEqual(result['scannedPdr'],1)
                self.assertEqual(result['shaderTypes'],2)
                self.assertEqual(len(result['references']),2)
                pft.write_bytes(b'changed')
                before=catalog.read_bytes()
                with self.assertRaises(ValueError):lib.scan(new,catalog,merge=True)
                self.assertEqual(before,catalog.read_bytes())
    def test_spec_name_hash(self):
        self.assertEqual(drawable_contracts.load()['shader']['mappings'][str(0x7204a391)]['name'],'spec')

if __name__=='__main__':unittest.main()
