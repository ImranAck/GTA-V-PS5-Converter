"""Case aliases and duplicate handling records; synthetic, no third-party assets."""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'motor/tools'),str(ROOT/'app')]
from import_pc_assets import unique_item, select_vehicle_metadata
from gtavmenu_tools.asset_metadata import collapse_equivalent_handling, parse_xml
from gtavmenu_tools.asset_formats import AssetError, Limits
from handling_balance import balance
from test_rc3_handling_and_tuning import CAR,HAND


def duplicated(text=HAND, alias='TESLAX'):
    root=ET.fromstring(text)
    parent=root.find('HandlingData')
    item=ET.fromstring(ET.tostring(parent[0]))
    item.find('handlingName').text=alias
    parent.append(item)
    return ET.tostring(root,encoding='unicode')

class HandlingDuplicateTests(unittest.TestCase):
    def select(self,text,name='teslax'):
        b=text.encode();roots=[('handling.meta',b,parse_xml(b,Limits()))]
        return unique_item(roots,'CHandlingDataMgr','./HandlingData/Item','handlingName',name,fold_case=True)
    def test_two_uppercase_aliases(self):
        text=duplicated()
        self.assertEqual(self.select(text)[2].findtext('handlingName'),'TESLAX')
        out,n=collapse_equivalent_handling(text)
        self.assertEqual(n,1)
        self.assertEqual([x.findtext('handlingName') for x in ET.fromstring(out).findall('./HandlingData/Item')],['TESLAX','OTHER'])
    def test_mixed_case_and_whitespace(self):
        text=duplicated(alias=' teslax ')
        self.assertIsNotNone(self.select(text))
        self.assertEqual(collapse_equivalent_handling(text)[1],1)
    def test_different_physics_rejected(self):
        text=duplicated();root=ET.fromstring(text)
        root.find('HandlingData')[-1].find('fInitialDriveForce').set('value','2.0')
        text=ET.tostring(root,encoding='unicode')
        for action in (self.select,collapse_equivalent_handling):
            with self.assertRaisesRegex(AssetError,'conflicting handling records'):action(text)
    def test_nested_subhandling_conflict_rejected(self):
        root=ET.fromstring(duplicated())
        root.find('HandlingData')[-1].find('./SubHandlingData/Item/fBrakeForce').set('value','4')
        with self.assertRaises(AssetError):self.select(ET.tostring(root,encoding='unicode'))
    def test_unchanged_xml(self):
        self.assertEqual(collapse_equivalent_handling(HAND),(HAND,0))
    def test_balancing_after_duplicate_collapse(self):
        out,_=collapse_equivalent_handling(duplicated())
        adjusted,report=balance(out,CAR,'teslax')
        self.assertEqual(report['category'],'suv')
        self.assertEqual(len(report['changes']),3)
        self.assertIn('0.350000',adjusted)
    def test_vehicle_selection(self):
        car=CAR.replace('<handlingId>','<txdName>teslax</txdName><layout>LAYOUT_STANDARD</layout><handlingId>').replace('TESLAX</handlingId>','teslax</handlingId>')
        var='<CVehicleModelInfoVariation><variationData><Item><modelName>teslax</modelName><kits/><lightSettings value="0"/><sirenSettings value="0"/></Item></variationData></CVehicleModelInfoVariation>'
        data=[(str(i),v.encode(),{}) for i,v in enumerate([car,duplicated(),var])]
        report,_=select_vehicle_metadata('teslax',data)
        self.assertEqual(report['dependencies']['handling']['status'],'selected-pack-metadata')
if __name__=='__main__':unittest.main()
