"""Regression tests for structure-based rear-light duplicate repair.

Synthetic PC skeletons are deliberate: tests exercise tag buckets, parent
indices, duplicate aliases and byte preservation; they do not prove a new
vehicle will load on a physical PS5.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "motor" / "tools"))
import repair_pc_duplicate_bones as d


def fixture(*, winner="boot", leaf=True, shared_name=False, tag_mismatch=False,
            bad_parent=False, extra_duplicate=False):
    layouts = d.vehicle_contracts.load()["pc"]["skeleton"]["layouts"]
    raw = bytearray(20000)
    skel, bone, node = (layouts[k] for k in ("Skeleton", "Bone", "SkeletonBoneTag"))
    base = d.SYSTEM_BASE
    def setf(layout, at, field, value):
        f = layout["fields"][field]
        raw[at + f["offset"]:at + f["offset"] + f["bytes"]] = value.to_bytes(
            f["bytes"], "little", signed=f["type"] == "Int16")
    names = ["chassis", "boot", "taillight_l", "taillight_l"]
    parents = [-1, 0, 0, 1]
    if extra_duplicate:
        names.append("taillight_l")
        parents.append(1)
    if not leaf:
        names.append("some_child")
        parents.append(2)
    if bad_parent:
        parents[2] = 3
    tags = [0, d.bone_tag("boot")] + [d.bone_tag("taillight_l")] * (2 + int(extra_duplicate))
    if not leaf:
        tags.append(d.bone_tag("some_child"))
    if tag_mismatch:
        tags[2] += 1
    count = len(names)
    bones_at, buckets_at, nodes_at, capacity = 512, 4000, 5000, 64
    for field, value in dict(BonesCount=count, BonesPointer=base+bones_at,
                             BoneTagsCapacity=capacity, BoneTagsCount=count,
                             BoneTagsPointer=base+buckets_at).items():
        setf(skel, 0, field, value)
    for index, (name, tag, parent) in enumerate(zip(names, tags, parents)):
        at = bones_at + index * bone["bytes"]
        name_at = 14000 + 48 * index
        if shared_name and index == 3:
            name_at = 14000 + 48 * 2
        else:
            raw[name_at:name_at+len(name)] = name.encode("ascii")
        for field, value in dict(NamePointer=base+name_at, Tag=tag, Index=index,
                                 Index2=index, ParentIndex=parent).items():
            setf(bone, at, field, value)
    # Bucket head insertion is the PC lookup order; alternate it to establish
    # which of the identically tagged light bones wins.
    order = list(range(count))
    if winner == "chassis":
        order = [i for i in order if i != 2] + [2]
    for index in order:
        tag = tags[index]
        at = nodes_at + index * node["bytes"]
        slot = buckets_at + (tag % capacity) * 8
        nxt = struct.unpack_from("<Q", raw, slot)[0]
        for field, value in dict(BoneTag=tag, BoneIndex=index, NextPointer=nxt).items():
            setf(node, at, field, value)
        struct.pack_into("<Q", raw, slot, base+at)
    return raw, layouts


class RearLightLeafGeneralTests(unittest.TestCase):
    def test_non_chassis_winner_and_distinct_parents(self):
        raw, layouts = fixture(winner="boot")
        before = bytes(raw)
        repairs = d.repair_skeleton(raw, 0, layouts)
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["oldName"], "taillight_l")
        self.assertEqual(repairs[0]["keptBoneIndex"], 3)
        self.assertEqual(repairs[0]["boneIndex"], 2)
        self.assertNotEqual(repairs[0]["newTag"], repairs[0]["oldTag"])
        self.assertEqual(d.repair_skeleton(raw, 0, layouts), [])
        # All parent indices, transformations, weights and drawable indices
        # survive: only the name, tag and tag-bucket table may change.
        bone = layouts["Bone"]
        at = 512 + 2*bone["bytes"]
        offset = bone["fields"]["Tag"]["offset"]
        self.assertEqual(before[at:at+offset], raw[at:at+offset])
        self.assertEqual(before[at+offset+2:at+bone["bytes"]], raw[at+offset+2:at+bone["bytes"]])

    def test_chassis_winner(self):
        raw, layouts = fixture(winner="chassis")
        rows = d.repair_skeleton(raw, 0, layouts)
        self.assertEqual(rows[0]["keptBoneIndex"], 2)
        self.assertEqual(rows[0]["boneIndex"], 3)
        self.assertEqual(d.repair_skeleton(raw, 0, layouts), [])

    def test_three_way_leaf_duplicates(self):
        raw, layouts = fixture(extra_duplicate=True)
        rows = d.repair_skeleton(raw, 0, layouts)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r['newTag'] for r in rows}), 2)
        self.assertEqual(d.repair_skeleton(raw, 0, layouts), [])

    def test_unsafe_variants_are_refused_without_saving(self):
        for case in ("nonleaf", "shared", "mismatched_tag", "self_parent"):
            kwargs = {
                "nonleaf": {"leaf": False},
                "shared": {"shared_name": True},
                "mismatched_tag": {"tag_mismatch": True},
                "self_parent": {"bad_parent": True},
            }[case]
            raw, layouts = fixture(**kwargs)
            with self.subTest(case=case), self.assertRaises(SystemExit):
                d.repair_skeleton(raw, 0, layouts)


if __name__ == "__main__":
    unittest.main()
