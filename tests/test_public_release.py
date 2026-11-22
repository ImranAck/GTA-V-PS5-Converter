"""Safety and public usability regressions; no real PS5 FTP writes."""
from pathlib import Path
from unittest.mock import patch
import io
import json
import sys
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from fake_ftp import FakeFTPServer
import ftp_manager,public_release


def zip_pack(path:Path,ident='gtavmenu-test',body=b'RPF8'*512):
    with zipfile.ZipFile(path,'w') as z:
        base=f'GTAVMenu/custom/packs/{ident}/resources/'
        z.writestr(base+'pack.cfg','GTAVPACK,1\n')
        z.writestr(base+'vehicle.rpf',body)
        z.writestr(base+'vehicle_handling.meta','<xml/>')
    return path

class SafetyTests(unittest.TestCase):
    def test_private_network_only(self):
        for x in ('8.8.8.8','127.0.0.1','169.254.1.10','0.0.0.0','224.0.0.1','example.org'):
            with self.subTest(x=x),self.assertRaises(ValueError):ftp_manager.validate_host(x,1337)
        self.assertEqual(ftp_manager.validate_host('192.168.1.52',1337),'192.168.1.52')

    def test_zip_path_traversal_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'evil.zip'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('GTAVMenu/custom/packs/gtavmenu-a/resources/pack.cfg','abc')
                z.writestr('GTAVMenu/custom/packs/gtavmenu-a/resources/../../bad','evil')
            with self.assertRaises(ValueError):ftp_manager.validate_local_pack(p)
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('GTAVMenu/custom/packs/gtavmenu-a/resources/pack.cfg','abc')
                z.writestr('GTAVMenu/custom/packs/gtavmenu-b/resources/pack.cfg','abc')
            with self.assertRaises(ValueError):ftp_manager.validate_local_pack(p)

    def test_preflight_readonly_and_unknown_capacity(self):
        fake=FakeFTPServer()
        info=ftp_manager.preflight('192.168.0.20',1337,factory=lambda:fake)
        self.assertEqual(info['installed_entries'],1)
        self.assertIsNone(info['remote_free_bytes'])
        self.assertEqual(len(fake.remote),1)

    def test_install_update_then_uninstall_is_reversible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);zip_path=zip_pack(root/'car.zip')
            fake=FakeFTPServer()
            ftp_manager.install(zip_path,'192.168.0.77',1337,backup_dir=root,factory=lambda:fake)
            self.assertIn(b'gtavmenu-test',fake.remote[ftp_manager.INSTALLED])
            self.assertIn(ftp_manager.ROOT+'/gtavmenu-test',fake.dirs)
            old=fake.remote[ftp_manager.ROOT+'/gtavmenu-test/resources/vehicle.rpf']
            zip_pack(zip_path,body=b'UPDATED'*500)
            ftp_manager.install(zip_path,'192.168.0.77',1337,backup_dir=root,factory=lambda:fake)
            self.assertNotEqual(old,fake.remote[ftp_manager.ROOT+'/gtavmenu-test/resources/vehicle.rpf'])
            self.assertTrue(any('/.previous-gtavmenu-test-' in x for x in fake.dirs))
            ftp_manager.uninstall('gtavmenu-test','192.168.0.77',1337,root,factory=lambda:fake)
            self.assertNotIn(b'gtavmenu-test',fake.remote[ftp_manager.INSTALLED])
            self.assertNotIn(ftp_manager.ROOT+'/gtavmenu-test',fake.dirs)
            self.assertTrue(any('/.uninstalled-gtavmenu-test-' in x for x in fake.dirs))
            self.assertTrue(any(root.glob('*installed-backup*')))

    def test_installed_commit_failure_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);car=zip_pack(root/'car.zip',body=b'UPDATED'*800)
            fake=FakeFTPServer()
            # Existing pack not registered yet: installation changes installed.
            original=ftp_manager.ROOT+'/gtavmenu-test'
            fake.dirs.add(original)
            fake.dirs.add(original+'/resources')
            fake.remote[original+'/resources/vehicle.rpf']=b'OLD'*500
            first=fake.remote[original+'/resources/vehicle.rpf']
            installed=fake.remote[ftp_manager.INSTALLED]
            fake.fail_installed_commit=True
            with self.assertRaises(RuntimeError):
                ftp_manager.install(car,'192.168.1.2',1337,backup_dir=root,factory=lambda:fake)
            self.assertEqual(fake.remote[ftp_manager.INSTALLED],installed)
            self.assertEqual(fake.remote[original+'/resources/vehicle.rpf'],first)

    def test_missing_index_is_normal_after_last_uninstall(self):
        fake=FakeFTPServer();fake.remote.pop(ftp_manager.INSTALLED)
        info=ftp_manager.preflight('192.168.0.50',1337,factory=lambda:fake)
        self.assertEqual(info['installed_entries'],0)
        self.assertNotIn(ftp_manager.INSTALLED,fake.remote)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            ftp_manager.install(zip_pack(root/'car.zip'),'192.168.0.50',1337,backup_dir=root,factory=lambda:fake)
            self.assertEqual(fake.remote[ftp_manager.INSTALLED],b'gtavmenu-test\n')

    def test_privacy_redacts_paths_ips_emails(self):
        line=r'ERROR: C:\Users\ExampleUser\Documents\Car\dlc.rpf ip=192.168.1.42 foo@example.org'
        clean=public_release.redact(line)
        for private in ('ExampleUser','Documents','192.168.1.42','foo@example.org'):
            self.assertNotIn(private,clean)
        self.assertIn('ERROR:',clean)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'support.json'
            public_release.export_support([line,'PERF_STAGE step=12 seconds=2.1'],out)
            obj=json.loads(out.read_text())
            self.assertNotIn('192.168.',out.read_text())
            self.assertEqual(len(obj['messages']),2)

    def test_static_qa_never_claims_gameplay_pass(self):
        with tempfile.TemporaryDirectory() as d:
            path=zip_pack(Path(d)/'car.zip')
            qa=public_release.inspect_pack(path)
            self.assertEqual(qa['pack'],'gtavmenu-test')
            self.assertTrue(qa['static_checks']['resource_rpf'])
            self.assertTrue(all('PENDING' in v for v in qa['gameplay_checks'].values()))
            self.assertFalse(qa['static_checks']['carcols_meta'])

    def test_duration_history_requires_three_samples(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            public_release.record_duration(p,45)
            public_release.record_duration(p,60)
            self.assertIsNone(public_release.median_duration(p))
            public_release.record_duration(p,50)
            self.assertEqual(public_release.median_duration(p),50)

if __name__=='__main__':unittest.main()
