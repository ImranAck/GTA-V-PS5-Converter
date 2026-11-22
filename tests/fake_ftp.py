"""Deterministic in-memory fake with real FTP directory/rename semantics."""
from __future__ import annotations
import ftplib
import posixpath

class FakeFTPServer:
    last=None
    def __init__(self):
        self.dirs={'/','/data','/data/GTAVMenu','/data/GTAVMenu/custom','/data/GTAVMenu/custom/packs'}
        self.remote={'/data/GTAVMenu/custom/packs/installed':b'gtavmenu-bmw\n'}
        self.login_args=None;self.fail_installed_commit=False;self.closed=False
        FakeFTPServer.last=self
    def connect(self,host,port,timeout):self.endpoint=(host,port)
    def login(self,u,p):self.login_args=(u,p)
    def voidcmd(self,command):return '200 OK'
    def cwd(self,p):
        if p not in self.dirs:raise ftplib.error_perm('550 Directory not found')
        return '250 OK'
    def mkd(self,p):
        if p in self.dirs:raise ftplib.error_perm('550 Already exists')
        if posixpath.dirname(p) not in self.dirs:raise ftplib.error_perm('550 Parent missing')
        self.dirs.add(p)
        return p
    def storbinary(self,cmd,fin,blocksize=8192,callback=None):
        p=cmd.split(' ',1)[1]
        if posixpath.dirname(p) not in self.dirs:raise ftplib.error_perm('550 Parent missing')
        buf=bytearray()
        while True:
            block=fin.read(blocksize)
            if not block:break
            buf.extend(block)
            if callback:callback(block)
        self.remote[p]=bytes(buf)
    def retrbinary(self,cmd,callback):
        p=cmd.split(' ',1)[1]
        if p not in self.remote:raise ftplib.error_perm('550 Not found')
        callback(self.remote[p])
    def size(self,path):
        if path not in self.remote:raise ftplib.error_perm('550 Not found')
        return len(self.remote[path])
    def rename(self,src,dst):
        if self.fail_installed_commit and src.startswith('/data/GTAVMenu/custom/packs/installed.incoming-') and dst.endswith('/installed'):
            raise ftplib.error_temp('451 simulated commit failure')
        if src in self.remote:
            if posixpath.dirname(dst) not in self.dirs:raise ftplib.error_perm('550 Parent missing')
            self.remote[dst]=self.remote.pop(src)
        elif src in self.dirs:
            if posixpath.dirname(dst) not in self.dirs:raise ftplib.error_perm('550 Parent missing')
            self.dirs={dst+x[len(src):] if x==src or x.startswith(src+'/') else x for x in self.dirs}
            self.remote={dst+x[len(src):] if x.startswith(src+'/') else x:v for x,v in self.remote.items()}
        else:raise ftplib.error_perm('550 Missing rename source')
    def quit(self):self.closed=True
    def close(self):self.closed=True
