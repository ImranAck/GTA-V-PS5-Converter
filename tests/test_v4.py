from __future__ import annotations
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from fake_ftp import FakeFTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import progress_v4 as pg
import v3_engine as eng


class InMemoryFTP:
    last=None
    def __init__(self):
        self.remote={'/data/GTAVMenu/custom/packs/installed':b'gtavmenu-bmw\n'}
        self.login_args=None
        InMemoryFTP.last=self
    def connect(self,host,port,timeout):self.endpoint=(host,port)
    def login(self,u,p):self.login_args=(u,p)
    def mkd(self,p):pass
    def cwd(self,p):pass
    def storbinary(self,command,file,blocksize=128*1024,callback=None):
        p=command.split(' ',1)[1];data=b''
        while True:
            block=file.read(blocksize)
            if not block:break
            data+=block
            if callback:callback(block)
        self.remote[p]=data
    def retrbinary(self,command,callback):
        p=command.split(' ',1)[1]
        if p not in self.remote:raise __import__('ftplib').error_perm('550 Not found')
        callback(self.remote[p])
    def rename(self,a,b):
        self.remote[b]=self.remote.pop(a)
    def quit(self):pass

class Tests(unittest.TestCase):
    def test_progress_step_boundaries(self):
        points=[];tracker=pg.StageProgress(lambda pct,label:points.append((pct,label)))
        tracker.line('[01] stage retail templates from source')
        tracker.line('[06] convert (references stage, multi-page)')
        tracker.line('[12] textures')
        tracker.line('[18] validate target pack')
        tracker.complete()
        self.assertEqual([x[0] for x in points],[0,27,83,99,100])
        self.assertEqual(pg.ftp_percent(49,100),49)
    def test_lan_ftp_backup_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath=Path(tmp)/'mod.zip'
            with zipfile.ZipFile(zpath,'w') as z:
                z.writestr('GTAVMenu/custom/packs/gtavmenu-rsq8m/resources/pack.cfg','test')
                z.writestr('GTAVMenu/custom/packs/gtavmenu-rsq8m/resources/model.rpf',b'RPF8'+b'X'*1000)
            progress=[]
            with patch.object(eng.ftplib,'FTP',FakeFTPServer):
                backup=eng.ftp_install(zpath,'192.168.0.77',1337,progress=lambda n,t:progress.append((n,t)))
            remote=FakeFTPServer.last
            self.assertEqual(remote.login_args,('anonymous',''))
            installed=remote.remote['/data/GTAVMenu/custom/packs/installed'].decode()
            self.assertEqual(installed,'gtavmenu-bmw\ngtavmenu-rsq8m\n')
            self.assertEqual(backup.read_text(),'gtavmenu-bmw\n')
            self.assertEqual(progress[-1][0],progress[-1][1])
    def test_refuse_external_ftp(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath=Path(tmp)/'mod.zip'
            with zipfile.ZipFile(zpath,'w') as z:z.writestr('GTAVMenu/custom/packs/gtavmenu-a/resources/pack.cfg','a')
            with self.assertRaises(ValueError):eng.ftp_install(zpath,'8.8.8.8')
    def test_no_embedded_retail_assets(self):
        # Distribution must not contain the 15 copyrighted retail templates.
        self.assertFalse(any(p.is_file() for p in (ROOT/'motor'/'build'/'assets').rglob('*')))
        self.assertFalse(any(p.name=='vehiclelayouts.meta' for p in ROOT.rglob('vehiclelayouts.meta')))

if __name__=='__main__':unittest.main(verbosity=2)
