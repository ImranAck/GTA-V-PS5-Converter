"""Conservative, auditable balancing of obviously extreme GTA V PC addon handling.

Does not attempt 1:1 real-world horsepower or km/h. Applies only to the referenced
CHandlingData item. By default never raises a performance value, never changes steering,
traction, suspension, drivetrain bias, or model geometry. Original mode is byte-identical.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
import xml.etree.ElementTree as ET

@dataclass(frozen=True)
class Limits:
    drive: float
    top_speed: float
    brake: float
    inertia: float = 1.45

# Bounds for the GTA V engine's native handling UNITS, not real-world specifications.
BOUNDS = {
    'family': Limits(.27, 160., 1.15),
    'suv': Limits(.35, 185., 1.45),
    'sedan': Limits(.32, 180., 1.25),
    'sports': Limits(.40, 210., 1.55),
    'super': Limits(.45, 235., 1.65),
    'utility': Limits(.28, 160., 1.15),
    'general': Limits(.38, 200., 1.45),
}
CLASS_CATEGORY = {
    'VC_SUVS':'suv','VC_SUV':'suv','VC_OFF_ROAD':'suv',
    'VC_VANS':'family','VC_COMPACT':'family','VC_COMPACTS':'family',
    'VC_SEDANS':'sedan','VC_COUPE':'sports','VC_COUPES':'sports',
    'VC_SPORT':'sports','VC_SPORTS':'sports','VC_SPORT_CLASSIC':'sports','VC_SPORTS_CLASSICS':'sports','VC_MUSCLE':'sports',
    'VC_SUPER':'super','VC_SUPERS':'super',
    'VC_UTILITY':'utility','VC_INDUSTRIAL':'utility','VC_COMMERCIAL':'utility',
}
# These types are not road cars and need their own physics/handling calibration.
EXCLUDED = ('BIKE','BICYCLE','BOAT','HELI','PLANE','TRAIN')

# Only the primary road-vehicle performance controls; reverse acceleration shares drive.
CAPS = {
    'fInitialDriveForce':'drive',
    'fInitialDriveMaxFlatVel':'top_speed',
    'fBrakeForce':'brake',
    'fDriveInertia':'inertia',
}
FIELD = re.compile(r'(<(?P<key>fInitialDriveForce|fInitialDriveMaxFlatVel|fBrakeForce|fDriveInertia)\b[^>]*?\bvalue\s*=\s*["\'])(?P<value>[-+0-9.eE]+)(?P<end>["\'])', re.I)


def profile_for(vehicle_xml:str, handling_xml:str, display_name:str='',target:str='') -> tuple[str,str]:
    v=ET.fromstring(vehicle_xml)
    h=ET.fromstring(handling_xml)
    cls=(v.findtext('.//vehicleClass') or '').strip().upper()
    vehicle_type=(v.findtext('.//type') or '').upper()
    if any(tag in cls or tag in vehicle_type for tag in EXCLUDED):
        return 'excluded', cls
    # Trust the true mass over mislabelled classes (some SUV mods declare VC_COMPACTS).
    masses=[]
    for item in h.findall('.//Item'):
        if item.get('type')!='CHandlingData':continue
        if target and (item.findtext('handlingName') or '').strip().casefold()!=target:continue
        try:masses.append(float((item.find('fMass').get('value','0') if item.find('fMass') is not None else '0')))
        except ValueError:pass
    mass=max(masses,default=0)
    if mass>=2050 and cls not in ('VC_SUPER','VC_SUPERS','VC_UTILITY','VC_INDUSTRIAL'):
        return 'suv',cls
    return CLASS_CATEGORY.get(cls,'general'),cls


def balance(handling_xml:str, vehicle_xml:str, model:str, display_name:str='',mode:str='balanced') -> tuple[str,dict]:
    """Return XML and report; never infer that a specific in-game top speed is verified."""
    if mode not in ('balanced','original'):raise ValueError('Invalid handling profile')
    if mode=='original':return handling_xml, {'mode':'original','changes':[],'category':'original'}
    root=ET.fromstring(handling_xml)
    car=ET.fromstring(vehicle_xml)
    cars=[item for item in car.findall('./InitDatas/Item')
          if (item.findtext('modelName') or '').strip().casefold()==model.casefold()]
    if len(cars)!=1:
        return handling_xml, {'mode':mode,'changes':[],'category':'unbound','note':'model not uniquely defined in vehicles.meta'}
    car=cars[0]
    target=(car.findtext('handlingId') or '').strip().casefold()
    if not target:return handling_xml,{'mode':mode,'changes':[],'category':'unbound','note':'handlingId missing'}
    hits=[i for i in root.findall('.//Item') if i.get('type')=='CHandlingData' and
          (i.findtext('handlingName') or '').strip().casefold()==target]
    if len(hits)!=1:return handling_xml,{'mode':mode,'changes':[],'category':'unbound','note':'handlingId not uniquely defined in the mod'}
    category, vehicle_class=profile_for(ET.tostring(car,encoding="unicode"),handling_xml,display_name,target)
    if category=='excluded':return handling_xml,{'mode':mode,'changes':[],'category':'excluded'}
    limits=BOUNDS[category]
    # Preserve exact formatting. Target only the chosen CHandlingData item's top-level fields.
    # The item can contain nested SubHandlingData, so locate its header via handlingName, and
    # stop at the first SubHandlingData (nested cars are never modified).
    pattern=re.compile(r'<Item\s+type\s*=\s*["\']CHandlingData["\'][^>]*>',re.I)
    spans=[]
    for m in pattern.finditer(handling_xml):
        start=m.end();sub=re.search(r'<SubHandlingData\b|</Item\s*>',handling_xml[start:],re.I)
        if not sub:continue
        end=start+sub.start()
        header=handling_xml[start:end]
        n=re.search(r'<handlingName>\s*([^<]+?)\s*</handlingName>',header,re.I)
        if n and n.group(1).strip().casefold()==target:spans.append((start,end,header))
    if len(spans)!=1:
        # XML-level fallback for alternate attribute order/formatting; only direct fields.
        changes=[]
        for key, cap in CAPS.items():
            field=hits[0].find(key)
            if field is None:continue
            try:value=float(field.get('value',''))
            except ValueError:continue
            limit=getattr(limits,cap)
            if math.isfinite(value) and value>limit+1e-7:
                field.set('value',f'{limit:.6f}')
                changes.append({'field':key,'before':value,'after':limit})
        return (ET.tostring(root,encoding='unicode') if changes else handling_xml), {
            'mode':mode,'category':category,'vehicleClass':vehicle_class,'changes':changes,
            'note':'Engine-unit clamps; physical PS5 driving validation required'}
    start,end,header=spans[0]
    changes=[]
    seen=set()
    def replace(m):
        key=next(k for k in CAPS if k.casefold()==m.group('key').casefold())
        if key in seen: return m.group(0)
        seen.add(key)
        try:value=float(m.group('value'))
        except ValueError:return m.group(0)
        limit=getattr(limits,CAPS[key])
        # Never replace negative, zero, NaN, or Infinity; these need a separate validation.
        if not math.isfinite(value) or value<=0 or value<=limit+1e-7:return m.group(0)
        new=f'{limit:.6f}'
        changes.append({'field':key,'before':value,'after':limit})
        return m.group(1)+new+m.group('end')
    new_header=FIELD.sub(replace,header)
    result=handling_xml[:start]+new_header+handling_xml[end:]
    # Verify the metadata parses and all unrelated CHandlingData entries are unchanged.
    ET.fromstring(result)
    return result,{'mode':mode,'category':category,'vehicleClass':vehicle_class,
                   'changes':changes,'note':'Engine-unit clamps; physical PS5 driving validation required'}


# Conservative configurable integer ceilings for performance-only upgrade entries.
# They are GTA modifier units, not percentages or a measured speed guarantee.
TUNING_CAPS={'VMT_ENGINE':50, 'VMT_BRAKES':50, 'VMT_GEARBOX':30}

def balance_tuning(carcols_xml:str, mode:str='balanced') -> tuple[str,list[dict]]:
    if mode=='original':return carcols_xml,[]
    if mode!='balanced':raise ValueError('Invalid handling profile')
    root=ET.fromstring(carcols_xml)
    changes=[]
    for kit in root.findall('./Kits/Item'):
        for part in kit.findall('./statMods/Item'):
            kind=(part.findtext('type') or '').strip().upper()
            if kind not in TUNING_CAPS:continue
            field=part.find('modifier')
            if field is None:continue
            raw=field.get('value','').strip()
            if not re.fullmatch(r'[+]?[0-9]{1,128}',raw):continue
            value=int(raw); cap=TUNING_CAPS[kind]
            if value>cap:
                field.set('value',str(cap))
                changes.append({'kit':kit.findtext('kitName'),'type':kind,'before':value,'after':cap})
    return (ET.tostring(root,encoding='unicode') if changes else carcols_xml),changes
