import unittest,struct
import test_rc9_speed

class HashCollisionTests(unittest.TestCase):
    def make_collision(self, noncanonical=False, child=False, pair=None):
        d,raw,l=test_rc9_speed.GeneralSkeletonTests().fixture(child=child)
        sk=d.read_fields(raw,0,l['Skeleton']); base=d.SYSTEM_BASE
        a,b=pair or ('door_pside_f_refl','door_dside_r_refl');tag=d.bone_tag(a)
        self.assertEqual(tag,d.bone_tag(b));self.assertNotEqual(a,b)
        if noncanonical:tag+=1
        for i,name in ((1,a),(2,b)):
            at=sk['BonesPointer']-base+i*l['Bone']['bytes'];fields=d.read_fields(raw,at,l['Bone']);p=fields['NamePointer']-base
            raw[p:p+32]=name.encode()+bytes(32-len(name));d.write_field(raw,at,l['Bone'],'Tag',tag)
        # Rebuild bucket chains from the fixture's original node locations.
        nodes=2200; buckets=sk['BoneTagsPointer']-base;cap=sk['BoneTagsCapacity'];raw[buckets:buckets+cap*8]=bytes(cap*8)
        for i in range(sk['BonesCount']):
            n=nodes+i*l['SkeletonBoneTag']['bytes'];bt=d.read_fields(raw,sk['BonesPointer']-base+i*l['Bone']['bytes'],l['Bone'])['Tag'];q=buckets+(bt%cap)*8
            d.write_field(raw,n,l['SkeletonBoneTag'],'BoneTag',bt);d.write_field(raw,n,l['SkeletonBoneTag'],'NextPointer',struct.unpack_from('<Q',raw,q)[0]);struct.pack_into('<Q',raw,q,base+n)
        return d,raw,l,tag
    def test_canonical_collision_preserves_lookup(self):
        d,raw,l,tag=self.make_collision();rows=d.repair_skeleton(raw,0,l)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['boneIndex'],1);self.assertEqual(rows[0]['keptBoneIndex'],2);self.assertEqual(rows[0]['oldTag'],tag);self.assertNotEqual(rows[0]['newTag'],tag)
        self.assertEqual(d.repair_skeleton(raw,0,l),[])
    def test_refuses_noncanonical_and_nonleaf(self):
        for kw in ({'noncanonical':True},{'child':True}):
            d,raw,l,t=self.make_collision(**kw)
            with self.assertRaises(SystemExit):d.repair_skeleton(raw,0,l)

    def test_generated_unseen_names(self):
        import random
        d,_,_=test_rc9_speed.GeneralSkeletonTests().fixture()
        rng=random.Random(81023);seen={};pairs=[]
        for _ in range(20000):
            name='slot_'+''.join(rng.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(10))
            tag=d.bone_tag(name)
            if tag in seen and seen[tag]!=name:
                pairs.append((seen[tag],name))
                if len(pairs)==100:break
            seen[tag]=name
        self.assertEqual(len(pairs),100)
        for pair in pairs:
            d,raw,l,tag=self.make_collision(pair=pair);before=bytes(raw)
            rows=d.repair_skeleton(raw,0,l);self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['keptBoneIndex'],2)
            self.assertEqual(d.repair_skeleton(raw,0,l),[])
            # Nothing in the bone record but its Tag may change; names and
            # tag-table nodes are separate from the transforms/parent data.
            sk=d.read_fields(raw,0,l['Skeleton']);at=sk['BonesPointer']-d.SYSTEM_BASE
            size=l['Bone']['bytes'];off=l['Bone']['fields']['Tag']['offset']
            permitted=set(range(at+size+off,at+size+off+2))
            self.assertTrue(all(before[i]==raw[i] or i in permitted for i in range(at,at+3*size)))

    def test_embedded_graphics_pointer_scan(self):
        import random
        from repair_pc_embedded_textures import graphics_words, GRAPHICS_BASE
        rng=random.Random(6723)
        values=[rng.choice([GRAPHICS_BASE+rng.randrange(0,8192),rng.randrange(2**64)]) for _ in range(5000)]
        raw=struct.pack('<5000Q',*values)+b'xyz';skip=(91,1802)
        expected={i*8 for i,v in enumerate(values) if GRAPHICS_BASE<=v<GRAPHICS_BASE+4096 and not skip[0]<=i*8<skip[1]}
        self.assertEqual(graphics_words(raw,4096,skip),expected)
        self.assertEqual(graphics_words(memoryview(raw),4096,skip),expected)

    def test_embedded_sidecar_names_are_fixed_together(self):
        from unittest.mock import patch
        import repair_pc_embedded_textures as e
        textures=[{'name':'led bleu','format':'DXT1','width':4,'height':4,'mips':[b'a']},
                  {'name':'led_bleu','format':'DXT1','width':4,'height':4,'mips':[b'b']}]
        with patch.object(e,'embedded_textures',return_value=textures), patch.object(e,'system_only',return_value=(b'system',2)) as sys, patch.object(e,'renamed_original',return_value=b'original') as orig:
            _,_,names,renames=e.plan_fragment(b'x',{})
            self.assertEqual(len(set(names)),2);self.assertTrue(all(' ' not in n for n in names));self.assertEqual(sys.call_args.args[1],orig.call_args.args[1]);self.assertIn('led bleu',renames)
