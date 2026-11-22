"""Release RC3: conservative road-car handling, ZIP repacks, and opt-in tuning."""
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'motor/tools')]
from handling_balance import balance
import v3_engine

CAR="""<CVehicleModelInfo__InitDataList><InitDatas><Item><modelName>teslax</modelName><handlingId>TESLAX</handlingId><vehicleClass>VC_COMPACT</vehicleClass><type>VEHICLE_TYPE_CAR</type></Item></InitDatas></CVehicleModelInfo__InitDataList>"""
HAND="""<?xml version="1.0"?><CHandlingDataMgr><HandlingData>
<Item type="CHandlingData"><handlingName>TESLAX</handlingName><fMass value="2200.000000" />
<fInitialDriveForce value="1.100000"/><fDriveInertia value="1.000000" />
<fInitialDriveMaxFlatVel value="285.000000"/><fBrakeForce value="9.000000"/>
<fSteeringLock value="39.0"/><SubHandlingData><Item type="CCarHandlingData"><fBrakeForce value="5.00000" /></Item></SubHandlingData></Item>
<Item type="CHandlingData"><handlingName>OTHER</handlingName><fInitialDriveForce value="0.70000"/></Item>
</HandlingData></CHandlingDataMgr>"""

class HandlingReleaseChecks(unittest.TestCase):
    def test_balanced_suv_mislabeled_compact(self):
        changed,report=balance(HAND,CAR,'teslax','Model X')
        self.assertEqual(report['category'],'suv')
        self.assertEqual(len(report['changes']),3)
        self.assertIn('<fInitialDriveForce value="0.350000"',changed)
        self.assertIn('<fBrakeForce value="1.450000"',changed)
        self.assertIn('<fInitialDriveMaxFlatVel value="185.000000"',changed)
        self.assertIn('<fSteeringLock value="39.0"',changed)
        self.assertIn('fBrakeForce value="5.00000"',changed)  # nested car handling untouched
        self.assertIn('handlingName>OTHER</handlingName><fInitialDriveForce value="0.70000"',changed)
        self.assertEqual(balance(changed,CAR,'teslax')[0],changed) # idempotent
    def test_original_exact(self):
        self.assertEqual(balance(HAND,CAR,'teslax',mode='original')[0],HAND)
    def test_unbound_protects_unrelated(self):
        v=CAR.replace('TESLAX','UNKNOWN')
        self.assertEqual(balance(HAND,v,'teslax')[0],HAND)
    def test_noncar_skipped(self):
        bike=CAR.replace('VEHICLE_TYPE_CAR','VEHICLE_TYPE_BIKE')
        self.assertEqual(balance(HAND,bike,'teslax')[0],HAND)
    def test_no_raise_for_already_modest_vehicle(self):
        h=HAND.replace('1.100000','0.250000').replace('285.000000','140.000000').replace('9.000000','0.900000')
        self.assertEqual(balance(h,CAR,'teslax')[0],h)
    def test_zip_repack_does_not_reconvert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); pack='gtavmenu-teslax'
            base=f'GTAVMenu/custom/packs/{pack}/resources/'
            hb=HAND.encode();vb=CAR.encode()
            def row(tp,b,name):return '\t'.join(['data',tp,str(len(b)),hashlib.sha256(b).hexdigest(),name])
            cfg='\n'.join(['GTAVPACK,1','pack\t'+pack,
                row('HANDLING_FILE',hb,'teslax_handling.meta'),
                row('VEHICLE_METADATA_FILE',vb,'teslax_vehicles.meta')])+'\n'
            inp=root/f'{pack}-PARA-PS5.zip'
            with zipfile.ZipFile(inp,'w') as z:
                z.writestr(base+'pack.cfg',cfg)
                z.writestr(base+'teslax_handling.meta',hb)
                z.writestr(base+'teslax_vehicles.meta',vb)
                z.writestr('ANADIR-A-INSTALLED.txt',pack+'\n')
            before=hashlib.sha256(inp.read_bytes()).hexdigest()
            out,report=v3_engine.rebalance_existing_zip(inp,verify=False)
            self.assertIn('EQUILIBRADO-PARA-PS5',out.name)
            self.assertEqual(hashlib.sha256(inp.read_bytes()).hexdigest(),before)
            self.assertEqual(len(report['changes']),3)
            with zipfile.ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                new=z.read(base+'teslax_handling.meta')
                self.assertIn(b'0.350000',new)
                self.assertEqual(z.read(base+'teslax_vehicles.meta'),vb)
                self.assertEqual(z.read(base+'pack.cfg').decode().split('\t')[0],'GTAVPACK,1\npack')
            with self.assertRaises(ValueError):v3_engine.rebalance_existing_zip(inp,verify=False) # no overwrite
    def test_option_is_explicit(self):
        source=(ROOT/'app/v3_engine.py').read_text(encoding='utf-8')
        self.assertIn("if include_tuning:cmd.extend(['--mod-kit'",source)
        self.assertIn("cmd.extend(['--handling-profile',handling_mode])",source)
        self.assertIn("'handling_mode':handling_mode",source)
    def test_menu_readback_and_special_slots(self):
        source=(ROOT/'menu_patch/lsc.inc.patch').read_text(encoding='utf-8')
        self.assertIn('mod part not applied; check installed kit/part resources',source)
        self.assertIn('if (!kVehicleKitSlots[i].visual) continue;',source)

if __name__=='__main__':unittest.main()
