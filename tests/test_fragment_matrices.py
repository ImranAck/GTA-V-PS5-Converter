import math, struct, unittest
import test_rc9_speed
from native_drawables import read, read_fragment_matrices, semantics
from gtavmenu_tools.vehicle_contracts import load
from gtavmenu_tools.asset_formats import AssetError

class FragmentMatricesTests(unittest.TestCase):
    def fixture(self):
        contract=load()['pc']['drawable']; layout=contract['drawable']; b=0x50000000
        s=bytearray(8192)
        for name,value in {'FragMatricesIndsPointer':b+512,'FragMatricesPointer':b+1024,'FragMatricesIndsCount':64,'FragMatricesCapacity':64,'FragMatricesCount':1}.items():
            f=layout['fields'][name];s[f['offset']:f['offset']+f['bytes']]=value.to_bytes(f['bytes'],'little')
        row=(math.cos(.02),-math.sin(.02),0,math.nan,math.sin(.02),math.cos(.02),0,math.nan,0,0,1,math.nan,.001,.002,.003,math.nan)
        struct.pack_into('<16f',s,1024,*row)
        s[1088:5120]=struct.pack('<16f',*([math.nan]*16))*63
        return s,b,contract
    def test_preserves_rotation_and_padding(self):
        s,b,c=self.fixture();v=read(s,b,0,c);self.assertEqual(bytes.fromhex(v['fragmentMatrices']['matrices']),s[1024:5120]);self.assertEqual(semantics(v)['fragmentMatrices'],v['fragmentMatrices'])
    def test_bad_index(self):
        s,b,c=self.fixture();struct.pack_into('<Q',s,512,1)
        with self.assertRaisesRegex(AssetError,'index'):read(s,b,0,c)
    def test_bad_active_matrix(self):
        s,b,c=self.fixture();struct.pack_into('<f',s,1024,math.nan)
        with self.assertRaisesRegex(AssetError,'spatial'):read(s,b,0,c)
    def test_outside_span(self):
        s,b,c=self.fixture()
        with self.assertRaisesRegex(AssetError,'storage'):read(s[:5000],b,0,c)
    def test_overlap(self):
        s,b,c=self.fixture();f=c['drawable']['fields']['FragMatricesIndsPointer'];struct.pack_into('<Q',s,f['offset'],b+1024)
        with self.assertRaisesRegex(AssetError,'overlap'):read(s,b,0,c)
