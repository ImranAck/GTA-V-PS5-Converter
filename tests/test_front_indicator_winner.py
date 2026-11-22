"""Front-indicator duplicate regression tests for both authentic lookup orders.

Uses synthetic resource skeletons: this is not a PS5 gameplay verification.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "motor" / "tools"))
import repair_pc_duplicate_bones as d


def fixture(*, name="indicator_lf", winner="chassis", with_child=False,
            shared_storage=False, wrong_tag=False, invalid_parent=False):
    layouts = d.vehicle_contracts.load()["pc"]["skeleton"]["layouts"]
    raw = bytearray(24000)
    skel, bone, node = (layouts[k] for k in ("Skeleton", "Bone", "SkeletonBoneTag"))
    base = d.SYSTEM_BASE

    def setf(layout, at, field, value):
        f = layout["fields"][field]
        raw[at + f["offset"]:at + f["offset"] + f["bytes"]] = value.to_bytes(
            f["bytes"], "little", signed=f["type"] == "Int16")

    door = "door_dside_f" if name == "indicator_lf" else "door_pside_f"
    names = ["chassis", door, name, name]
    parents = [-1, 0, 0, 1]
    tags = [0, d.bone_tag(door), d.bone_tag(name), d.bone_tag(name)]
    if with_child:
        names.append("indicator_child")
        parents.append(3)
        tags.append(d.bone_tag("indicator_child"))
    if invalid_parent:
        parents[3] = 100
    if wrong_tag:
        tags[3] += 1

    count = len(names)
    bones_at, buckets_at, nodes_at, capacity = 512, 4000, 5000, 64
    for field, value in dict(BonesCount=count, BonesPointer=base + bones_at,
                             BoneTagsCapacity=capacity, BoneTagsCount=count,
                             BoneTagsPointer=base + buckets_at).items():
        setf(skel, 0, field, value)

    for index, (name_item, tag, parent) in enumerate(zip(names, tags, parents)):
        at = bones_at + index * bone["bytes"]
        name_at = 14000 + index * 48
        if shared_storage and index == 3:
            name_at = 14000 + 2 * 48
        else:
            raw[name_at:name_at + len(name_item)] = name_item.encode("ascii")
        for field, value in dict(NamePointer=base + name_at, Tag=tag, Index=index,
                                 Index2=index, ParentIndex=parent).items():
            setf(bone, at, field, value)

    # Head-insertion in the bucket determines which duplicate is resolved.
    indices = list(range(count))
    if winner == "chassis":
        indices = [i for i in indices if i != 2] + [2]
    else:
        indices = [i for i in indices if i != 3] + [3]
    for index in indices:
        tag = tags[index]
        at = nodes_at + index * node["bytes"]
        slot = buckets_at + tag % capacity * 8
        nxt = struct.unpack_from("<Q", raw, slot)[0]
        for field, value in dict(BoneTag=tag, BoneIndex=index, NextPointer=nxt).items():
            setf(node, at, field, value)
        struct.pack_into("<Q", raw, slot, base + at)
    return raw, layouts


class TestFrontIndicatorWinners(unittest.TestCase):
    def test_chassis_winner_preserves_lookup_and_kinematics(self):
        for name in ("indicator_lf", "indicator_rf"):
            with self.subTest(name=name):
                raw, layouts = fixture(name=name, winner="chassis")
                initial = bytes(raw)
                rows = d.repair_skeleton(raw, 0, layouts)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["boneIndex"], 3)
                self.assertEqual(rows[0]["keptBoneIndex"], 2)
                self.assertEqual(rows[0]["oldTag"], d.bone_tag(name))
                self.assertEqual(rows[0]["newTag"], d.bone_tag(rows[0]["newName"]))
                self.assertEqual(len(rows[0]["newName"]), len(name))
                self.assertNotEqual(rows[0]["newName"], name)
                self.assertEqual(d.repair_skeleton(raw, 0, layouts), [])
                bone = layouts["Bone"]
                at = 512 + 3 * bone["bytes"]
                off = bone["fields"]["Tag"]["offset"]
                self.assertEqual(initial[at:at + off], raw[at:at + off])
                self.assertEqual(initial[at + off + 2:at + bone["bytes"]],
                                 raw[at + off + 2:at + bone["bytes"]])

    def test_door_winner_unchanged_regression(self):
        for name, alias in (("indicator_lf", "indicator_lc"),
                            ("indicator_rf", "indicator_rc")):
            with self.subTest(name=name):
                raw, layouts = fixture(name=name, winner="door")
                rows = d.repair_skeleton(raw, 0, layouts)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["boneIndex"], 2)
                self.assertEqual(rows[0]["keptBoneIndex"], 3)
                self.assertEqual(rows[0]["newName"], alias)
                self.assertEqual(d.repair_skeleton(raw, 0, layouts), [])

    def test_unsafe_winner_topologies_refused(self):
        for case in ("with_child", "shared_storage", "wrong_tag", "invalid_parent"):
            raw, layouts = fixture(winner="chassis", **{case: True})
            initial = bytes(raw)
            with self.subTest(case=case), self.assertRaises(SystemExit):
                d.repair_skeleton(raw, 0, layouts)
            self.assertEqual(raw, initial, "unsafe case must not mutate source buffer")


if __name__ == "__main__":
    unittest.main()
