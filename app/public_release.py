"""Release metadata, honest static QA and private support reporting."""
from __future__ import annotations
import json
import platform
import re
import statistics
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

VERSION='1.0.2d'
APP_TITLE='GTA V PS5 Converter '+VERSION

# Evidence is kept separate: toolchain JSON is not proof on every game edition.
COMPATIBILITY={
    'tested_user_environment': {
        'game':'GTA V PS5', 'title_id':'PPSA04263',
        'content_version':'01.010.002',
        'note':'Reported by an original tester using a backport and a modified menu; not a universal compatibility guarantee.'
    },
    'unverified': 'Other editions, updates, menus, unmodified consoles and setups without the tested backport.',
    'target_manifest_note':'The engine also contains PPSA04264 disc manifests; these do not establish PPSA04263 compatibility.'
}

FEATURES=('Paint','Customization/tuning','Wheels','Doors and trunk','Lights','Damage','LOD and distance','Audio','Handling')


def inspect_pack(path:Path)->dict:
    """Only identifies files and obligations. Does not claim PS5 gameplay tests."""
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        configs=[n for n in names if n.endswith('/resources/pack.cfg')]
        if len(configs)!=1:
            raise ValueError('The ZIP must include exactly one pack.cfg.')
        cfg=z.read(configs[0]).decode('utf-8-sig',errors='replace')
        files={Path(n).name.lower() for n in names}
        partial_notes = []
        if 'AVISO-CONVERSION-PARCIAL.txt' in names:
            partial_notes = [line.strip() for line in z.read('AVISO-CONVERSION-PARCIAL.txt').decode('utf-8',errors='replace').splitlines()
                             if line.startswith(('WARNING_TUNING_EXCLUDED:', 'WARNING_OPTIONAL_EXCLUDED:'))]
        result={
            'conversion_status':'PARCIAL_CON_OMISIONES' if partial_notes else 'VALIDACION_ESTRUCTURAL',
            'omitted_optional_items':partial_notes,
            'schema':1,'version':VERSION,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'pack':Path(configs[0]).parts[3],
            'static_checks':{
                'pack_cfg':True,
                'resource_rpf':any(n.endswith('.rpf') for n in files),
                'handling_meta':any(n.endswith('_handling.meta') for n in files),
                'vehicles_meta':any(n.endswith('_vehicles.meta') for n in files),
                'carcols_meta':any(n=='carcols.meta' or n.endswith('_carcols.meta') for n in files),
                'carvariations_meta':any(n.endswith('_carvariations_kit.meta') or n.endswith('_carvariations.meta') for n in files),
                'pack_manifest':cfg.startswith('GTAVPACK,1')
            },
            'gameplay_checks':{name:'PENDING PS5 GAMEPLAY TEST' for name in (('Wheels', 'GTAV Menu LS Customs selection') if not any(n.endswith('_vehicles.meta') for n in files) and any(n=='carcols.meta' for n in files) else FEATURES)},
            'note':'Only resource structure was checked; paint, tuning, wheels, collisions, audio and console loading are not proven.'
        }
        return result


def qa_report(path:Path,out:Path)->Path:
    record=inspect_pack(path)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out


# Keep technical timing/error hints but NEVER include raw Windows/macOS paths or IPs.
_PRIVATE_PATH=re.compile(r"(?i)(?:[a-z]:\\[^'\"\r\n]+|/(?:home|Users|mnt|data)/[^'\"\r\n]+)")
_PRIVATE_IP=re.compile(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')
_EMAIL=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')


def redact(message:str)->str:
    message=str(message)
    # Normalise double backslashes as found in JSON logging before redaction.
    message=message.replace('\\\\','\\')
    message=_PRIVATE_PATH.sub('[PRIVATE_PATH]',message)
    message=_PRIVATE_IP.sub('[PRIVATE_IP]',message)
    message=_EMAIL.sub('[PRIVATE_EMAIL]',message)
    return message


def friendly_error(message:str)->str:
    low=message.lower()
    if 'replace' in low and 'dlc.rpf' in low:
        return 'This mod has no PC Legacy add-on (dlc.rpf). Replace conversion is not available in this build.'
    if 'shader' in low and ('unsupported' in low or 'no cubre' in low):
        return 'PS5 material references are missing. Index models from your own game; materials will not be substituted blindly.'
    if 'lightsettings' in low or 'carcols' in low:
        return 'This mod contains light or customization settings that need verification. Review the technical report.'
    if 'skeleton' in low or 'bone tag' in low or 'tag collision' in low or 'duplicate bone' in low:
        return 'The vehicle skeleton has bone IDs or links that could not be repaired safely. An incomplete model will not be installed. Export the diagnostic report without sharing the mod.'
    if 'triangle' in low or 'collision' in low or 'geometry' in low:
        return 'Automatic repair could not validate the model geometry or collision data. Keep the job files for diagnosis.'
    if 'dictionary' in low or 'texture' in low or 'diccionario' in low:
        return 'The texture dictionary exceeds a writer limit or contains an unsupported format. Texture quality will not be silently reduced.'
    if 'ftp' in low or '550' in low or 'connection' in low:
        return 'FTP could not be completed. Check the PS5 server IP, port and backup status.'
    return 'Operation stopped. The diagnostic log identifies the failed stage without modifying your original resources.'


def export_support(messages:list[str],destination:Path,extra:dict|None=None)->Path:
    """Text report; paths, private IPs and email addresses are redacted.

    Do not include hidden original shaders or unmodified proprietary bytes.
    """
    extra=extra or {}
    report={
        'application':APP_TITLE,
        'platform':platform.system()+' '+platform.release(),
        'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'notes':'Private paths, IP addresses and email addresses have been masked. Review the report before sharing.',
        'compatible_user_environment':COMPATIBILITY['tested_user_environment']['content_version'],
        'messages':[redact(m)[:800] for m in messages[-2000:]],
        'metadata':{str(k)[:40]:redact(str(v))[:200] for k,v in extra.items()}
    }
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return destination


def record_duration(cache:Path,seconds:float)->None:
    if not 0<seconds<7200:return
    file=cache/'duraciones-publicas.json'
    try:records=json.loads(file.read_text(encoding='utf-8'))
    except (OSError,ValueError):records=[]
    records=[float(x) for x in records if isinstance(x,(int,float)) and 0<float(x)<7200][-29:]
    records.append(round(seconds,2))
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(records)+'\n',encoding='utf-8')


def median_duration(cache:Path):
    try:
        rows=json.loads((cache/'duraciones-publicas.json').read_text(encoding='utf-8'))
        if len(rows)<3:return None
        return statistics.median(float(x) for x in rows[-15:])
    except (OSError,ValueError,TypeError):return None
