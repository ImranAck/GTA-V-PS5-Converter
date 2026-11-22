"""Conservative local-only FTP pack management.

No remote recursive deletion. Every installation and removal is reversible by
remote renames. The PS5 server must already expose the expected GTAVMenu root.
Standard anonymous FTP is unencrypted; do not use across public networks.
"""
from __future__ import annotations

import ftplib
import io
import ipaddress
import posixpath
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT='/data/GTAVMenu/custom/packs'
INSTALLED=ROOT+'/installed'
ACTIVE=ROOT+'/active'
PACK_ID=re.compile(r'[a-z0-9][a-z0-9_-]{1,63}\Z')
MAX_FILES=5000
MAX_BYTES=8_000_000_000


@dataclass(frozen=True)
class LocalPack:
    ident: str
    members: tuple[tuple[str,str,int], ...]
    total_bytes: int


def validate_local_pack(path:Path)->LocalPack:
    """Do not trust user-supplied ZIP paths or special file entries."""
    if not path.is_file(): raise ValueError('No existe el ZIP seleccionado.')
    with zipfile.ZipFile(path) as z:
        infos=[i for i in z.infolist() if not i.is_dir()]
        if not infos or len(infos)>MAX_FILES: raise ValueError('Número de archivos del ZIP no admitido.')
        seen=set(); result=[]; ids=set(); total=0
        for info in infos:
            name=info.filename
            if name in seen: raise ValueError('ZIP con entradas repetidas.')
            seen.add(name)
            if name.startswith('/') or '\\' in name or any(x in ('','.','..') for x in name.split('/')):
                raise ValueError('El ZIP contiene rutas inseguras.')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('El ZIP contiene enlaces simbólicos.')
            total += info.file_size
            if total>MAX_BYTES: raise ValueError('ZIP excesivamente grande para una instalación segura.')
            parts=PurePosixPath(name).parts
            if len(parts)>=6 and parts[:3]==('GTAVMenu','custom','packs') and parts[4]=='resources':
                ident=parts[3]
                if not PACK_ID.fullmatch(ident): raise ValueError('Identificador de pack no permitido.')
                ids.add(ident)
                relative='/'.join(parts[5:])
                if not relative: raise ValueError('Archivo de recursos sin nombre.')
                result.append((relative,name,info.file_size))
            elif name not in ('ANADIR-A-INSTALLED.txt','INSTRUCCIONES.txt','AVISO-CONVERSION-PARCIAL.txt'):
                raise ValueError('ZIP con archivos fuera de los recursos del paquete.')
        if len(ids)!=1 or not result or not any(x[0]=='pack.cfg' for x in result):
            raise ValueError('El ZIP no contiene exactamente un pack con pack.cfg.')
        if z.testzip() is not None: raise ValueError('Error CRC en el ZIP de entrada.')
    return LocalPack(ids.pop(), tuple(result), total)


def validate_host(host:str,port:int)->str:
    try:
        ip=ipaddress.ip_address(host.strip())
    except ValueError as exc: raise ValueError('Introduce la IP local de la PS5.') from exc
    if ip.version!=4 or not any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise ValueError('FTP solo admite una IPv4 privada de la red local.')
    if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
        raise ValueError('Puerto FTP no válido.')
    return str(ip)


def connect(host:str,port:int,factory=None):
    ip=validate_host(host,port)
    ftp=(factory or ftplib.FTP)()
    try:
        ftp.connect(ip,port,timeout=20)
        ftp.login('anonymous','')
        ftp.cwd(ROOT)
        if hasattr(ftp, 'voidcmd'):ftp.voidcmd('TYPE I')
        return ftp
    except Exception:
        try: ftp.close()
        except Exception: pass
        raise


def close(ftp):
    try: ftp.quit()
    except Exception:
        try: ftp.close()
        except Exception: pass


def _dir_exists(ftp,path):
    try:
        ftp.cwd(path)
        ftp.cwd(ROOT)
        return True
    except ftplib.error_perm as exc:
        if str(exc).startswith('550'):
            try: ftp.cwd(ROOT)
            except Exception: pass
            return False
        raise


def _read_index(ftp,path):
    data=bytearray()
    try:ftp.retrbinary('RETR '+path,data.extend)
    except ftplib.error_perm as exc:
        # Do not mistake an explicit access denial for a missing index.
        message=str(exc).lower()
        if message.startswith('550') and any(x in message for x in ('not found','no such','does not exist','missing')):
            return None
        raise
    if len(data)>100_000: raise ValueError('Registro FTP demasiado grande: '+path)
    data.decode('utf-8-sig')
    return bytes(data)


def _read_installed(ftp):
    return _read_index(ftp,INSTALLED)


def _decode_lines(raw):
    return (raw or b'').decode('utf-8-sig').splitlines()


def _with_id(raw,ident,add,limit=128):
    # The game parser expects ASCII IDs, one per LF-terminated line.
    ids=list(dict.fromkeys(line.strip() for line in _decode_lines(raw) if line.strip()))
    if any(not PACK_ID.fullmatch(i) for i in ids):
        raise ValueError('Registro FTP contiene identificadores inválidos; se conserva intacto.')
    if add and ident not in ids:ids.append(ident)
    if not add:ids=[i for i in ids if i!=ident]
    if len(ids)>limit:raise ValueError('Demasiados packs en el registro FTP.')
    return ''.join(i+'\n' for i in ids).encode('ascii')


def _write_index(ftp,path,old,new,token):
    """Publish via verified staging and backup; confirm final remote bytes."""
    if _read_index(ftp,path)!=old:
        raise RuntimeError('Registro FTP cambió durante la operación: '+path)
    stage=path+'.incoming-'+token
    backup=path+'.backup-'+token
    if new is not None:
        ftp.storbinary('STOR '+stage,io.BytesIO(new),blocksize=65536)
        if _read_index(ftp,stage)!=new:raise RuntimeError('Verificación del registro temporal falló: '+path)
    if old is not None:
        try:ftp.rename(path,backup)
        except Exception as exc:raise RuntimeError('FTP: no se pudo respaldar '+path+'; se conserva el original.') from exc
    try:
        if new is not None:ftp.rename(stage,path)
        if _read_index(ftp,path)!=new:raise RuntimeError('Verificación final del registro falló: '+path)
    except Exception as exc:
        try:
            current=_read_index(ftp,path)
            if current is not None:ftp.rename(path,path+'.failed-'+token)
            if old is not None:ftp.rename(backup,path)
            if _read_index(ftp,path)!=old:raise RuntimeError('readback rollback')
        except Exception:raise RuntimeError('FTP: restauración del registro falló. Revisa '+backup) from exc
        raise RuntimeError('FTP: registro restaurado tras un fallo de escritura: '+path) from exc
    return backup


def _backup_local(raw:bytes,dir:Path,ident:str,token:str)->Path:
    dir.mkdir(parents=True,exist_ok=True)
    backup=dir/(ident+'-installed-backup-'+token+'.txt')
    with backup.open('xb') as f:f.write(raw or b'')
    return backup


def _token():
    return time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]


def _upload_resource(ftp,z,source:str,destination:str,on_bytes):
    with z.open(source) as stream:
        def progress(block):on_bytes(len(block))
        ftp.storbinary('STOR '+destination,stream,blocksize=256*1024,callback=progress)


def preflight(host:str,port:int,factory=None)->dict:
    """Read-only check. FTP does not offer a reliable, standard free-space API."""
    ftp=connect(host,port,factory)
    try:
        raw=_read_installed(ftp)
        return {'connected':True,'menu_root':ROOT,'installed_entries':len(_decode_lines(raw)),
                'remote_free_bytes':None,'space_status':'No verificable con FTP estándar',
                'transport':'FTP sin cifrar (solo LAN)', 'auth':'anonymous'}
    finally:close(ftp)


def install(path:Path,host:str,port:int,log=lambda s:None,progress=lambda n,t:None,
            backup_dir:Path|None=None,factory=None)->Path:
    pack=validate_local_pack(path)
    ftp=connect(host,port,factory)
    token=_token(); ident=pack.ident
    stage=ROOT+'/.incoming-'+ident+'-'+token
    final=ROOT+'/'+ident
    oldpack=ROOT+'/.previous-'+ident+'-'+token
    committed=False; prior=False; started=False
    try:
        original=_read_installed(ftp)
        local_backup=_backup_local(original,backup_dir or path.parent,ident,token)
        log('Copia local de installed: '+str(local_backup))
        log('Espacio libre PS5: FTP estándar no permite comprobarlo; la consola puede rechazar archivos sin espacio.')
        prior=_dir_exists(ftp,final)
        ftp.mkd(stage); started=True
        ftp.mkd(stage+'/resources')
        sent=0; progress(0,pack.total_bytes)
        with zipfile.ZipFile(path) as z:
            for relative,member,size in pack.members:
                remote=stage+'/resources/'+relative
                components=relative.split('/')[:-1]
                folder=stage+'/resources'
                for component in components:
                    folder+='/'+component
                    if not _dir_exists(ftp,folder):ftp.mkd(folder)
                def transferred(count):
                    nonlocal sent
                    sent+=count
                    progress(sent,pack.total_bytes)
                _upload_resource(ftp,z,member,remote,transferred)
                if relative=='pack.cfg':
                    readback=bytearray()
                    ftp.retrbinary('RETR '+remote,readback.extend)
                    if bytes(readback)!=z.read(member):
                        raise RuntimeError('Verificación FTP del manifiesto pack.cfg falló.')
                try:
                    remote_size=ftp.size(remote) if hasattr(ftp,'size') else None
                    if remote_size is not None and remote_size!=size:
                        raise RuntimeError('Tamaño FTP diferente al original: '+relative)
                except ftplib.error_perm:
                    log('AVISO: este servidor FTP no permite comprobar SIZE de '+relative)
        # Stage first: old pack remains untouched during the long upload.
        if prior:ftp.rename(final,oldpack)
        try:ftp.rename(stage,final)
        except Exception:
            if prior:ftp.rename(oldpack,final)
            raise
        committed=True
        try:
            if _read_installed(ftp)!=original:
                raise RuntimeError('installed cambió durante la subida; se cancela para no pisar cambios ajenos.')
            new=_with_id(original,ident,True)
            if new!=original:_write_index(ftp,INSTALLED,original,new,token)
            if _read_installed(ftp)!=new:raise RuntimeError('Registro installed no confirmado por FTP.')
            log('installed verificado por FTP: '+ident)
        except Exception:
            # Restore original pack / do not leave an unregistered replacement.
            try:
                ftp.rename(final,ROOT+'/.failed-'+ident+'-'+token)
                if prior:ftp.rename(oldpack,final)
            except Exception:
                log('ATENCIÓN: restauración del directorio del pack incompleta; revisar el FTP manualmente.')
            raise
        if prior:log('Pack anterior preservado en '+oldpack)
        log('Paquete instalado: '+ident+' (copias de seguridad conservadas).')
        return local_backup
    finally:
        if started and not committed:log('Si una subida fue interrumpida, puede quedar un directorio temporal: '+stage)
        close(ftp)


def uninstall(ident:str,host:str,port:int,backup_dir:Path,log=lambda s:None,factory=None)->Path:
    """Reversible removal: remote pack is quarantined, never permanently erased."""
    if not PACK_ID.fullmatch(ident):raise ValueError('ID de pack incorrecto.')
    ftp=connect(host,port,factory)
    token=_token(); final=ROOT+'/'+ident
    quarantined=ROOT+'/.uninstalled-'+ident+'-'+token
    try:
        raw=_read_installed(ftp)
        active=_read_index(ftp,ACTIVE)
        if ident not in [x.strip() for x in _decode_lines(raw)]:
            raise ValueError('El pack no figura en installed; no se modifica ningún recurso.')
        backup=_backup_local(raw,backup_dir,ident,token)
        exists=_dir_exists(ftp,final)
        active_changed=False; moved=False
        try:
            if active is not None and ident in [x.strip() for x in _decode_lines(active)]:
                _write_index(ftp,ACTIVE,active,_with_id(active,ident,False,16) or None,token)
                active_changed=True
            if exists:ftp.rename(final,quarantined);moved=True
            _write_index(ftp,INSTALLED,raw,_with_id(raw,ident,False),token)
        except Exception:
            if moved:
                try:ftp.rename(quarantined,final)
                except Exception:log('ATENCIÓN: no se pudo restaurar el directorio del pack '+ident)
            if active_changed:
                try:_write_index(ftp,ACTIVE,_with_id(active,ident,False,16) or None,active,token+'-rollback')
                except Exception:log('ATENCIÓN: no se pudo restaurar active; revisar backup remoto.')
            raise
        log('Desinstalado: '+ident+'. Copia recuperable en PS5: '+quarantined if exists else 'Desregistrado '+ident+'.')
        return backup
    finally:close(ftp)
