"""Manifest selection rather than guessing which conflicting physics are wanted."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'motor/tools'),str(ROOT/'app')]
from import_pc_assets import select_vehicle_metadata, declared_metadata_roots
from gtavmenu_tools.asset_formats import AssetError
from convert_vehicle import mod_metas
from test_rc3_handling_and_tuning import CAR,HAND

CAR=CAR.replace('<handlingId>','<txdName>teslax</txdName><layout>LAYOUT_STANDARD</layout><handlingId>')
VAR='<CVehicleModelInfoVariation><variationData><Item><modelName>teslax</modelName><kits/><lightSettings value="0"/><sirenSettings value="0"/></Item></variationData></CVehicleModelInfoVariation>'
DECL='common/data/handling.meta'
OTHER=HAND.replace('1.100000','0.220000')
def manifest(*rows):
    return '<CDataFileMgr__ContentsOfDataFileXml><dataFiles>'+''.join(f'<Item><filename>dlc_x:/{p}</filename><fileType>{k}</fileType><disabled value="true"/></Item>' for k,p in rows)+'</dataFiles></CDataFileMgr__ContentsOfDataFileXml>'
def data(content=None,other=OTHER):
    rows=[(DECL,HAND),('handling.meta',other),('data/vehicles.meta',CAR),('data/carvariations.meta',VAR)]
    if content is not None:rows.append(('content.xml',content))
    return [(p,s.encode(),{}) for p,s in rows]
class ManifestTests(unittest.TestCase):
    def test_declared_physics_wins(self):
        report,fragments=select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE',DECL))))
        self.assertEqual(next(r['sourceMember'] for r in report['records'] if r['kind']=='handling'),DECL)
        self.assertIn(b'1.100000',dict(fragments)['metadata-selection/handling.item.xml'])
    def test_other_declared_wins(self):
        report,fragments=select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE','handling.meta'))))
        self.assertIn(b'0.220000',dict(fragments)['metadata-selection/handling.item.xml'])
    def test_no_manifest_still_refuses_conflict(self):
        with self.assertRaisesRegex(AssetError,'conflicting handling'): select_vehicle_metadata('teslax',data())
    def test_multideclaration_still_refuses_conflict(self):
        with self.assertRaisesRegex(AssetError,'conflicting handling'): select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE',DECL),('HANDLING_FILE','handling.meta'))))
    def test_missing_declared_does_not_use_unregistered_file(self):
        report,_=select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE','not-present.meta'))))
        self.assertEqual(report['dependencies']['handling']['status'],'external-unverified')
    def test_wrong_xml_type_refused(self):
        with self.assertRaisesRegex(AssetError,'incorrect declared metadata'):select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE','data/vehicles.meta'))))
    def test_traversal_refused(self):
        with self.assertRaisesRegex(AssetError,'invalid declared metadata path'):select_vehicle_metadata('teslax',data(manifest(('HANDLING_FILE','../handling.meta'))))
    def test_converter_selects_same_path(self):
        rows=data(manifest(('HANDLING_FILE',DECL)))
        with TemporaryDirectory() as d:
            root=Path(d)
            for p,b,_ in rows:
                f=root/'metadata'/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
            paths,_=mod_metas(root)
            self.assertEqual(paths['handling'],root/'metadata'/DECL)
    def test_vehicle_and_variation_backups_not_selected(self):
        rows=data(manifest(('HANDLING_FILE',DECL),('VEHICLE_METADATA_FILE','data/vehicles.meta'),('VEHICLE_VARIATION_FILE','data/carvariations.meta')))
        rows.extend([('backup/vehicles.meta',CAR.encode(),{}),('backup/carvariations.meta',VAR.encode(),{})])
        report,_=select_vehicle_metadata('teslax',rows)
        self.assertEqual({r['sourceMember'] for r in report['records']},{DECL,'data/vehicles.meta','data/carvariations.meta'})
if __name__=='__main__':unittest.main()
