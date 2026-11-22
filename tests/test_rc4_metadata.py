"""Synthetic global regressions; real Mercedes tested separately (not redistributed)."""
import sys, tempfile, unittest, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'motor/tools'),str(ROOT/'app')]
from gtavmenu_tools.asset_metadata import numeric_identifier, normalize_source_numeric_xml
from gtavmenu_tools.asset_formats import AssetError
from import_pc_assets import select_vehicle_metadata,mod_kit_chains
from prepare_carcols import main as prepare, point
from handling_balance import balance,balance_tuning
from test_rc3_handling_and_tuning import CAR,HAND

BIG='1002'*14
CARCOLS=f'''<CVehicleModelInfoVarGlobal><Kits><Item><kitName>{BIG}_test_modkit</kitName><id value='{BIG}'/><visibleMods><Item><modelName>bumper</modelName><linkedModels><Item>missing</Item><Item>link</Item></linkedModels><type>VMT_BUMPER_F</type></Item></visibleMods><linkMods><Item><modelName>link</modelName></Item><Item><modelName>missing</modelName></Item></linkMods><statMods><Item><type>VMT_GEARBOX</type><modifier value="80"/></Item><Item><type>VMT_HORN</type><modifier value="4294967295"/></Item></statMods></Item></Kits><Lights><Item><id value='0xFF'/></Item><Item><id value='{BIG}'/></Item></Lights><Sirens><Item><id value='4294967295'/></Item></Sirens></CVehicleModelInfoVarGlobal>'''
VAR=f'''<CVehicleModelInfoVariation><variationData><Item><modelName>teslax</modelName><kits><Item>{BIG}_test_modkit</Item></kits><lightSettings value='{BIG}'/><sirenSettings value='-1'/></Item></variationData></CVehicleModelInfoVariation>'''
class RC4Tests(unittest.TestCase):
    def test_bounded_source_ids(self):
        for raw,expected in [(BIG,BIG),('0xFF','255'),('-1','4294967295'),('000005','5'),('+42','42'),('9'*128,'9'*128)]:
            self.assertEqual(numeric_identifier(raw),expected)
        for bad in ['abc','1.2','9'*129,'-2147483649','0x'+'f'*107]:
            with self.assertRaises(AssetError):numeric_identifier(bad)
    def test_import_binds_exact_large_and_signed_ids(self):
        car=CAR.replace('<handlingId>','<txdName>teslax</txdName><layout>LAYOUT_STANDARD</layout><handlingId>')
        sources=[(str(i),v.encode(),{}) for i,v in enumerate([car,HAND,VAR,CARCOLS])]
        result,_=select_vehicle_metadata('teslax',sources)
        self.assertEqual(result['dependencies']['lightSetting']['id'],int(BIG))
        self.assertEqual(result['dependencies']['lightSetting']['status'],'selected-pack-metadata')
        self.assertEqual(result['dependencies']['sirenSetting']['status'],'selected-pack-metadata')
    def test_real_writer_reassigns_and_filters(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'c').write_text(CARCOLS);(p/'v').write_text(VAR)
            prepare(['--carcols',str(p/'c'),'--variations',str(p/'v'),'--kit-id','4609','--light-id','224','--keep-sirens','--siren-id','226','--ship-model','bumper','--ship-model','link','--handling-profile','balanced','--out-carcols',str(p/'co'),'--out-variations',str(p/'vo')])
            c=ET.parse(p/'co');v=ET.parse(p/'vo');kit=c.find('./Kits/Item')
            self.assertEqual(kit.find('id').get('value'),'4609')
            self.assertEqual(v.find('.//kits/Item').text,kit.findtext('kitName'))
            self.assertEqual(v.find('.//lightSettings').get('value'),'225')
            self.assertEqual(v.find('.//sirenSettings').get('value'),'226')
            self.assertEqual([x.text for x in kit.findall('.//linkedModels/Item')],['link'])
            self.assertEqual([x.text for x in kit.findall('./linkMods/Item/modelName')],['link'])
            self.assertEqual([x.get('value') for x in kit.findall('./statMods/Item/modifier')],['30','4294967295'])
    def test_invalid_unbound_light_fallback(self):
        v=normalize_source_numeric_xml(VAR)
        self.assertIn('lightSettings value="0"',point(v,'light',{},None,None,[]))
    def test_exact_original_tuning(self):
        self.assertEqual(balance_tuning(CARCOLS,'original'),(CARCOLS,[]))
    def test_multi_vehicle_handling_selects_model(self):
        extra='<Item><modelName>other</modelName><handlingId>OTHER</handlingId><vehicleClass>VC_SUPER</vehicleClass></Item>'
        car=CAR.replace('<InitDatas>','<InitDatas>'+extra)
        out,report=balance(HAND,car,'teslax')
        self.assertEqual(report['category'],'suv');self.assertIn('0.350000',out)
        self.assertIn('handlingName>OTHER</handlingName><fInitialDriveForce value="0.70000"',out)
    def test_uppercase_part_chain(self):
        self.assertEqual(len(mod_kit_chains('test',['X64/VEHICLEMODS/test_mods.rpf!/TEST_BUMPER.YFT'])),1)
    def test_ui_auto(self):
        self.assertIn('self.include_tuning.set(bool(count))',(ROOT/'app/conversor_gui.py').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
