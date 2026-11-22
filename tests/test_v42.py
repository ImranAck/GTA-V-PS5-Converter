"""Tests of v4.2; no real PS5 connection or writes to user game data."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from fake_ftp import FakeFTPServer

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
sys.path.insert(0,str(BASE/'motor'/'tools'))
import v3_engine as eng
import convert_pc_ytd_writer as tw
import shader_preflight


class OfflineTests(unittest.TestCase):
    def test_import_original_audi(self):
        source=BASE/'tests'/'fixtures'/'optional-audi'/'dlc.rpf'
        if not source.exists():self.skipTest('No original Audi present on this host')
        m=eng.scan_rpf(source)
        self.assertIn('rsq8m',[x['model'] for x in m])

    def test_unsupported_shader_early(self):
        report=BASE/'tests'/'fixtures'/'optional-audi'/'materials.json'
        templates=BASE/'tests'/'fixtures'/'optional-audi'/'templates'
        if not report.exists():self.skipTest('No original Audi evidence on this host')
        self.assertEqual(shader_preflight.check(report,templates),[0x60d16e80])
        sample={'resources':[{'shaders':[{'nameHash':'0x1d5f09ce'}]}]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.json';path.write_text(json.dumps(sample))
            self.assertEqual(shader_preflight.check(path,templates),[])

    def test_texture_parallel_identical(self):
        templates=BASE/'tests'/'fixtures'/'optional-audi'/'templates'
        if not templates.exists():self.skipTest('Templates unavailable')
        source={'textures':[{'name':f'pixel{i}','format':'BC1','width':256,'height':256,'mipLevels':1,'mips':[bytes([i])*32768]} for i in range(6)]}
        result=[]
        for n in ['1','2','4']:
            with patch.dict(os.environ,{'GTAV_TEXTURE_WORKERS':n}):
                data,meta=tw.convert(source,templates)
            result.append((hashlib.sha256(data).hexdigest(),meta))
        self.assertEqual(result[0],result[1]);self.assertEqual(result[0],result[2])

    def make_demo_zip(self, root:Path, ident='gtavmenu-test', data=b'resource'):
        path=root/f'{ident}-PARA-PS5.zip'
        with zipfile.ZipFile(path,'w') as z:
            name=f'GTAVMenu/custom/packs/{ident}/resources/'
            z.writestr(name+'pack.cfg',f'id={ident}\n')
            z.writestr(name+'gmtest.rpf',data)
        return path

    def test_ftp_dropdown_detects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.make_demo_zip(root,'gtavmenu-a')
            self.make_demo_zip(root,'gtavmenu-b')
            (root/'other.txt').write_text('ignored')
            names=[x[0] for x in eng.list_packages(root)]
            self.assertEqual(set(names),{'gtavmenu-a','gtavmenu-b'})

    def test_ftp_anonymous_preserves_existing_installed(self):
        class FakeFTP:
            saved={'/data/GTAVMenu/custom/packs/installed':b'old-bmw\n'}
            login_args=None
            def __init__(self):pass
            def connect(self,ip,port,timeout):self.address=(ip,port)
            def login(self,*args):FakeFTP.login_args=args
            def mkd(self,path):pass
            def cwd(self,path):pass
            def storbinary(self,cmd,fin,blocksize=8192,callback=None):
                path=cmd.split(' ',1)[1];buf=bytearray()
                while True:
                    data=fin.read(blocksize)
                    if not data:break
                    buf.extend(data)
                    if callback:callback(data)
                FakeFTP.saved[path]=bytes(buf)
            def retrbinary(self,cmd,cb):
                cb(FakeFTP.saved[cmd.split(' ',1)[1]])
            def rename(self,a,b):
                FakeFTP.saved[b]=FakeFTP.saved.pop(a)
            def quit(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            z=self.make_demo_zip(Path(tmp),'gtavmenu-new')
            with patch.object(eng.ftplib,'FTP',FakeFTPServer):
                backup=eng.ftp_install(z,'192.168.1.42',1337)
            self.assertEqual(FakeFTPServer.last.login_args,('anonymous',''))
            self.assertEqual(backup.read_bytes(),b'gtavmenu-bmw\n')
            self.assertEqual(FakeFTPServer.last.remote['/data/GTAVMenu/custom/packs/installed'],b'gtavmenu-bmw\ngtavmenu-new\n')

    def test_ftp_external_ip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.make_demo_zip(Path(tmp))
            with self.assertRaises(ValueError):eng.ftp_install(path,'1.1.1.1',21)

    def test_engine_quality_uses_user_setting(self):
        import conversor_v2_core as core
        cmd=core.make_command(Path('car.rpf'),'rsq8m','gtavmenu-rsq8m','Audi RSQ8M',Path('templates'),Path('vehiclelayouts.meta'),Path('out'),512)
        self.assertIn('--max-texture-size',cmd)
        self.assertEqual(cmd[cmd.index('--max-texture-size')+1],'512')

    def test_credits(self):
        content=(BASE/'app/conversor_gui.py').read_text(encoding='utf-8')
        self.assertIn('Community edition',content)
        self.assertNotIn('x.com/',content)

if __name__=='__main__':unittest.main(verbosity=2)
