import struct, unittest, zlib
from unittest.mock import patch
import test_rc9_speed

class V100Tests(unittest.TestCase):
    def two_bones(self, invalid=False):
        d,raw,l=test_rc9_speed.GeneralSkeletonTests().fixture()
        sk=d.read_fields(raw,0,l['Skeleton']); b=sk['BonesPointer']-d.SYSTEM_BASE; n=l['Bone']['bytes']; name='attachment_01';tag=47123
        d.write_field(raw,0,l['Skeleton'],'BonesCount',2);d.write_field(raw,0,l['Skeleton'],'BoneTagsCount',2)
        for i,t in enumerate((0,tag)):
            at=b+i*n; fields=d.read_fields(raw,at,l['Bone']);pos=fields['NamePointer']-d.SYSTEM_BASE
            raw[pos:pos+32]=name.encode()+bytes(32-len(name))
            d.write_field(raw,at,l['Bone'],'Tag',t)
        if invalid:
            d.write_field(raw,b+n,l['Bone'],'Tag',0);tag=0
        cap=sk['BoneTagsCapacity']; buckets=sk['BoneTagsPointer']-d.SYSTEM_BASE;raw[buckets:buckets+cap*8]=bytes(cap*8)
        for i,t in enumerate((0,tag)):
            node=2200+i*l['SkeletonBoneTag']['bytes'];bucket=buckets+(t%cap)*8
            d.write_field(raw,node,l['SkeletonBoneTag'],'BoneTag',t);d.write_field(raw,node,l['SkeletonBoneTag'],'NextPointer',struct.unpack_from('<Q',raw,bucket)[0]);struct.pack_into('<Q',raw,bucket,d.SYSTEM_BASE+node)
        return d,raw,l
    def test_root_name_only(self):
        d,raw,l=self.two_bones();old=bytes(raw);r=d.repair_skeleton(raw,0,l)
        self.assertEqual(len(r),1);self.assertEqual(r[0]['oldTag'],r[0]['newTag']);self.assertEqual(r[0]['boneIndex'],0)
        self.assertEqual(old[:3200],raw[:3200]);self.assertEqual(old[3232:],raw[3232:]);self.assertEqual(d.repair_skeleton(raw,0,l),[])
    def test_root_ambiguous_tags_refused(self):
        d,raw,l=self.two_bones(True)
        with self.assertRaises(SystemExit):d.repair_skeleton(raw,0,l)
    def test_decode_cache(self):
        from gtavmenu_tools import asset_formats as a
        raw=b'a'*512;pack=zlib.compressobj(1,zlib.DEFLATED,-15);blob=struct.pack('<4sIII',b'RSC7',0,0x08000000,0)+pack.compress(raw)+pack.flush()
        a.configure_decode_cache(1024*1024)
        try:
            with patch.object(a,'inflate_raw',wraps=a.inflate_raw) as inflate:
                h,p=a.decode_resource(blob,512);h['systemBytes']=1
                self.assertEqual(a.decode_resource(bytes(bytearray(blob)),512)[1],raw)
                self.assertEqual(a.decode_resource(blob,512)[0]['systemBytes'],512)
                self.assertEqual(inflate.call_count,1)
                with self.assertRaises(a.AssetError):a.decode_resource(blob,511)
                with self.assertRaises(a.AssetError):a.decode_resource(blob[:-1],512)
        finally:a.configure_decode_cache()
    def test_common_translation_guard(self):
        from repair_pc_pose_precision import repair_shared_root_translation,SYSTEM_BASE
        identity=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
        matrix=identity[:];matrix[12]=1.;raw=bytearray(struct.pack('<32f',*(matrix+matrix)))
        sk={'bones':[{},{}],'parents':[-1,0],'header':{'TransformationsInvertedPointer':SYSTEM_BASE}}
        pose={'rejections':[{'boneIndex':0},{'boneIndex':1}],'bones':[{'name':str(i),'localComparison':{'mismatches':[]},'inverseBindTimesGlobalComparison':{'mismatches':[{'field':'M41'}]},'globalPose':identity} for i in range(2)]}
        skin={'geometries':[{'streams':[{'vertexVisits':10,'rigidBoneVertices':[{'boneIndex':0,'vertices':10}]}]}]}
        self.assertEqual(len(repair_shared_root_translation(raw,sk,pose,skin)),2);self.assertEqual(struct.unpack('<32f',raw),tuple(identity+identity))
        raw=bytearray(struct.pack('<32f',*(matrix+matrix)));struct.pack_into('<f',raw,112,2.)
        old=bytes(raw)
        with self.assertRaises(SystemExit):repair_shared_root_translation(raw,sk,pose,skin)
        self.assertEqual(raw,old)
