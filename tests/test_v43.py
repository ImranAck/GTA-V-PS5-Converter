"""Structural tests for opt-in reusable native shader reference library.
No proprietary PS5 game data is needed or redistributed by these tests.
"""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
from contextlib import contextmanager

TOOLS=Path(__file__).resolve().parents[1]/'motor'/'tools'
sys.path.insert(0,str(TOOLS))
import user_shader_library as u

@contextmanager
def temporary_env(name,value):
    old=os.environ.get(name)
    try:
        if value is None:os.environ.pop(name,None)
        else:os.environ[name]=str(value)
        yield
    finally:
        if old is None:os.environ.pop(name,None)
        else:os.environ[name]=old

class ShaderLibraryTests(unittest.TestCase):
    def test_identity_and_reference_scanning(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/'car.pft';p.write_bytes(b'RSC7 fake fixture')
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            from gtavmenu_tools import drawable_contracts
            known_hash=int(next(iter(drawable_contracts.load()['shader']['mappings'])))
            rows=[{'schema':{'nameHash':known_hash}}]
            with patch.object(u,'read_materials',return_value=(h,rows)) as mock:
                doc=u.scan(root,root/'library.json')
                self.assertEqual(doc['scannedPft'],1)
                self.assertEqual(doc['rejected'],0)
                self.assertEqual(doc['newShaderTypes'],1)
                self.assertEqual(len(doc['references']),1)
                self.assertEqual(doc['references'][0]['sha256'],h)
                mock.assert_called_once()
            with patch.object(u,'read_materials',return_value=(h,rows)):
                again=u.scan(root,root/'library.json',baseline={known_hash})
                self.assertEqual(again['newShaderTypes'],0)
                self.assertEqual(again['references'],[])
    def test_sha_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'source.pft';p.write_bytes(b'fixture')
            lib=root/'library.json'
            lib.write_text(json.dumps({'format':u.FORMAT,'target':'PPSA04263-01.010.002',
                'references':[{'path':str(p),'sha256':'0'*64,'shaders':[123]}]}))
            with temporary_env('GTAV_USER_SHADER_LIBRARY',lib):
                with patch.object(u,'read_materials',return_value=('a'*64,[{'schema':{'nameHash':123}}])):
                    with self.assertRaisesRegex(ValueError,'modificada'):
                        u.references_from_environment()
    def test_duplicate_and_wrong_target_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'index.json'
            p.write_text(json.dumps({'format':u.FORMAT,'target':'otra version','references':[]}))
            with temporary_env('GTAV_USER_SHADER_LIBRARY',p):
                with self.assertRaisesRegex(ValueError,'otra versión'):
                    u.references_from_environment()
    def test_disabled_when_no_user_library(self):
        with temporary_env('GTAV_USER_SHADER_LIBRARY',None):
            self.assertEqual(u.references_from_environment(),[])
    def test_no_altered_original_corpus(self):
        source=(TOOLS/'convert_pc_vehicle.py').read_text(encoding='utf-8')
        self.assertIn('vehicle_templates.verified_input',source)
        self.assertIn('REFERENCE_CACHES',source)
        self.assertIn('user_shader_library.references_from_environment()',source)
        self.assertIn('supplementary.add(identity)',source)

if __name__=='__main__':unittest.main()
