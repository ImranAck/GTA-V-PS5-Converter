#!/usr/bin/env python3
"""User-owned supplemental PS5 shader material references, indexed once per folder.

Only decoded original PS5 RSC7 .pft and .pdr files with compatible Gen9
material layouts can enter the library. Source bytes are never distributed with
this application. SHA256 pins and structural readback are rechecked on use.
The library is *supplementary*: tested pinned schemas always take precedence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))

import gen9_materials
from gtavmenu_tools import drawable_contracts, vehicle_contracts
from gtavmenu_tools.asset_formats import AssetError, decode_resource
from gtavmenu_tools.asset_textures import SYSTEM_BASE

DONOR_SUFFIXES = frozenset({'.pft', '.pdr'})
MAX_FILE = 40 * 1024 * 1024
MAX_SCAN = 20000
MAX_LIBRARY = 256
FORMAT = 'gtav-ps5-user-shader-library-v1'


def sha(data: bytes)->str:
    return hashlib.sha256(data).hexdigest()


def read_materials(path:Path):
    """Bounded extraction of native shader schemas from a PS5 fragment or drawable.

    Other native fragment formats are rejected, not reinterpreted.
    """
    if not path.is_file() or path.is_symlink() or not 16 <= path.stat().st_size <= MAX_FILE:
        raise ValueError('No es un fragmento PS5 .pft válido o supera el límite de tamaño')
    data = path.read_bytes()
    head, payload=decode_resource(data,32*1024*1024)
    suffix=path.suffix.lower()
    if suffix not in DONOR_SUFFIXES or head['version'] != {'.pft':171,'.pdr':159}[suffix]:
        raise ValueError('Versión de recurso nativo diferente de PS5 01.010.002')
    # For PS5 fragmented vehicles the root object's first drawable pointer is
    # at the native fragment contract offset. Reject different root encodings.
    contract=drawable_contracts.load()
    offset=contract['material']['fragment']['fields']['drawablePointer']['offset']
    group_delta=vehicle_contracts.load()['native']['material']['drawableShaderGroupOffset']
    system=payload[:head['systemBytes']]
    if suffix == '.pft':
        if offset + 8 > len(system):
            raise ValueError('Fragmento sin puntero drawable completo')
        drawable=struct.unpack_from('<Q',system,offset)[0]-SYSTEM_BASE
    else:
        drawable=0
        if group_delta != contract['geometry']['drawable']['fields']['ShaderGroupPointer']['offset']:
            raise ValueError('Contrato de materiales PDR incompatible')
    slot=drawable + group_delta
    if drawable < 0 or slot<0 or slot+8>len(system) or drawable % 16:
        raise ValueError('Fragmento incompatible: puntero drawable fuera del área verificada')
    group=struct.unpack_from('<Q',system,slot)[0]-SYSTEM_BASE
    if group<0 or group%8:
        raise ValueError('Grupo de materiales fuera del área verificada')
    rows=gen9_materials.read_group(system,SYSTEM_BASE,group,contract['shader'])
    if not rows:
        raise ValueError('No contiene materiales compatibles')
    return sha(data), rows


def _load(path:Path):
    if not path.is_file():
        return []
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('format')!=FORMAT or data.get('target')!='PPSA04263-01.010.002':
        raise ValueError('Banco de materiales de otra versión o formato')
    rows=data.get('references')
    if not isinstance(rows,list) or len(rows)>MAX_LIBRARY:
        raise ValueError('Biblioteca de referencias malformada o demasiado grande')
    return rows


def references_from_environment():
    raw=os.environ.get('GTAV_USER_SHADER_LIBRARY')
    if not raw:
        return []
    rows=_load(Path(raw))
    result=[]
    seen=set()
    for entry in rows:
        path=Path(entry['path'])
        expected=entry['sha256']
        if not path.is_absolute() or path.is_symlink() or path.suffix.lower() not in DONOR_SUFFIXES or len(expected)!=64:
            raise ValueError('Referencia externa con ruta/identidad no permitida')
        if path in seen:
            raise ValueError('Referencia externa duplicada')
        seen.add(path)
        digest,shaders=read_materials(path)
        current=sorted({r['schema']['nameHash'] for r in shaders})
        if digest!=expected or current!=entry['shaders']:
            raise ValueError('Referencia de materiales modificada desde su verificación: '+str(path))
        result.append((path,path.read_bytes()))
    return result


def scan(source:Path,catalog:Path, log=print, baseline=None, *, merge=False):
    """Index a *whole folder* once. Keep only donor files adding new mapped types.

    Only descriptors from original native fragments are accepted. The hash and
    actual schema are verified again before any conversion uses the donor.
    """
    if not source.is_dir():
        raise ValueError('Selecciona una carpeta con archivos .pft originales de tu PS5')
    source=source.resolve()
    contract=drawable_contracts.load()['shader']['mappings']
    baseline=set(baseline or ())
    known=set(baseline)
    accepted=[]
    if merge and catalog.is_file():
        for entry in _load(catalog):
            path=Path(entry['path'])
            if path.is_symlink() or not path.is_absolute():
                raise ValueError('Referencia previa inválida')
            digest, rows=read_materials(path)
            hashes=sorted({r['schema']['nameHash'] for r in rows})
            if digest!=entry['sha256'] or hashes!=entry['shaders']:
                raise ValueError('Referencia previa modificada: '+path.name)
            accepted.append(entry)
            known.update(h for h in hashes if str(h) in contract)
    checked=0; rejected=0; unmapped=0; checked_pft=0; checked_pdr=0
    for p in sorted(source.rglob('*')):
        if p.suffix.lower() not in DONOR_SUFFIXES or not p.is_file():continue
        checked+=1
        if p.suffix.lower()=='.pft':checked_pft+=1
        else:checked_pdr+=1
        if checked>MAX_SCAN:raise ValueError('Demasiados archivos: organiza la biblioteca en carpetas más pequeñas')
        try:
            digest, shaders=read_materials(p)
            hashes=sorted({r['schema']['nameHash'] for r in shaders})
            supported={h for h in hashes if str(h) in contract}
            unmapped+=len(hashes)-len(supported)
            added=supported-known
            if not added:continue
            # Prefer native fragments contributing missing types, retaining all
            # schemas for later preflight conflict/readback checks.
            accepted.append({'path':str(p.resolve()),'bytes':p.stat().st_size,
                             'sha256':digest,'shaders':hashes})
            known.update(added)
            log('Materiales nuevos en '+p.name+': '+', '.join(contract[str(h)].get('name',hex(h)) for h in sorted(added)))
            if len(accepted)>MAX_LIBRARY:
                raise ValueError('La biblioteca supera el máximo de referencias verificables')
        except (OSError,ValueError,AssetError,struct.error,IndexError,KeyError) as exc:
            rejected+=1
            log(f'Ignorado {p.name}: {str(exc)[:180]}')
    document={'format':FORMAT,'target':'PPSA04263-01.010.002','sourceFolder':str(source),
              'references':accepted,'shaderTypes':len(known),'newShaderTypes':len(known-baseline),'scannedPft':checked_pft,'scannedPdr':checked_pdr,
              'rejected':rejected,'unmappedShaderObservations':unmapped}
    catalog.parent.mkdir(parents=True,exist_ok=True)
    temp=catalog.with_suffix('.json.tmp')
    temp.write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    os.replace(temp,catalog)
    return document


def main(argv=None):
    parser=argparse.ArgumentParser(description='Indexa materiales originales PS5 .pft/.pdr para conversiones futuras')
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    doc=scan(args.folder,args.out)
    print(json.dumps({k:v for k,v in doc.items() if k!='references'},ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
