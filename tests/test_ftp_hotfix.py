from pathlib import Path
import tempfile, unittest, ftplib
from fake_ftp import FakeFTPServer
from test_public_release import zip_pack, ftp_manager as m

class HotfixTests(unittest.TestCase):
    def test_remove_active_only_selected(self):
        for active,expected in [(b'gtavmenu-test\n',None),(b'gtavmenu-test\ngtavmenu-bmw\n',b'gtavmenu-bmw\n')]:
            with self.subTest(active=active),tempfile.TemporaryDirectory() as d:
                p=Path(d); f=FakeFTPServer()
                m.install(zip_pack(p/'car.zip'),'192.168.1.2',1337,backup_dir=p,factory=lambda:f)
                f.remote[m.ACTIVE]=active
                m.uninstall('gtavmenu-test','192.168.1.2',1337,p,factory=lambda:f)
                self.assertEqual(f.remote.get(m.ACTIVE),expected)
                self.assertEqual(f.remote[m.INSTALLED],b'gtavmenu-bmw\n')
    def test_active_rollback_on_installed_commit_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); f=FakeFTPServer()
            m.install(zip_pack(p/'car.zip'),'192.168.1.2',1337,backup_dir=p,factory=lambda:f)
            original=f.remote[m.INSTALLED]; f.remote[m.ACTIVE]=b'gtavmenu-test\n';f.fail_installed_commit=True
            with self.assertRaises(RuntimeError):m.uninstall('gtavmenu-test','192.168.1.2',1337,p,factory=lambda:f)
            self.assertEqual(f.remote[m.ACTIVE],b'gtavmenu-test\n')
            self.assertEqual(f.remote[m.INSTALLED],original)
            self.assertIn(m.ROOT+'/gtavmenu-test/resources/pack.cfg',f.remote)
    def test_readback_corruption_rolls_back(self):
        class Corrupt(FakeFTPServer):
            def rename(self,src,dst):
                super().rename(src,dst)
                if src.startswith(m.INSTALLED+'.incoming-') and dst==m.INSTALLED:self.remote[dst]=b'bad\n'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=Corrupt();old=f.remote[m.INSTALLED]
            with self.assertRaises(RuntimeError):m.install(zip_pack(p/'car.zip'),'192.168.1.2',1337,backup_dir=p,factory=lambda:f)
            self.assertEqual(f.remote[m.INSTALLED],old)
            self.assertNotIn(m.ROOT+'/gtavmenu-test',f.dirs)
    def test_normalize_line_endings(self):
        self.assertEqual(m._with_id(b'\xef\xbb\xbfgtavmenu-bmw\r\n','gtavmenu-test',True),b'gtavmenu-bmw\ngtavmenu-test\n')
    def test_access_denial_not_missing(self):
        class Denied(FakeFTPServer):
            def retrbinary(self,cmd,callback):
                if cmd=='RETR '+m.INSTALLED:raise ftplib.error_perm('550 Permission denied')
                super().retrbinary(cmd,callback)
        f=Denied();old=f.remote.copy()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with self.assertRaises(ftplib.error_perm):m.install(zip_pack(p/'car.zip'),'192.168.1.2',1337,backup_dir=p,factory=lambda:f)
        self.assertEqual(f.remote,old)
