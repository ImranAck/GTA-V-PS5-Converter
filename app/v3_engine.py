"""Offline, user-owned GTA V PC Legacy mod helper. No console integration except explicit FTP upload.
Original PS5 assets are NEVER bundled in this application: the user imports them locally.
"""
from __future__ import annotations
import ftplib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
APP = ROOT / 'app'
MOTOR = ROOT / 'motor'
# Import only the audited importer; it parses RPF indexes without unpacking models.
sys.path[:0] = [str(MOTOR / 'tools'), str(MOTOR)]
from tools.import_pc_assets import RpfSource, RpfWindow, discover, LIMITS, chain_name, mod_kit_chains, kit_part_names
from gtavmenu_tools import asset_metadata
import conversor_v2_core as core

EXPECTED = {
 'corpus/tornado6.pft':'120996dd9ba11eee19b13f21808ad8637959754e4bf2a3086416bdcc086d1ed8',
 'corpus/tornado6.ptd':'8e8ea88871352cffcd85aa97fe7c07ff443cea8b9d4c9dd6c28626fe0ed435ee',
 'corpus/banshee-a.pft':'cca19838de4b45c69dca9dada667d6e822b5c25ca85445dc3c0f50ce8e449eb2',
 'corpus/banshee-a.ptd':'848808b699cce61448c2a4986b78693cbdefdabb6e0020159f34f1d5d72bc8d8',
 'corpus/decal-schema-a.pft':'0d09a2fa24a48a809678b2d9fdd2ef76e07fe9baf6b8c7098fc50fe19e3e3f1f',
 'corpus/vehshare-a.ptd':'6aaf11afa42d9bf65ba3af537aaf2ccaa7a6395aee897ea8f9cb04a6f8e7252f',
 'razor-shader-database-source-a/sga_prospero_final.awc':'8f91ce58fc0245940ca3d79da00b65fe5f152f6785f02e080d2ee8e3e03bde9c',
 'razor-shader-database-source-a/sga_prospero_final_init.awc':'4d7e3d18c8ed9b3f13fc8325488bb3fb1d78127ae3e4ba1b29fa1d7b180a6f5c',
 'corpus/vigero.pft':'e2771d0e25300eb60055cd5eeac8097ffa494a6a532e0b44a1dc775578f5a555',
 'corpus/trailersmall.pft':'50f915e8b8e045e4b8a6959417721f4a0334b8a44a9fcdb0de18ae4a01a8b989',
 'corpus/trailers3.pft':'b9413a3af708d42992888fab9fbc5f08cbc2300c6d2b2ffd513859f50b368879',
 'corpus/buc2_dl_camo2.pft':'1c4c5b8324bcaf134f8cb791d0fcd7949d4875518fce6524bf820c4ee639c3f2',
 'corpus/cheb_skirts.pft':'a8d720be5abfdf42b4481dbc6db0c7c14f128b0f49ff1d1d2d588a4961d1de7d',
 'corpus/nemesis.pft':'6c15295c12180febe3446686fce7114ec9affea2124099680b960a35584df086',
 'corpus/armytrailer_hi.pft':'5321d3c6fbbf1958ae920dedd50692b595aa19d3b538f09e4fa10671761922e5',
}
OPTIONAL_REFERENCES = {
 'wheels/wheel_loride_01.pdr': (235196, 'cb4577f91fd62e6ea6c0399e82e74091eae8adcd59d0a846a98692e33a75721d'),
 'retail-audio/game.dat151.rel': (2083440, 'd275cfb6f4c29f4601cc32f3694de0321fbb132eabd8d23c4aa66c07d7381ea9'),
}
LAYOUT_SHA = 'ae780f5470b4ffd2aa8636f764f70eeccebf482742d59e88b00f12ec30e6c099'
LAYOUT_BYTES = 2014170

def cache_root() -> Path:
    explicit = os.environ.get('GTAV_CONVERTER_CACHE')
    root = Path(explicit) if explicit else Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.local'/'share')) / 'GTAV-CarMods-PS5'
    root.mkdir(parents=True, exist_ok=True)
    return root

def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def import_optional_reference(source: Path, log=lambda s:None) -> str:
    """Import only the exact pinned original resource; never distribute it."""
    matches = [n for n in OPTIONAL_REFERENCES if Path(n).name.lower() == source.name.lower()]
    if len(matches) != 1: raise ValueError('Referencia opcional desconocida.')
    name = matches[0]; size, sha = OPTIONAL_REFERENCES[name]
    if not source.is_file() or source.stat().st_size != size or digest_file(source) != sha:
        raise ValueError('Referencia original incorrecta o dañada: '+name)
    dest = cache_root()/'recursos'/'plantillas'/name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest.resolve():
        tmp = dest.with_suffix(dest.suffix+'.tmp')
        try:
            shutil.copyfile(source, tmp)
            if digest_file(tmp) != sha: raise ValueError('La referencia cambió durante la copia.')
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
    log('Referencia opcional original verificada: '+name)
    return name

def configured() -> bool:
    base = cache_root()/'recursos'
    marker=base/'config.json'
    if not marker.is_file():return False
    try:
        data=json.loads(marker.read_text(encoding='utf-8'))
        return (data.get('version')==1 and (base/'vehiclelayouts.meta').is_file()
                and digest_file(base/'vehiclelayouts.meta')==LAYOUT_SHA
                and all((base/'plantillas'/n).is_file() and digest_file(base/'plantillas'/n)==sha
                        for n,sha in EXPECTED.items()))
    except (ValueError,OSError):return False

def library_catalog() -> Path:
    """Persistent private shader donor index, separate from refreshable templates.

    Migrate original v4.3/v4.4 index once before re-importing templates.
    The program never distributes original GTA V material data.
    """
    root=cache_root()
    stable=root/'biblioteca-materiales'/'shaders-extra.json'
    legacy=root/'recursos'/'shaders-extra.json'
    if not stable.is_file() and legacy.is_file():
        stable.parent.mkdir(parents=True,exist_ok=True)
        tmp=stable.with_suffix('.json.tmp')
        shutil.copy2(legacy,tmp)
        tmp.replace(stable)
    return stable


def import_resources(template: Path, layouts: Path, log=lambda s:None) -> None:
    """One-time private local install of previously extracted user-owned resources."""
    if not layouts.is_file() or layouts.stat().st_size != LAYOUT_BYTES or digest_file(layouts) != LAYOUT_SHA:
        raise ValueError('vehiclelayouts.meta no coincide con la referencia de 01.010.002.')
    # Migrate a pre-existing donor index BEFORE replacing the template directory.
    library_catalog()
    base=cache_root()/'recursos'
    staging=cache_root()/'recursos-nuevos'
    if staging.exists():shutil.rmtree(staging)
    try:
        target=core.copy_templates(template,staging/'plantillas')
        for name, sha in EXPECTED.items():
            path=target/name
            if digest_file(path)!=sha:
                raise ValueError('Plantilla incorrecta o dañada: '+name)
        # Optional references survive a refresh and are never required for normal cars.
        for name,(size,sha) in OPTIONAL_REFERENCES.items():
            dst=target/name
            if not dst.exists():
                oldref=base/'plantillas'/name
                if oldref.is_file() and oldref.stat().st_size==size and digest_file(oldref)==sha:
                    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(oldref,dst)
            if dst.exists() and (not dst.is_file() or dst.stat().st_size!=size or digest_file(dst)!=sha):
                raise ValueError('Referencia opcional incorrecta: '+name)
        shutil.copy2(layouts,staging/'vehiclelayouts.meta')
        (staging/'config.json').write_text(json.dumps({'version':1,'plantillas':15,'target':'PPSA04263 01.010.002', 'layoutSha256':LAYOUT_SHA},indent=2)+'\n',encoding='utf-8')
        # Replace an entire validated resource set by reversible same-disk renames.
        # Never remove the previous good set before the new directory is in place.
        old=cache_root()/('recursos-respaldo-'+str(time.time_ns()))
        had_previous=base.exists()
        if had_previous:base.rename(old)
        try:staging.rename(base)
        except Exception:
            if had_previous:old.rename(base)
            raise
        if had_previous:
            try:shutil.rmtree(old)
            except OSError:log('AVISO: un respaldo antiguo de recursos sigue en '+str(old))
        log('Recursos originales del juego comprobados y guardados para futuras conversiones.')
    finally:
        if staging.exists():shutil.rmtree(staging)

def auto_resource_candidates() -> tuple[Path|None,Path|None]:
    base=Path.home()
    for folder in (base/'Documents',base/'Desktop',base/'Downloads',base/'OneDrive'/'Documents'):
        t=folder/'GTAV-15-plantillas-BMW-PS5.zip'
        l=folder/'vehiclelayouts.meta'
        if t.is_file() and l.is_file():return t,l
    return None,None

def _source_id(source:Path)->str:
    return digest_file(source)

def prepared_rpf(source:Path, log=lambda s:None)->tuple[Path,Path|None]:
    """Unpack only once; return RPF and optional preview image. ZIP/OIV supported without 7zip."""
    if not source.is_file():raise ValueError('No existe el mod seleccionado.')
    suffix=source.suffix.lower()
    if suffix not in ('.rpf','.zip','.oiv','.rar','.7z'):
        raise ValueError('Elige un RPF, ZIP, OIV, RAR o 7z.')
    if suffix=='.rpf':
        image=next((p for p in [source.with_suffix(ext) for ext in ('.png','.jpg','.jpeg','.webp')] if p.is_file()),None)
        return source,image
    hexdigest = _source_id(source)
    unpack=cache_root()/'mods'/hexdigest
    ready=unpack/'selection.json'
    if ready.exists():
        try:
            state=json.loads(ready.read_text(encoding='utf-8'))
            p=unpack/state['rpf']
            picture=unpack/state['image'] if state.get('image') else None
            if p.is_file():
                log('Archivo ya extraído: se reutiliza la copia privada del mod.')
                return p, picture if picture and picture.exists() else None
        except (ValueError,KeyError,OSError):pass
    if unpack.exists():shutil.rmtree(unpack)
    unpack.mkdir(parents=True)
    if suffix in ('.zip','.oiv'):
        try:
            with zipfile.ZipFile(source) as z:
                infos=[i for i in z.infolist() if not i.is_dir()]
                rpfs=[i for i in infos if i.filename.replace('\\','/').lower().endswith('/dlc.rpf') or i.filename.lower()=='dlc.rpf']
                if not rpfs:raise ValueError('No hay dlc.rpf: los mods Replace con YFT/YTD sueltos requieren una ruta distinta, todavía no compatible.')
                if len(rpfs)!=1:raise ValueError(f'El archivo contiene {len(rpfs)} dlc.rpf; extrae y selecciona la variante correcta manualmente.')
                rpf=unpack/'dlc.rpf'
                if rpfs[0].file_size>8_000_000_000:raise ValueError('RPF excesivamente grande.')
                with z.open(rpfs[0]) as fin,rpf.open('wb') as fout:shutil.copyfileobj(fin,fout,4*1024*1024)
                images=[i for i in infos if i.filename.lower().endswith(('.png','.jpg','.jpeg')) and i.file_size<10_000_000]
                images.sort(key=lambda i:(not any(k in i.filename.lower() for k in ('preview','cover','screen','picture','image')),len(i.filename)))
                picture=None
                if images:
                    picture=unpack/('foto'+Path(images[0].filename).suffix.lower())
                    with z.open(images[0]) as fin,picture.open('wb') as fout:shutil.copyfileobj(fin,fout)
        except zipfile.BadZipFile as exc:raise ValueError('El ZIP del coche está dañado.') from exc
    else:
        log('Descomprimiendo RAR/7z la primera vez…')
        rpf=core.prepare_mod(source,unpack/'archivo',log)
        # Limit exposure to extracted images. Photos are optional.
        candidates=[]
        for extension in ('*.png','*.jpg','*.jpeg'):
            candidates.extend(unpack.rglob(extension))
        picture=next((p for p in candidates if p.is_file() and p.stat().st_size<10_000_000),None)
    ready.write_text(json.dumps({'rpf':rpf.relative_to(unpack).as_posix(),'image':picture.relative_to(unpack).as_posix() if picture else None},indent=2)+'\n',encoding='utf-8')
    return rpf,picture

def scan_rpf(path:Path)->list[dict]:
    """Fast RPF table scan; XML metadata supplied by the mod only; no 3D rendering."""
    src=RpfSource(path)
    try:
        root=RpfWindow(src,0,src.before.st_size,'')
        _, entries=discover(root)
        files={member.name.lower() for _,member in entries}
        names=sorted({member.name[:-4].lower() for _,member in entries if member.name.lower().endswith('.yft') and not member.name.lower().endswith('_hi.yft') and (member.name[:-4]+'_hi.yft').lower() in files and (member.name[:-4]+'.ytd').lower() in files})
        metadata={}
        for m in root.members():
            if m.name.lower().endswith('vehicles.meta') and not m.encrypted and max(m.size,m.unpacked_size)<4_000_000:
                xml=asset_metadata.parse_xml(root.read_member(m,4_000_000),LIMITS)
                for item in xml.findall('./InitDatas/Item'):
                    n=(item.findtext('modelName') or '').strip().lower()
                    if n:
                        metadata[n]={key:(item.findtext(key) or '').strip() for key in ('vehicleMakeName','gameName','modelName')}
        result=[]
        for n in names:
            meta=metadata.get(n,{})
            game=meta.get('gameName') or n
            make=meta.get('vehicleMakeName','')
            # Prefer meaningful literal names from vehicles.meta; GXT2 tokens may be opaque.
            if re.fullmatch(r'[A-Z0-9_]{2,24}',game) and not any(' ' in x for x in (game,make)):
                # If no spaces, still preserve metadata rather than invent a vehicle name.
                pass
            text=' '.join(x for x in (make,game) if x).replace('_',' ').strip()
            text=text.title().replace('Bmw','BMW').replace('Gta','GTA') if text else n.upper()
            # Scan referenced vehiclemods without converting the parts. Their conversion is
            # explicitly opt-in because rigid model types are not supported by the 3D writer.
            try:
                yft_chains=[chain_name(w,m) for w,m in entries if m.name.lower().endswith('.yft')]
                parts=mod_kit_chains(n,yft_chains,kit_part_names(n,root))
            except (ValueError, KeyError, OSError):
                parts=[]
            result.append({'model':n,'name':text[:64],'packid':('gtavmenu-'+n)[:64],
                           'photo':'optional','tuning_parts':len(parts)})
        # Standalone custom wheel packs are a distinct installable pack. Never
        # confuse a wheel drawable with a vehicle model or a visibleMods YFT.
        wheels = _wheel_rows(entries)
        if wheels:
            ident = 'gtavmenu-wheels-' + digest_file(path)[:12]
            result.append({'model':'@wheels','name':'Custom wheels ('+str(len(wheels))+')',
                           'packid':ident,'photo':'optional','tuning_parts':0,
                           'wheel_count':len(wheels)})
        return result
    finally:src.close()

def _wheel_rows(entries):
    from convert_pc_wheel import parse_wheels
    models={m.name.lower() for _,m in entries if m.name.lower().endswith('.ydr')}
    if not models:return []
    wheels={}
    for w,m in entries:
        if 'carcols' not in m.name.lower() or not m.name.lower().endswith('.meta'):continue
        text=w.read_member(m,16*1024*1024).decode('utf-8-sig')
        for row in parse_wheels(text,chain_name(w,m)):
            if row.name.lower()+'.ydr' in models:
                wheels.setdefault(row.name.lower(),row)
    return list(wheels.values())


def convert_wheel_pack(rpf:Path, packid:str, output:Path, log=lambda s:None, texture_size=0, workers=1):
    if not configured():raise ValueError('Configura primero los recursos originales de tu copia de GTA V PS5.')
    if not re.fullmatch('[a-z0-9][a-z0-9_-]{1,63}',packid):raise ValueError('ID de paquete no válido.')
    if texture_size not in (0,512,1024,2048):raise ValueError('Calidad de texturas no permitida.')
    tpl=cache_root()/'recursos'/'plantillas'
    rel='wheels/wheel_loride_01.pdr'; size,sha=OPTIONAL_REFERENCES[rel]
    ref=tpl/rel
    if not ref.is_file() or ref.stat().st_size!=size or digest_file(ref)!=sha:
        raise ValueError('Importa wheel_loride_01.pdr original en Referencias PS5.')
    output.mkdir(parents=True,exist_ok=True)
    destination=output/(packid+'-PARA-PS5.zip')
    if destination.exists():raise ValueError('Ya existe un ZIP con ese ID; no se sobrescribe.')
    # Isolated temporary build; never remove any existing vehicle or wheel pack.
    with tempfile.TemporaryDirectory(prefix='wheel-pack-',dir=cache_root()) as d:
        work=Path(d); tool=MOTOR/'tools'; packs=work/'packs'
        env=dict(os.environ,GTAV_TEXTURE_WORKERS=str(min(max(1,workers),8)),OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='1')
        cmd=[sys.executable,str(tool/'convert_pc_wheel.py'),'pack','--source',str(rpf),'--id',packid,'--templates',str(tpl),'--work',str(work/'work'),'--output-root',str(packs)]
        if texture_size:cmd.extend(['--max-texture-size',str(texture_size)])
        log('[01] Conversión de llantas personalizadas')
        core.run_process(cmd,'Conversión de llantas PC Legacy → PS5',log,env=env)
        report=json.loads((work/'work'/'wheel-pack-report.json').read_text(encoding='utf-8'))
        expected={r.name.lower() for r in _read_wheel_rows(rpf)}
        actual={r['name'].lower() for r in report['wheels']}
        if not expected or actual!=expected:raise ValueError('El paquete de llantas no conserva todos los modelos detectados.')
        log('[02] Validación final de llantas')
        core.run_process([sys.executable,str(tool/'validate_runtime_pack.py'),str(packs/packid),'--target','ppsa04263-01.010.002'],'Validación final',log,env=env)
        log(f'Llantas convertidas: {len(actual)}. Selección desde LS Customs de GTAV Menu; prueba física pendiente.')
        return make_zip(packs/packid,output),False


def _read_wheel_rows(path):
    src=RpfSource(path)
    try:
        _,entries=discover(RpfWindow(src,0,src.before.st_size,''))
        return _wheel_rows(entries)
    finally:src.close()


def _engine_fingerprint() -> str:
    """Invalidate resumable work after *any* conversion tool changes."""
    h = hashlib.sha256()
    for path in sorted((MOTOR / 'tools').rglob('*.py')):
        h.update(path.relative_to(MOTOR).as_posix().encode('utf-8'))
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
    return h.hexdigest()


def _donor_fingerprint(index:Path) -> list | None:
    if not index.is_file():
        return None
    try:
        doc=json.loads(index.read_text(encoding='utf-8'))
        refs=[]
        for row in doc.get('references', []):
            path=Path(row['path'])
            st=path.stat()
            refs.append([str(path),st.st_size,st.st_mtime_ns, row.get('sha256')])
        return [digest_file(index),sorted(refs)]
    except (ValueError, KeyError, OSError) as exc:
        raise ValueError('La biblioteca de modelos PS5 se ha movido o está dañada. Vuelve a indexarla.') from exc


def _signature(p:Path):return [p.stat().st_size,digest_file(p)]

def convert(rpf:Path, model:str, name:str, packid:str, output:Path,
            log=lambda s:None,texture_size:int=0,workers:int=1,auto_texture_fit:bool=False,handling_mode:str="balanced",include_tuning:bool=True)->tuple[Path,bool]:
    try:
        import numpy  # noqa: F401
    except ImportError as exc:
        raise ValueError('Falta NumPy. Ejecuta INSTALAR-DEPENDENCIAS-SI-FALTAN.bat.') from exc
    if texture_size not in (0,512,1024,2048):raise ValueError('Calidad de texturas no permitida.')
    if handling_mode not in ('balanced','original'):raise ValueError('Perfil de conducción no válido.')
    cpu=max(1,os.cpu_count() or 1)
    if not 1<=workers<=cpu:raise ValueError('Selecciona entre 1 y los procesadores lógicos disponibles.')
    if not configured():raise ValueError('Primero configura los recursos originales de tu copia de GTA V PS5.')
    if not re.fullmatch('[a-z0-9_]+',model):raise ValueError('ID de modelo no válido.')
    if not re.fullmatch('[a-z0-9][a-z0-9_-]{1,63}',packid):raise ValueError('ID de paquete no válido.')
    if not name or len(name)>64:raise ValueError('Nombre de coche no válido.')
    output.mkdir(parents=True,exist_ok=True)
    res=cache_root()/'recursos'
    tpl=res/'plantillas'
    layout=res/'vehiclelayouts.meta'
    job=cache_root()/'trabajos-v100'/packid
    pack=job/'paquetes'/packid
    marker=job/'conversion-v3.json'
    resume_marker=job/'conversion-resume-identity.json'
    identity={'version':7, 'skip_unsupported_tuning':True, 'handling_mode':handling_mode,'include_tuning':include_tuning,'auto_texture_fit':auto_texture_fit,'rpf':_signature(rpf),'model':model,'name':name,'id':packid,'layout':LAYOUT_SHA,'target':'PPSA04263-01.010.002', 'engine':digest_file(MOTOR/'tools'/'convert_vehicle.py'),'texture_size':texture_size,'texture_writer':digest_file(MOTOR/'tools'/'convert_pc_ytd_writer.py'),
      'material_library': digest_file(library_catalog()) if (library_catalog()).is_file() else None,
      'repair_engine': digest_file(MOTOR/'tools'/'repair_pc_auto.py'),
      'reference_engine': digest_file(MOTOR/'tools'/'convert_pc_vehicle.py'),
      'source_importer': digest_file(MOTOR/'tools'/'import_pc_assets.py'),
      'all_tools_fingerprint': _engine_fingerprint(),
      'optional_references': {n:digest_file(tpl/n) for n in OPTIONAL_REFERENCES if (tpl/n).is_file()},
      'external_material_references': _donor_fingerprint(library_catalog())}
    record_path=job/'resultado-v100.json'
    if marker.is_file() and (pack/'resources'/'pack.cfg').is_file():
        try:
            saved=json.loads(marker.read_text(encoding='utf-8'))
        except (ValueError,OSError):saved={}
        if saved==identity:
            log('Caché verificada: esta conversión ya terminó; no se repetirán modelos ni texturas.')
            try:
                record=json.loads(record_path.read_text(encoding='utf-8'))
                for warning in record.get('warnings',[]):log(warning)
                candidate=output/Path(record['file']).name
                if candidate.is_file() and digest_file(candidate)==record['sha256']:
                    return candidate,True
            except (ValueError,OSError,KeyError,TypeError):
                record={}
            core.run_process([sys.executable,str(MOTOR/'tools'/'validate_runtime_pack.py'),str(pack),'--target','ppsa04263-01.010.002'],'Revalidar',log)
            result=make_zip(pack,output,alternate=True,warnings=record.get('warnings',[]))
            record_path.write_text(json.dumps({'file':result.name,'sha256':digest_file(result),'warnings':record.get('warnings',[])},ensure_ascii=False),encoding='utf-8')
            return result,True
        history=cache_root()/'historial-v100'
        history.mkdir(parents=True,exist_ok=True)
        # Keep previous completed jobs intact when the user changes options.
        destination=history/(packid+'-'+str(time.time_ns()))
        job.rename(destination)
        log('Opciones nuevas: conversión anterior conservada; se creará una nueva copia.')
    resume = False
    if job.exists() and resume_marker.is_file():
        try:
            resume = json.loads(resume_marker.read_text(encoding='utf-8')) == identity
        except (ValueError, OSError):
            resume = False
    if job.exists() and not resume:
        log('Los datos de entrada cambiaron o no hay checkpoints: limpiando únicamente el intento anterior.')
        shutil.rmtree(job)
    if resume:
        log('Reanudando: se reutilizarán etapas COMPLETAS y verificadas; no se repetirán modelos ya reparados.')
    (job/'paquetes').mkdir(parents=True,exist_ok=True)
    if not resume:
        temp_marker = resume_marker.with_suffix('.tmp')
        temp_marker.write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        temp_marker.replace(resume_marker)
    cmd=core.make_command(rpf,model,packid,name,tpl,layout,job/'paquetes',texture_size)
    cmd.extend(['--handling-profile',handling_mode])
    if include_tuning:cmd.extend(['--mod-kit','--parts-repair','auto','--skip-unsupported-tuning'])
    wheel_warning = None
    if _read_wheel_rows(rpf):
        wheel_warning = ('WARNING_OPTIONAL_EXCLUDED: llantas personalizadas independientes no incluidas '
                         'en el coche; convierte el paquete @wheels por separado')
        log(wheel_warning)
    cmd.append('--drop-wheels')  # independent wheel pack route; preserve stock options
    # Reserve ids against OTHER locally completed vehicle packs, not only this job.
    for local in sorted([*job.parent.glob('*/paquetes'),*(cache_root()/'trabajos').glob('*/paquetes')]):
        if local.parent.name != packid and local.is_dir():
            cmd.extend(['--ids-from',str(local)])
    cmd.extend(['--ids-from',str(job/'paquetes')])
    cmd.append('--resume')
    if auto_texture_fit: cmd.append('--auto-texture-fit')
    env=os.environ.copy()
    env['GTAV_HOST_BUILD_DIR']=str(job/'build')
    env['GTAV_TEXTURE_WORKERS']=str(min(workers,8))
    env['GTAV_MODEL_WORKERS']=str(min(workers,4))
    donor_catalog=library_catalog()
    if donor_catalog.is_file():
        env['GTAV_USER_SHADER_LIBRARY']=str(donor_catalog)
        log('Biblioteca ampliada de shaders PS5 activada: referencias locales verificadas.')
    else:
        log('AVISO: falta la biblioteca de materiales PS5 adicionales. Pulsa «Ampliar materiales PS5» y selecciona la carpeta de modelos .pft o .pdr originales.')
    # Prevent NumPy's internal BLAS pool from multiplying the number of threads.
    for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
        env[key]='1'
    log(f'Conducción: {"equilibrada (límites por categoría)" if handling_mode=="balanced" else "original del mod"}; piezas especiales: {"activadas (experimentales)" if include_tuning else "desactivadas"}.')
    log(f'Conversión nueva: calidad {"ORIGINAL, sin recortes" if texture_size == 0 else str(texture_size) + "px (solo mips existentes)"}; {workers} núcleos elegidos, hasta {min(workers,8)} hilos para texturas.')
    log('Modo calidad: no se reducirá silenciosamente la resolución. El escritor admite hasta 128 MiB por diccionario. Si se necesitan varios, la cadena de texturas es EXPERIMENTAL y requiere prueba en PS5.')
    if auto_texture_fit: log('Ajuste de límites de texturas habilitado: si el paquete PS5 excede capacidad, se puede reducir SOLO el diccionario problemático a 256px, con aviso.')
    log('Comprobación temprana de shaders: se detendrá antes del paso 3D pesado si faltan referencias originales.')
    warnings=[wheel_warning] if wheel_warning else []
    def capture(message):
        if any(mark in message for mark in ('WARNING_TUNING_EXCLUDED:', 'WARNING_OPTIONAL_EXCLUDED:', 'WARNING: tuning excluded', 'left out (', 'WARNING_TEXTURE_CHAIN:', 'all custom tuning models are unsupported')):
            warnings.append(message)
        log(message)
    core.run_process(cmd,'Conversión PC Legacy → PS5',capture,env=env)
    core.run_process([sys.executable,str(MOTOR/'tools'/'validate_runtime_pack.py'),str(pack),'--target','ppsa04263-01.010.002'],'Validación final',log,env=env)
    result=make_zip(pack,output,alternate=True,warnings=warnings)
    record_path.write_text(json.dumps({'file':result.name,'sha256':digest_file(result),'warnings':warnings},ensure_ascii=False),encoding='utf-8')
    marker.write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return result,False



def rebalance_existing_zip(source:Path, log=lambda s:None, *, verify:bool=True)->tuple[Path,dict]:
    """Produce a NEW balanced pack from an existing pack ZIP; does not rebuild 3D or textures.

    Validates the pack descriptor SHA and size and, in normal mode, the complete output
    via the upstream runtime-pack validator. Never modifies a source ZIP or installed PS5 pack.
    """
    import tempfile
    from handling_balance import balance
    if not source.is_file() or source.suffix.lower()!='.zip':
        raise ValueError('Selecciona un ZIP de coche generado por este conversor.')
    with zipfile.ZipFile(source,'r') as z:
        members=z.infolist()
        if any(i.file_size>512*1024*1024 or i.filename.startswith('/') or '..' in Path(i.filename).parts
               or '\\' in i.filename for i in members):
            raise ValueError('ZIP con entradas peligrosas o demasiado grandes.')
        cfg=[i.filename for i in members if i.filename.endswith('/resources/pack.cfg')]
        if len(cfg)!=1 or not cfg[0].startswith('GTAVMenu/custom/packs/'):
            raise ValueError('El ZIP no tiene un descriptor único de pack.')
        root=cfg[0].removesuffix('pack.cfg')
        ident=Path(root.rstrip('/')).parent.name
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,63}',ident):
            raise ValueError('ID de pack incorrecto.')
        if not all(i.filename.startswith(root) or i.filename in ('ANADIR-A-INSTALLED.txt','INSTRUCCIONES.txt','AVISO-CONVERSION-PARCIAL.txt')
                   for i in members):
            raise ValueError('El ZIP contiene archivos fuera de su pack.')
        cfg_text=z.read(cfg[0]).decode('utf-8')
        rows=[]
        for line in cfg_text.splitlines():
            cols=line.split('\t')
            if len(cols)==5 and cols[0]=='data' and cols[1] in ('HANDLING_FILE','VEHICLE_METADATA_FILE'):
                rows.append(cols)
        handle=[r for r in rows if r[1]=='HANDLING_FILE']
        car=[r for r in rows if r[1]=='VEHICLE_METADATA_FILE']
        if len(handle)!=1 or len(car)!=1:
            raise ValueError('El pack no contiene un handling y vehicles.meta verificables.')
        for row in (handle[0],car[0]):
            logical=root+row[4]
            if logical not in z.namelist():raise ValueError('Falta '+logical)
            buf=z.read(logical)
            if len(buf)!=int(row[2]) or hashlib.sha256(buf).hexdigest()!=row[3]:
                raise ValueError('El descriptor no coincide con '+logical)
        handling_file=root+handle[0][4]
        raw=z.read(handling_file)
        try:
            handling=raw.decode('utf-8-sig')
            vehicles=z.read(root+car[0][4]).decode('utf-8-sig')
        except UnicodeError as exc:
            raise ValueError('Metadatos incompatibles con UTF-8.') from exc
        model=handle[0][4].removesuffix('_handling.meta')
        revised, report=balance(handling,vehicles,model,mode='balanced')
        if not report['changes']:
            raise ValueError('Este pack no tiene parámetros extremos que equilibrar o el handling no corresponde al coche.')
        blob=revised.encode('utf-8')
        new_line='\t'.join(['data','HANDLING_FILE',str(len(blob)),hashlib.sha256(blob).hexdigest(),handle[0][4]])
        old_line='\t'.join(handle[0])
        if cfg_text.count(old_line)!=1:raise ValueError('Descriptor ambiguo; no se modificará el pack.')
        next_cfg=cfg_text.replace(old_line,new_line,1).encode('utf-8')
        destination=source.with_name(ident+'-EQUILIBRADO-PARA-PS5.zip')
        if source.resolve()==destination.resolve() or destination.exists():
            raise ValueError('Ya existe el ZIP de conducción equilibrada; no se sobrescribe.')
        temp_zip=destination.with_suffix('.zip.tmp')
        try:
            with zipfile.ZipFile(temp_zip,'w',allowZip64=True) as out:
                for info in members:
                    content=(blob if info.filename==handling_file else
                             next_cfg if info.filename==cfg[0] else z.read(info))
                    out.writestr(info,content)
                out.writestr('CONDUCCION-EQUILIBRADA.txt',
                    'Se ajustaron exclusivamente parámetros extremos del motor y frenos.\n'
                    'La velocidad real y la marcha atrás deben comprobarse en PS5.\n'
                    'No se modificaron mallas, texturas ni las piezas del tuning.\n')
            with zipfile.ZipFile(temp_zip) as check_zip:
                if check_zip.testzip() is not None:raise ValueError('ZIP final con error CRC')
                if verify:
                    from validate_runtime_pack import check as pack_check
                    with tempfile.TemporaryDirectory(prefix='gtav-balanced-') as d:
                        packdir=Path(d)/ident
                        (packdir/'resources').mkdir(parents=True)
                        for member in members:
                            if member.filename.startswith(root) and not member.is_dir():
                                rel=member.filename.removeprefix(root)
                                target=packdir/'resources'/rel
                                target.parent.mkdir(parents=True,exist_ok=True)
                                target.write_bytes(check_zip.read(member.filename))
                        parsed,errs,warnings=pack_check(packdir,target='ppsa04264-01.010.002')
                        if errs or parsed is None:
                            raise ValueError('El nuevo pack no supera la validación: '+ '; '.join(errs[:3]))
                        for warn in warnings[:5]:log('VALIDACION: '+warn)
            temp_zip.replace(destination)
        except Exception:
            temp_zip.unlink(missing_ok=True)
            raise
    for c in report['changes']:
        log('Conducción: '+c['field']+f" {c['before']:g} -> {c['after']:g}")
    log('ZIP equilibrado: '+str(destination))
    return destination,report

def index_user_shader_library(folder:Path, log=lambda s:None)->dict:
    """One-time resource indexing; never copies retail material bytes into the app."""
    from user_shader_library import scan
    from shader_preflight import native_types
    if not configured():
        raise ValueError('Configura primero los recursos originales de tu juego.')
    baseline=native_types(cache_root()/'recursos'/'plantillas')
    result=scan(folder,library_catalog(),log,baseline=baseline,merge=True)
    log(f"Banco PS5: {result['shaderTypes']} tipos totales, {result['newShaderTypes']} NUEVOS, "
        f"{len(result['references'])} recursos adicionales; {result['rejected']} descartados.")
    return result

def list_packages(folder:Path)->list[tuple[str,Path]]:
    """Discover only locally generated pack ZIPs, verifying their IDs and layout.

    No FTP activity occurs during discovery. Reopen the ZIP at install time.
    """
    if not folder.is_dir():return []
    result=[]
    for p in sorted(folder.glob('*-PARA-PS5.zip'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            with zipfile.ZipFile(p) as z:
                names=[n for n in z.namelist() if n.endswith('/resources/pack.cfg') and n.startswith('GTAVMenu/custom/packs/')]
                if len(names)!=1:continue
                parts=Path(names[0]).parts
                if len(parts)!=6 or not re.fullmatch('[a-z0-9][a-z0-9_-]{1,63}',parts[3]):continue
                result.append((parts[3],p))
        except (OSError,zipfile.BadZipFile,ValueError):continue
    return result


def make_zip(pack:Path,out:Path,*,alternate:bool=False,warnings:list[str]|None=None)->Path:
    resources=pack/'resources'
    if not (resources/'pack.cfg').is_file():raise ValueError('El motor no creó resources/pack.cfg.')
    archive=out/(pack.name+'-PARA-PS5.zip')
    if alternate:
        index=2
        while archive.exists():
            archive=out/f'{pack.name}-{index}-PARA-PS5.zip'
            index+=1
    if archive.exists():raise ValueError('Ya existe un ZIP con ese nombre; no se sobrescribe.')
    with zipfile.ZipFile(archive,'x',allowZip64=True) as z:
        for p in sorted(resources.rglob('*')):
            if p.is_file():
                rel=(Path('GTAVMenu')/'custom'/'packs'/pack.name/'resources'/p.relative_to(resources)).as_posix()
                # Resource archives are already compressed; avoid re-deflating them for minutes.
                method=zipfile.ZIP_STORED if p.suffix.lower()=='.rpf' else zipfile.ZIP_DEFLATED
                z.write(p,rel,compress_type=method,compresslevel=1 if method==zipfile.ZIP_DEFLATED else None)
        omitted = list(dict.fromkeys(
            warning for warning in (warnings or []) if warning.startswith(('WARNING_TUNING_EXCLUDED:', 'WARNING_OPTIONAL_EXCLUDED:'))
        ))
        if omitted:
            z.writestr('AVISO-CONVERSION-PARCIAL.txt',
                       'CONVERSION ESTRUCTURAL COMPLETADA CON OMISIONES\n\n'
                       'El modelo principal supero la validacion en PC. Las piezas\n'
                       'independientes indicadas abajo NO se han incluido y NO\n'
                       'apareceran como modificaciones en el menu.\n'
                       'El comportamiento en PS5 no esta garantizado.\n\n'
                       + '\n'.join(omitted) + '\n')
        z.writestr('ANADIR-A-INSTALLED.txt',pack.name+'\n')
        z.writestr('INSTRUCCIONES.txt',
           'Copia GTAVMenu de este ZIP a /data/GTAVMenu.\n'
           'NO sobrescribas el installed de la PS5 con la nota ANADIR-A-INSTALLED.txt.\n'
           'Para registrar el coche automáticamente usa la función FTP del conversor.\n'
           'Si instalas manualmente: añade la línea indicada en ANADIR-A-INSTALLED.txt al fichero installed existente.\n'
           'En el juego, desactiva los demás coches durante la primera prueba.\n')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Error CRC en salida.')
    return archive

# Public-release FTP operations are isolated from the legacy uploader so that
# future UI changes cannot bypass transactional remote backups.
import ftp_manager as ftp_secure

def ftp_preflight(host:str,port:int=1337):
    return ftp_secure.preflight(host,port)

def ftp_install(zip_path:Path,host:str,port:int=1337,log=lambda s:None,progress=lambda n,t:None)->Path:
    return ftp_secure.install(zip_path,host,port,log,progress,backup_dir=cache_root()/'ftp-backups')

def ftp_uninstall(ident:str,host:str,port:int=1337,log=lambda s:None)->Path:
    return ftp_secure.uninstall(ident,host,port,cache_root()/'ftp-backups',log)
