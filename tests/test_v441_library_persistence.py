"""Regression test: re-importing retail templates must NEVER delete donor library.

Uses tiny synthetic local files; does not redistribute GTA V resources.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import v3_engine as engine

class LibraryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.m=patch.object(engine,'cache_root',return_value=self.root)
        self.m.start();self.addCleanup(self.m.stop)
        self.layout=self.root/'original.meta'
        self.layout.write_bytes(b'fixed test fixture')
        self.temp=self.root/'fake-templates'
        self.temp.mkdir()
        self.baseline=b'example verified corpus'
        self.expected={'corpus/tornado6.pft':hashlib.sha256(self.baseline).hexdigest()}
        self.m2=patch.object(engine,'EXPECTED',self.expected)
        self.m2.start();self.addCleanup(self.m2.stop)
        self.m3=patch.object(engine,'LAYOUT_BYTES',len(self.layout.read_bytes()))
        self.m3.start();self.addCleanup(self.m3.stop)
        self.m4=patch.object(engine,'LAYOUT_SHA',engine.digest_file(self.layout))
        self.m4.start();self.addCleanup(self.m4.stop)
        def copy_templates(src,target):
            p=target/'corpus/tornado6.pft'
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(self.baseline)
            return target
        self.m5=patch.object(engine.core,'copy_templates',side_effect=copy_templates)
        self.m5.start();self.addCleanup(self.m5.stop)
        self.donor=self.root/'user-pft'/'real-owned.pft'
        self.donor.parent.mkdir(parents=True)
        self.donor.write_bytes(b'my local native resource')
        self.document={
            'format':'gtav-ps5-user-shader-library-v1',
            'target':'PPSA04263-01.010.002',
            'shaderTypes':37,
            'references':[{'path':str(self.donor),'sha256':engine.digest_file(self.donor),'shaders':[123]}]
        }
    def save(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(self.document),encoding='utf-8')
    def test_legacy_index_is_migrated_before_reimport(self):
        legacy=self.root/'recursos/shaders-extra.json'
        self.save(legacy)
        engine.import_resources(self.temp,self.layout)
        stable=self.root/'biblioteca-materiales/shaders-extra.json'
        self.assertTrue(stable.is_file())
        self.assertEqual(json.loads(stable.read_text()),self.document)
        self.assertFalse(legacy.exists())
        engine.import_resources(self.temp,self.layout)
        self.assertEqual(json.loads(stable.read_text()),self.document)
    def test_new_library_survives_reimport(self):
        stable=self.root/'biblioteca-materiales/shaders-extra.json'
        self.save(stable)
        engine.import_resources(self.temp,self.layout)
        engine.import_resources(self.temp,self.layout)
        self.assertEqual(json.loads(stable.read_text()),self.document)
    def test_missing_donor_library_not_silently_active(self):
        self.assertFalse(engine.library_catalog().exists())
    def test_corrupted_legacy_does_not_get_silently_rewritten(self):
        stable=self.root/'biblioteca-materiales/shaders-extra.json'
        self.save(stable)
        bad=self.root/'recursos/shaders-extra.json'
        bad.parent.mkdir(parents=True)
        bad.write_text('corrupt legacy',encoding='utf-8')
        self.assertEqual(json.loads(engine.library_catalog().read_text()),self.document)

if __name__=='__main__':unittest.main()
