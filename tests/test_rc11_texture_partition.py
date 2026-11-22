import sys,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'motor/tools'))
from convert_pc_ytd_writer import partition_source, source_plan, planned_storage
from convert_vehicle import link_texture_chain, ConvertError
from gtavmenu_tools.asset_formats import AssetError
from repair_pc_auto import STEPS, run_repair_worker

class PartitionTests(unittest.TestCase):
    def tex(self,name,w,h,fmt='BC3'):
        return dict(name=name,width=w,height=h,format=fmt,mipLevels=1,mips=[b'marker'])
    def test_large_sets_keep_every_entry(self):
        ts=[self.tex('a',8192,8192),self.tex('b',8192,8192),self.tex('c',4096,4096),self.tex('car_sign_1',1024,1024),self.tex('car_sign_2',1024,1024)]
        groups=partition_source({'textures':ts})
        self.assertGreater(len(groups),1)
        self.assertCountEqual([id(t) for g in groups for t in g],[id(t) for t in ts])
        self.assertTrue({'car_sign_1','car_sign_2'}<={t['name'] for t in groups[0]})
        for g in groups:self.assertFalse(source_plan([planned_storage(t) for t in g])['issues'])
    def test_small_unchanged_and_duplicate_refused(self):
        ts=[self.tex('a',32,32),self.tex('b',128,128)]
        self.assertEqual(partition_source({'textures':ts}),[ts])
        with self.assertRaises(AssetError):partition_source({'textures':ts+[self.tex('A',32,32)]})
    def test_chain_preserves_existing_parent(self):
        xml='<root><InitDatas><Item><txdName>car</txdName></Item></InitDatas><txdRelationships><Item><parent>interior</parent><child>car</child></Item><Item><parent>vehshare</parent><child>interior</child></Item></txdRelationships></root>'
        root=ET.fromstring(link_texture_chain(xml,'car',['gmcar_tx1','gmcar_tx2']))
        self.assertEqual({i.findtext('child'):i.findtext('parent') for i in root.findall('./txdRelationships/Item')},{'car':'gmcar_tx1','gmcar_tx1':'gmcar_tx2','gmcar_tx2':'interior','interior':'vehshare'})
        with self.assertRaises(ConvertError):link_texture_chain(xml,'car',['interior'])
    def test_repair_order(self):
        names=[x[0] for x in STEPS]; self.assertLess(names.index('pose-precision'),names.index('triangle-counts'))
    def test_worker_cli_restore(self):
        script=Path(__file__).resolve().parents[1]/'motor/tools/repair_pc_triangle_counts.py';old=sys.argv[:];path=sys.path[:];cwd=Path.cwd();r=run_repair_worker([sys.executable,str(script),'--help']);self.assertEqual(r.returncode,0);self.assertIn('--fixture',r.stdout);self.assertEqual(sys.argv,old);self.assertEqual(sys.path,path);self.assertEqual(Path.cwd(),cwd)
