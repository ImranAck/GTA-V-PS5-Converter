import random, struct, sys, unittest
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'motor'/'tools'))
from fast_binary_checks import pointer_in, aligned_targets, selected_counts, diff_count, changed_outside
from prepare_vehicle_layouts import repair_entry_variations

class FastChecks(unittest.TestCase):
    def test_reference_equivalence(self):
        rng=random.Random(918)
        for _ in range(100):
            values=[rng.choice([0,0x50000000+rng.randrange(0,800,8),rng.randrange(2**64)]) for i in range(100)]
            raw=struct.pack('<100Q',*values)+b'abc'; size=800
            lo,hi=0x50000010,0x50000100
            self.assertEqual(pointer_in(raw,size,lo,hi),any(lo<=v<hi for v in values))
            self.assertEqual(aligned_targets(raw,size,0x50000000,16),{v-0x50000000 for v in values if 0x50000000<=v<0x50000000+size and v%16==0})
            keys=[0,0x50000000,0x50000010]
            self.assertEqual(selected_counts(raw,size,keys),Counter(v for v in values if v in keys))
            new=bytearray(raw); new[5]^=1;new[17]^=2
            self.assertEqual(diff_count(raw,new),2)
            self.assertFalse(changed_outside(raw,new,len(raw),[(4,8),(16,20)]))
            self.assertTrue(changed_outside(raw,new,len(raw),[(4,8)]))
    def test_chunk_boundary(self):
        raw=bytearray((1<<20)*8+8);struct.pack_into('<Q',raw,len(raw)-8,0x50000010)
        self.assertTrue(pointer_in(raw,len(raw),0x50000000,0x50000020))
        self.assertEqual(selected_counts(raw,len(raw),[0x50000010]),{0x50000010:1})
        self.assertEqual(aligned_targets(raw,len(raw),0x50000000,16),{16})
    def test_layout_unique_vs_ambiguous(self):
        def rec(name,ref):
            return f'<Item><Name>{name}</Name><CommonClipSetMap ref="c"/><EntryClipSetMap ref="e"/><ExitClipSetMap ref="x"/><AlternateTryLockedDoorClipId>l</AlternateTryLockedDoorClipId><AlternateForcedEntryClipId>f</AlternateForcedEntryClipId><AlternateEntryPointClipSetId>a</AlternateEntryPointClipSetId><EnterVehicleMoveNetwork>n</EnterVehicleMoveNetwork><EntryAnimVariations ref="{ref}"/></Item>'
        def xml(items):return '<CVehicleMetadataMgr><VehicleEntryPointAnimInfos>'+items+'</VehicleEntryPointAnimInfos><Variations><Item><Name>stock</Name></Item><Item><Name>other</Name></Item></Variations></CVehicleMetadataMgr>'
        src=xml(rec('custom','missing'));stock=xml(rec('normal','stock'))
        out,notes=repair_entry_variations(src,stock);self.assertIn('ref="stock"',out);self.assertEqual(len(notes),1)
        self.assertEqual(repair_entry_variations(src,xml(rec('normal','stock')+rec('normal2','other'))),(src,[]))
        self.assertEqual(repair_entry_variations(src,stock.replace('>a<','>different<')),(src,[]))

class GeneralSkeletonTests(unittest.TestCase):
    def fixture(self, child=False, distinct_tags=False):
        import repair_pc_duplicate_bones as d
        layouts=d.vehicle_contracts.load()['pc']['skeleton']['layouts'];raw=bytearray(8192)
        skel=layouts['Skeleton'];bone=layouts['Bone'];taglayout=layouts['SkeletonBoneTag'];base=d.SYSTEM_BASE
        def setfield(layout,at,k,value):
            f=layout['fields'][k];raw[at+f['offset']:at+f['offset']+f['bytes']]=int(value).to_bytes(f['bytes'],'little',signed=f['type']=='Int16')
        names=['chassis','customlamp','customlamp']+(['child'] if child else [])
        tags=[0,1234,1235 if distinct_tags else 1234]+([2345] if child else [])
        parents=[-1,0,0]+([1] if child else [])
        bones_at=512;bucket_at=2048;nodes_at=2200;capacity=8
        for k,v in {'BonesCount':len(names),'BonesPointer':base+bones_at,'BoneTagsCapacity':capacity,'BoneTagsCount':len(names),'BoneTagsPointer':base+bucket_at}.items():setfield(skel,0,k,v)
        for i,(name,t,parent) in enumerate(zip(names,tags,parents)):
            addr=bones_at+i*bone['bytes'];name_at=3200+32*i;raw[name_at:name_at+len(name)]=name.encode('ascii')
            for k,v in {'NamePointer':base+name_at,'Tag':t,'Index':i,'Index2':i,'ParentIndex':parent}.items():setfield(bone,addr,k,v)
            at=nodes_at+i*taglayout['bytes'];bucket=bucket_at+(t%capacity)*8
            nextptr=struct.unpack_from('<Q',raw,bucket)[0]
            for k,v in {'BoneTag':t,'BoneIndex':i,'NextPointer':nextptr}.items():setfield(taglayout,at,k,v)
            struct.pack_into('<Q',raw,bucket,base+at)
        return d,raw,layouts
    def test_same_tag_leaf_preserves_winner(self):
        d,raw,layouts=self.fixture();rows=d.repair_skeleton(raw,0,layouts)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['oldTag'],1234)
        self.assertEqual(rows[0]['keptBoneIndex'],2);self.assertEqual(rows[0]['boneIndex'],1)
        self.assertEqual(d.repair_skeleton(raw,0,layouts),[])
    def test_ambiguous_skeleton_refused(self):
        for kw in ({'child':True},{'distinct_tags':True}):
            d,raw,layouts=self.fixture(**kw)
            with self.assertRaises(SystemExit):d.repair_skeleton(raw,0,layouts)

class BatchProgressTests(unittest.TestCase):
    def test_batch_progress_waits_for_success(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from progress_v4 import StageProgress
        messages=[];tracker=StageProgress(lambda n,s:messages.append((n,s)),expected_steps=24)
        tracker.line('[16] tuning model split and LOD batch')
        tracker.line('PERF_TUNING_BATCH workers=4 count=2 persistent=1')
        tracker.line('TUNING_PART_OK bumper seconds=0.1')
        self.assertIn('1/2',messages[-1][1]);tracker.line('TUNING_PART_OK spoiler seconds=0.1')
        self.assertIn('2/2',messages[-1][1]);self.assertLess(tracker.percent,100)
        tracker.line('[24] validate target pack');self.assertEqual(tracker.percent,99)
        tracker.complete();self.assertEqual(tracker.percent,100)
