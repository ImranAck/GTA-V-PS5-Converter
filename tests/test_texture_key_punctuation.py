"""Internal Legacy names are not archive paths; keep hash/link integrity."""
import struct
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'motor/tools'))
from gtavmenu_tools.asset_formats import AssetError, Limits, safe_name
from gtavmenu_tools.asset_textures import ResourceView, SYSTEM_BASE, GRAPHICS_BASE, inspect_legacy_dictionary
from gtavmenu_tools.hashes import joaat
from repair_pc_texture_names import fixed, rename_dictionary, rename_references

class TextureKeyTests(unittest.TestCase):
    def test_dictionary_and_reference_with_exporter_punctuation(self):
        name='paintflake_prisma_nrml?????????'
        sysbuf=bytearray(512)
        struct.pack_into('<QHHI',sysbuf,32,SYSTEM_BASE+64,1,1,0)
        struct.pack_into('<QHHI',sysbuf,48,SYSTEM_BASE+72,1,1,0)
        struct.pack_into('<I',sysbuf,64,joaat(name))
        struct.pack_into('<Q',sysbuf,72,SYSTEM_BASE+96)
        struct.pack_into('<Q',sysbuf,96+40,SYSTEM_BASE+256)
        struct.pack_into('<4HIBB',sysbuf,96+80,4,4,1,4,int.from_bytes(b'DXT5','little'),0,1)
        struct.pack_into('<Q',sysbuf,96+112,GRAPHICS_BASE)
        sysbuf[256:256+len(name)]=name.encode('ascii')
        pixels=bytes(range(16)); payload=sysbuf+pixels
        header=dict(version=13,systemBytes=512,graphicsBytes=16)
        before=inspect_legacy_dictionary(bytes(payload),header,Limits())['textures'][0]
        self.assertEqual(before['name'],name);self.assertTrue(before['linearPayloadValidated'])
        changes=rename_dictionary(payload,header)
        after=inspect_legacy_dictionary(bytes(payload),header,Limits())['textures'][0]
        self.assertEqual(after['name'],fixed(name));self.assertEqual(after['payloadSha256'],before['payloadSha256'])
        self.assertEqual(after['nameHash'],f'0x{joaat(fixed(name)):08x}');self.assertEqual(len(changes),1)
        refs=bytearray(512);struct.pack_into('<Q',refs,64+40,SYSTEM_BASE+256)
        refs[256:256+len(name)]=name.encode('ascii')
        changes=rename_references(refs,{64},{after['name'].lower()})
        self.assertFalse(changes[0]['external']);self.assertEqual(ResourceView(refs,512,0).name(SYSTEM_BASE+256),after['name'])
    def test_printable_names_and_unchanged_path_policy(self):
        for name in ('abc?','a*b','a|b','a#b','a"b','a<b>','a=b'):
            data=name.encode()+b'\0'
            self.assertEqual(ResourceView(data,len(data),0).name(SYSTEM_BASE),name)
            with self.assertRaises(AssetError):safe_name(name)
    def test_invalid_still_rejected(self):
        for raw in (b'a/b\0',b'a\\b\0',b'a:b\0',b'..\0',b' \0',b'\0',b'a\x7fb\0',b'a\x1fb\0',b'a\x81b\0',b'abc'):
            with self.subTest(raw=raw),self.assertRaises(AssetError):ResourceView(raw,len(raw),0).name(SYSTEM_BASE)
    def test_wrong_hash_not_accepted(self):
        # A logical key does not gain permission to bypass dictionary integrity.
        b=bytearray(512);struct.pack_into('<QHHI',b,32,SYSTEM_BASE+64,1,1,0);struct.pack_into('<QHHI',b,48,SYSTEM_BASE+72,1,1,0);struct.pack_into('<Q',b,72,SYSTEM_BASE+96);struct.pack_into('<Q',b,136,SYSTEM_BASE+256);b[256:259]=b'a?\0'
        with self.assertRaisesRegex(AssetError,'hash'):inspect_legacy_dictionary(bytes(b),dict(version=13,systemBytes=512,graphicsBytes=0),Limits())
