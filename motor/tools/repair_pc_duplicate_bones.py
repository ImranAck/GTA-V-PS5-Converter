#!/usr/bin/env python3
"""Rename duplicate lettered bones in an imported PC fixture to the next free letter.

The Prototipo police car (protopolice.yft and _hi) has two bones named misc_a (indices 57 and 60,
both children of chassis, both tag 58614, separate name strings). The skeleton reader refuses
duplicate bone names or tags ("skeleton duplicate bone tags or names are ambiguous"). On PC a tag
lookup walks its tag bucket and takes the first node: bucket 10 holds bone 60 before bone 57, so
every lookup of misc_a (physics children, mods, scripts) reached bone 60 and bone 57 was reachable
only by index (drawing). This tool keeps that: the bone the tag chain reaches first keeps its name
and tag; each other bone of the group is renamed in place to the same name with the next free last
letter (misc_a -> misc_b, same length, its own name string) and given that name's tag, and its tag
node moves to the head of the new tag's bucket. Index-based bindings (geometry palettes, parents,
transforms) do not change. Refused unless:
  - the name is a generic lettered slot (misc_a .. misc_z) and a free letter exists; a semantic name
    (door_dside_f, neon_l) is never renamed,
  - the bone's name string is not shared with another bone,
  - the skeleton's tags follow ElfHash(UPPER(name)) % 0xFE8F + 0x170 for the duplicated name and the
    new tag is unused (the renamed bone gets the tag the game derives from its new name).
The repaired fixture must pass the skeleton reader; the original stays intact and the manifest
records each rename.

  repair_pc_duplicate_bones.py --fixture build/assets/convert-<id>/fixtures/protopolice-import \\
      --material-report <its material report> --output <new fixture>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import inspect_pc_vehicle_pose as mesh_runner  # noqa: E402
from gtavmenu_tools import vehicle_contracts  # noqa: E402
from gtavmenu_tools.asset_formats import Limits, decode_resource  # noqa: E402
from gtavmenu_tools.vehicle_repair_inputs import FixtureError, copy_fixture, validate_fixture  # noqa: E402
from repair_pc_seat_mirror import SYSTEM_BASE, pc_walk_args  # noqa: E402

LETTERED = re.compile(r"(misc_)([a-z])")  # generic slots misc_a..misc_z
# An explicitly inspected 2025 BMW M4 Legacy export has front indicator bones on both
# the chassis and the front doors. Only this exact two-bone topology is permitted.
SEMANTIC_ALIASES = {
    "indicator_lf": ("chassis", "door_dside_f", "indicator_lc"),
    "indicator_rf": ("chassis", "door_pside_f", "indicator_rc"),
}
# Renault Espace V "pacev" Legacy export. Six duplicated rear light bones
# have one leaf under the boot and one leaf under chassis. PC name/tag lookup
# resolves the chassis member. Keep that member unmodified and rename only
# the index-bound boot member; do not alter hierarchy or geometry indexes.
# This is NOT a generic semantic bone repair rule.
PACEV_REAR_BONES = {
    "taillight_l": (29, 37, "taillight_x"),
    "taillight_r": (30, 38, "taillight_y"),
    "indicator_rr": (31, 39, "indicator_br"),
    "indicator_lr": (32, 41, "indicator_bl"),
    "reversinglight_l": (33, 40, "reversinglight_x"),
    "reversinglight_r": (34, 42, "reversinglight_y"),
}

# Structural rear-light fallback. Preserve the original PC tag-chain winner
# regardless of which physical parent owns it. Some vehicle exporters attach
# tail lights to a boot, bumper, chassis or a custom animated parent. Parent
# *names* are not evidence that a bone may safely be renamed: require that the
# duplicated bones are terminal leaves, have an identical canonical name/tag,
# own distinct name strings and that every parent index is a valid bone.
# No parent, transform, weight, drawable index or winning tag is changed.
# This is NOT a blanket renamer for all duplicate semantic bones.
REAR_LIGHT_NAMES = frozenset({
    "taillight_l", "taillight_r", "brakelight_l", "brakelight_r",
    "indicator_lr", "indicator_rr", "reversinglight_l", "reversinglight_r",
})

RESOURCE_LIMIT = 256 * 1024 * 1024


def elf_hash(text: str) -> int:
    value = 0
    for byte in text.encode("ascii"):
        value = ((value << 4) + byte) & 0xFFFFFFFF
        high = value & 0xF0000000
        if high:
            value ^= high >> 24
        value &= ~high & 0xFFFFFFFF
    return value


def bone_tag(name: str) -> int:
    """The tag the game derives from a bone name (matches every non-root bone of the PC vehicles seen)."""
    return elf_hash(name.upper()) % 0xFE8F + 0x170


def read_fields(raw: bytes | bytearray, at: int, layout: dict) -> dict:
    out = {}
    for name, spec in layout["fields"].items():
        if spec["type"] in ("Single", "Vector3", "Vector4"):
            continue
        start, size = at + spec["offset"], spec["bytes"]
        if start < 0 or start + size > len(raw):
            raise SystemExit("skeleton field exceeds resource bounds")
        chunk = raw[start : start + size]
        out[name] = int.from_bytes(chunk, "little", signed=spec["type"] == "Int16")
    return out


def write_field(raw: bytearray, at: int, layout: dict, name: str, value: int) -> None:
    spec = layout["fields"][name]
    raw[at + spec["offset"] : at + spec["offset"] + spec["bytes"]] = value.to_bytes(spec["bytes"], "little")


def repair_skeleton(raw: bytearray, skeleton_at: int, layouts: dict) -> list[dict]:
    """Rename every duplicate bone except the one its tag chain reaches first; returns the renames."""
    skel = read_fields(raw, skeleton_at, layouts["Skeleton"])
    count, bone_bytes = skel["BonesCount"], layouts["Bone"]["bytes"]
    if not 0 < count <= Limits().max_entries:
        raise SystemExit("skeleton bone count is empty or exceeds limit")
    bones_at = skel["BonesPointer"] - SYSTEM_BASE
    bones = []
    for index in range(count):
        at = bones_at + index * bone_bytes
        bone = read_fields(raw, at, layouts["Bone"]) | {"at": at}
        name_at = bone["NamePointer"] - SYSTEM_BASE
        end = raw.find(0, max(0, name_at), name_at + 256)
        if name_at < 0 or end < name_at or end < 0:
            raise SystemExit("skeleton bone name is outside bounded resource bytes")
        try:
            bone["name"] = bytes(raw[name_at:end]).decode("ascii")
        except UnicodeError:
            raise SystemExit("skeleton bone name is not ASCII") from None
        bones.append(bone)
    capacity, node_layout = skel["BoneTagsCapacity"], layouts["SkeletonBoneTag"]
    if capacity == 0 and count == 1 and skel["BoneTagsPointer"] == 0 and skel.get("BoneTagsCount", 0) == 0:
        return []  # the ordinary skeleton reader admits a single bone without a tag table
    buckets_at = skel["BoneTagsPointer"] - SYSTEM_BASE
    if not 0 < capacity <= Limits().max_entries or buckets_at < 0 or buckets_at + capacity * 8 > len(raw):
        raise SystemExit("skeleton tag table exceeds resource bounds")
    chain_order, node_of, seen_nodes = [], {}, set()
    for bucket in range(capacity):
        pointer = struct.unpack_from("<Q", raw, buckets_at + bucket * 8)[0]
        while pointer:
            if pointer in seen_nodes or len(seen_nodes) >= count:
                raise SystemExit("skeleton tag chain cycles, shares nodes or exceeds bone count")
            seen_nodes.add(pointer)
            node = read_fields(raw, pointer - SYSTEM_BASE, node_layout)
            index = node["BoneIndex"]
            if (
                index >= count
                or index in node_of
                or node["BoneTag"] != bones[index]["Tag"]
                or node["BoneTag"] % capacity != bucket
            ):
                raise SystemExit("skeleton tag chain disagrees with bone identity or bucket")
            chain_order.append(index)
            node_of[node["BoneIndex"]] = (bucket, pointer)
            pointer = node["NextPointer"]
    if len(node_of) != count:
        raise SystemExit("skeleton tag chains do not uniquely cover bones")
    original_winners = {}
    for index in chain_order:
        original_winners.setdefault(bones[index]["Tag"], index)
    groups: dict[str, list[int]] = {}
    for index, bone in enumerate(bones):
        groups.setdefault(bone["name"], []).append(index)
    tags = {bone["Tag"] for bone in bones}
    names = {bone["name"] for bone in bones}
    renames = []
    duplicates = {key: set(value) for key, value in groups.items() if len(value) > 1}
    renault_topology = count == 50 and duplicates == {
        key: {boot, chassis} for key, (boot, chassis, _) in PACEV_REAR_BONES.items()
    }
    # Preserve tag-zero root and canonical child lookups; only rename the
    # private string of the container root in this two-bone topology.
    if count == 2 and len(groups) == 1:
        root, child = bones
        name = root["name"]
        if (len(name) >= 6 and root["Tag"] == 0 and root["ParentIndex"] == -1
                and child["ParentIndex"] == 0
                and child["Tag"] != 0 and abs(root["NamePointer"] - child["NamePointer"]) > len(name)):
            alias = "gm" + "0" * (len(name)-2)
            if alias == name:
                alias = alias[:-1] + "1"
            pos = root["NamePointer"] - SYSTEM_BASE
            raw[pos:pos+len(alias)] = alias.encode("ascii")
            root["name"] = alias
            groups = {alias: [0], name: [1]}
            names.add(alias)
            renames.append({"boneIndex": 0, "oldName": name, "newName": alias,
                            "oldTag": 0, "newTag": 0, "keptBoneIndex": 1,
                            "specialCase": "tag-zero container root and attachment child; all tags preserved"})
    for name, members in groups.items():
        if len(members) < 2:
            continue
        family = LETTERED.fullmatch(name)
        semantic_alias = None
        semantic_rename_index = None
        special_case = None
        structural_choices = None
        structural_renames = None
        preserve_stored_tag = False
        if family is None:
            if renault_topology and name in PACEV_REAR_BONES:
                boot_i, chassis_i, semantic_alias = PACEV_REAR_BONES[name]
                if bones[boot_i]["ParentIndex"] < 0 or bones[chassis_i]["ParentIndex"] < 0:
                    raise SystemExit("invalid Renault Espace parent indices")
                if bones[bones[boot_i]["ParentIndex"]]["name"] != "boot" or \
                   bones[bones[chassis_i]["ParentIndex"]]["name"] != "chassis":
                    raise SystemExit(f"Renault Espace {name!r}: unexpected parent names")
                if min(members, key=chain_order.index) != chassis_i:
                    raise SystemExit(f"Renault Espace {name!r}: unexpected tag-chain winner")
                if any(b["ParentIndex"] in (boot_i, chassis_i) for b in bones):
                    raise SystemExit(f"Renault Espace {name!r}: light bone is not a leaf")
                semantic_rename_index = boot_i
                special_case = "Renault Espace V boot-vs-chassis rear lights; preserve chassis tag lookup"
            elif name in REAR_LIGHT_NAMES and len(members) in (2, 3):
                # Keep the *actual* PC tag-chain winner, not an assumed
                # chassis member. An original PC name lookup already reached
                # this particular node, regardless of its attachment parent.
                winner = min(members, key=chain_order.index)
                others = set(members) - {winner}
                parents = {i: bones[i]["ParentIndex"] for i in members}
                original_tags = {bones[i]["Tag"] for i in members}
                pointers = [bones[i]["NamePointer"] for i in members]
                reason = None
                if any(p < 0 or p >= count or p in members for p in parents.values()):
                    reason = "missing, root or duplicate-parent reference"
                elif any(b["ParentIndex"] in members for b in bones):
                    reason = "duplicated light is not a leaf"
                elif len(original_tags) != 1 or next(iter(original_tags)) != bone_tag(name):
                    reason = "tags differ or do not match the canonical light-name hash"
                elif len(set(pointers)) != len(members):
                    reason = "shared name-string storage"
                else:
                    # Overlapping, not just identical, name strings are unsafe.
                    segments = sorted((p - SYSTEM_BASE, p - SYSTEM_BASE + len(name) + 1)
                                      for p in pointers)
                    if any(segments[i][1] > segments[i + 1][0]
                           for i in range(len(segments) - 1)):
                        reason = "overlapping name-string storage"
                if reason:
                    parent_names = [bones[p]["name"] if 0 <= p < count else "INVALID"
                                    for p in parents.values()]
                    raise SystemExit(f"rear light {name!r}: unsafe duplicate topology ({reason}; "
                                     f"parents={parent_names}; winner={winner})")
                # Rewrite only private, index-only leaf names to unused
                # same-width aliases. Parent indices and all rigging remain.
                structural_choices = [name[:-1] + x for x in "xyzuvwabcdefg"
                                      if name[:-1] + x not in names
                                      and bone_tag(name[:-1] + x) not in tags]
                if len(structural_choices) < len(others):
                    raise SystemExit(f"rear light {name!r}: no unused same-width aliases")
                structural_renames = others
                special_case = "structural rear-light leaf duplicates; preserve original PC tag-chain winner"
            elif name not in SEMANTIC_ALIASES:
                # General leaf-only topology: retain the exact existing tag-chain
                # winner, even for exporter-assigned tags that differ from the hash.
                # No index, matrix, parent, or existing winning tag is rewritten.
                winner = min(members, key=chain_order.index)
                parent_ids = {bones[i]["ParentIndex"] for i in members}
                parent_names = {bones[i]["name"] for i in parent_ids if 0 <= i < count}
                original_tags = {bones[i]["Tag"] for i in members}
                same_parent = len(parent_ids) == 1 and all(0 <= i < count for i in parent_ids)
                paired_doors = parent_names in ({"door_dside_f", "door_pside_f"}, {"door_dside_r", "door_pside_r"}) and len(parent_ids) == 2
                safe = (len(members) in (2, 3) and len(name) >= 6 and len(original_tags) == 1
                        and (same_parent or paired_doors) and not any(b["ParentIndex"] in members for b in bones)
                        and all(b["Tag"] not in original_tags for i, b in enumerate(bones) if i not in members))
                if not safe:
                    raise SystemExit(f"duplicate bone {name!r} is not an approved duplicate topology")
                structural_choices = []
                for k in range(1024):
                    alias = "gm" + format(k, f"0{len(name)-2}x")
                    if len(alias) == len(name) and alias not in names and bone_tag(alias) not in tags:
                        structural_choices.append(alias)
                structural_renames = set(members) - {winner}
                preserve_stored_tag = True
                special_case = "same-tag leaf duplicates; preserve original tag-chain winner and index bindings"
            else:
                if len(members) != 2:
                    raise SystemExit(f"duplicate bone {name!r} is not an approved duplicate topology")
                chassis_parent, door_parent, semantic_alias = SEMANTIC_ALIASES[name]
                parent_names = {
                    i: bones[bones[i]["ParentIndex"]]["name"] if 0 <= bones[i]["ParentIndex"] < count else None
                    for i in members
                }
                chassis_indices = [i for i in members if parent_names[i] == chassis_parent]
                door_indices = [i for i in members if parent_names[i] == door_parent]
                if len(chassis_indices) != 1 or len(door_indices) != 1:
                    raise SystemExit(f"semantic duplicate {name!r} has unexpected parents")
                chassis_i, door_i = chassis_indices[0], door_indices[0]
                # Never assume the door node wins: some valid PC exporters put
                # the chassis indicator first in the tag bucket. Preserve the
                # actual winner, so external name/tag lookups still resolve to
                # the same bone. For the known door-winner layout preserve the
                # established alias exactly (regression compatibility).
                winner = min(members, key=chain_order.index)
                if winner == door_i:
                    if any(b["ParentIndex"] == chassis_i for b in bones):
                        raise SystemExit(f"semantic duplicate {name!r}: chassis member has children")
                    semantic_rename_index = chassis_i
                    special_case = "front indicator door-winner; preserve original PC tag lookup"
                else:
                    # If the chassis wins, the other light is safe to rename
                    # only when BOTH are terminal independent leaves. Do not
                    # assign a semantic chassis alias to the door light: use
                    # an unused name-derived tag of identical byte width.
                    if winner != chassis_i or any(b["ParentIndex"] in members for b in bones):
                        raise SystemExit(f"semantic duplicate {name!r}: loser has children")
                    if (len({bones[i]["Tag"] for i in members}) != 1 or
                        any(bones[i]["Tag"] != bone_tag(name) for i in members)):
                        raise SystemExit(f"semantic duplicate {name!r}: noncanonical or conflicting tags")
                    pointers = [bones[i]["NamePointer"] for i in members]
                    spans = sorted((pointer - SYSTEM_BASE, pointer - SYSTEM_BASE + len(name) + 1)
                                   for pointer in pointers)
                    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
                        raise SystemExit(f"semantic duplicate {name!r}: shared or overlapping name strings")
                    structural_choices = []
                    for k in range(4096):
                        alias = "gm" + format(k, f"0{len(name)-2}x")
                        if len(alias) == len(name) and alias not in names and bone_tag(alias) not in tags:
                            structural_choices.append(alias)
                    if not structural_choices:
                        raise SystemExit(f"semantic duplicate {name!r}: no safe unused alias")
                    structural_renames = {door_i}
                    semantic_alias = None
                    special_case = "front indicator chassis-winner; preserve original PC tag lookup and rigging"
            if semantic_alias and (semantic_alias in names or bone_tag(semantic_alias) in tags):
                raise SystemExit(f"alias {semantic_alias!r} is already used")
            if semantic_alias and len(semantic_alias) != len(name):
                raise SystemExit("semantic alias must exactly fit its original name storage")
        if not preserve_stored_tag and any(bones[i]["Tag"] != bone_tag(name) for i in members):
            raise SystemExit(
                f"duplicate bone {name!r}: stored tags do not follow the name hash; cannot derive new tags"
            )
        pointers = [bone["NamePointer"] for bone in bones]
        keep = min(members, key=chain_order.index)  # what a PC tag lookup reaches
        for index in sorted(set(members) - {keep}):
            if structural_renames is not None and index not in structural_renames:
                raise SystemExit("rear light: unexpected rename index")
            if semantic_alias and index != semantic_rename_index:
                raise SystemExit("semantic duplicate refused: unexpected rename target")
            if pointers.count(bones[index]["NamePointer"]) != 1:
                raise SystemExit(f"bone {index} ({name}) shares its name string with another bone")
            free = (
                [n for n in structural_choices if n not in names and bone_tag(n) not in tags]
                if structural_choices is not None else [semantic_alias]
                if semantic_alias is not None
                else [
                    family[1] + letter
                    for letter in "abcdefghijklmnopqrstuvwxyz"
                    if family[1] + letter not in names and bone_tag(family[1] + letter) not in tags
                ]
            )
            if not free:
                raise SystemExit(f"no free name for duplicate bone {index} ({name})")
            new, tag = free[0], bone_tag(free[0])
            names.add(new)
            tags.add(tag)
            name_at = bones[index]["NamePointer"] - SYSTEM_BASE
            raw[name_at : name_at + len(new)] = new.encode("ascii")
            write_field(raw, bones[index]["at"], layouts["Bone"], "Tag", tag)
            # unlink the bone's tag node, retag it, push it on the new bucket's chain
            bucket, pointer = node_of[index]
            node_at = pointer - SYSTEM_BASE
            following = read_fields(raw, node_at, node_layout)["NextPointer"]
            link_at = buckets_at + bucket * 8
            while struct.unpack_from("<Q", raw, link_at)[0] != pointer:
                previous = struct.unpack_from("<Q", raw, link_at)[0] - SYSTEM_BASE
                link_at = previous + node_layout["fields"]["NextPointer"]["offset"]
            struct.pack_into("<Q", raw, link_at, following)
            target = buckets_at + (tag % capacity) * 8
            write_field(raw, node_at, node_layout, "BoneTag", tag)
            write_field(raw, node_at, node_layout, "NextPointer", struct.unpack_from("<Q", raw, target)[0])
            struct.pack_into("<Q", raw, target, pointer)
            renames.append(
                {"boneIndex": index, "oldName": name, "newName": new, "oldTag": bones[index]["Tag"], "newTag": tag}
            )
            renames[-1]["keptBoneIndex"] = keep
            if semantic_alias or structural_choices is not None:
                renames[-1]["specialCase"] = special_case
    # A different-name collision can survive the name pass: the game uses a
    # 16-bit hash, not an injective name identifier. Preserve the first node
    # reached by the original tag lookup; only index-bound leaf losers with
    # authentic name-derived tags and independently owned name storage qualify.
    for row in renames:
        bones[row["boneIndex"]].update(name=row["newName"], Tag=row["newTag"])
    by_tag = {}
    for index, bone in enumerate(bones):
        by_tag.setdefault(bone["Tag"], []).append(index)
    for old_tag, members in by_tag.items():
        if len(members) < 2:
            continue
        keep = min(members, key=chain_order.index)
        if len({bones[i]["name"] for i in members}) != len(members) or any(
            bones[i]["Tag"] != bone_tag(bones[i]["name"]) for i in members
        ):
            raise SystemExit(f"tag collision {old_tag}: ambiguous or noncanonical names/tags")
        for index in sorted(set(members) - {keep}):
            bone = bones[index]; name = bone["name"]
            if (len(name) < 6 or bone["ParentIndex"] < 0 or
                any(b["ParentIndex"] == index for b in bones) or
                sum(b["NamePointer"] == bone["NamePointer"] for b in bones) != 1):
                raise SystemExit(f"tag collision {old_tag}: unsafe alias for bone {index} ({name})")
            for k in range(4096):
                alias = "gm" + format(k, f"0{len(name)-2}x")
                tag = bone_tag(alias)
                if len(alias) == len(name) and alias not in names and tag not in tags:
                    break
            else:
                raise SystemExit(f"tag collision {old_tag}: no unused alias")
            name_at = bone["NamePointer"] - SYSTEM_BASE
            raw[name_at:name_at+len(alias)] = alias.encode("ascii")
            write_field(raw, bone["at"], layouts["Bone"], "Tag", tag)
            bucket, pointer = node_of[index]
            node_at = pointer - SYSTEM_BASE
            following = read_fields(raw, node_at, node_layout)["NextPointer"]
            link_at = buckets_at + bucket * 8
            while struct.unpack_from("<Q", raw, link_at)[0] != pointer:
                prev = struct.unpack_from("<Q", raw, link_at)[0] - SYSTEM_BASE
                link_at = prev + node_layout["fields"]["NextPointer"]["offset"]
            struct.pack_into("<Q", raw, link_at, following)
            target = buckets_at + (tag % capacity) * 8
            write_field(raw, node_at, node_layout, "BoneTag", tag)
            write_field(raw, node_at, node_layout, "NextPointer", struct.unpack_from("<Q", raw, target)[0])
            struct.pack_into("<Q", raw, target, pointer)
            names.add(alias); tags.add(tag)
            bone.update(name=alias, Tag=tag)
            renames.append({"boneIndex": index, "oldName": name, "newName": alias,
                            "oldTag": old_tag, "newTag": tag, "keptBoneIndex": keep,
                            "specialCase": "distinct-name canonical hash collision; preserve original tag lookup"})
    if len({b["Tag"] for b in bones}) != count or len({b["name"] for b in bones}) != count:
        raise SystemExit("skeleton repair incomplete: duplicate names or tags remain")
    # Audit the actual rewritten bucket graph rather than just the plan.
    final_winners, final_indices, final_nodes = {}, set(), set()
    for bucket in range(capacity):
        pointer = struct.unpack_from("<Q", raw, buckets_at + bucket*8)[0]
        while pointer:
            if pointer in final_nodes or len(final_nodes) >= count:
                raise SystemExit("repaired skeleton tag chain cycles or shares nodes")
            final_nodes.add(pointer)
            node = read_fields(raw, pointer-SYSTEM_BASE, node_layout)
            index, tag = node["BoneIndex"], node["BoneTag"]
            if index >= count or index in final_indices or tag != bones[index]["Tag"] or tag % capacity != bucket:
                raise SystemExit("repaired skeleton tag table disagrees with bone")
            final_indices.add(index); final_winners.setdefault(tag,index)
            pointer = node["NextPointer"]
    if len(final_indices) != count or any(final_winners.get(t) != i for t,i in original_winners.items()):
        raise SystemExit("skeleton repair changes original tag lookup or loses bones")
    return renames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--material-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tuning-parts", action="store_true", help="isolate unsupported optional tuning skeletons")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"refusing to overwrite {args.output}")
    manifest = validate_fixture(args.fixture)
    mesh = mesh_runner.inspect(
        pc_walk_args(args.fixture, args.material_report), stage="mesh"
    )  # PC-side replay, no native input
    layouts = vehicle_contracts.load()["pc"]["skeleton"]["layouts"]
    geometry = mesh["freshGeometryBindings"]
    pointer_spec = geometry["pcLegacyGeometryContract"]["drawable"]["fields"]["SkeletonPointer"]
    rows = {row["member"]: row for row in manifest["resources"]}
    planned = []
    excluded = []
    for geom in geometry["resources"]:
        member = geom["member"]
        path = args.fixture.joinpath("resources", *member.replace("!/", "/").split("/"))
        blob = path.read_bytes()
        _, payload = decode_resource(blob, RESOURCE_LIMIT)
        raw = bytearray(payload)
        (drawable,) = [r for r in geom["claimedSystemSpans"] if r["kind"] == "drawable"]
        at = drawable["start"] + pointer_spec["offset"]
        pointer = int.from_bytes(raw[at : at + pointer_spec["bytes"]], "little")
        if not pointer:
            continue
        try:
            renames = repair_skeleton(raw, pointer - SYSTEM_BASE, layouts)
        except SystemExit as exc:
            stem = Path(member.replace("!/", "/")).stem.casefold()
            if not args.tuning_parts or stem in {manifest["model"].casefold(), manifest["model"].casefold()+"_hi"}:
                raise
            excluded.append({"member":member,"reason":str(exc)})
            print(f"WARNING_TUNING_EXCLUDED: {member}: {exc}",flush=True)
            continue
        if renames:
            planned.append((member, blob, raw, renames))
    if not planned and not excluded:
        raise SystemExit("no duplicate bones to repair")
    copy_fixture(args.fixture, args.output, manifest)
    repairs = []
    for member, blob, raw, renames in planned:
        compressor = zlib.compressobj(1, zlib.DEFLATED, -15)
        new_blob = blob[:16] + compressor.compress(bytes(raw)) + compressor.flush()
        args.output.joinpath("resources", *member.replace("!/", "/").split("/")).write_bytes(new_blob)
        row = rows[member]
        row["bytes"] = row["storedBytes"] = len(new_blob)
        row["sha256"] = hashlib.sha256(new_blob).hexdigest()
        repairs.append({"member": member, "bones": renames})
    manifest["excludedTuningSkeleton"] = manifest.get("excludedTuningSkeleton", []) + excluded
    manifest["duplicateBoneRepairs"] = {
        "tool": "tools/repair_pc_duplicate_bones.py",
        "reason": "duplicate lettered bone names/tags; the bone a PC tag lookup reaches keeps the name",
        "sourceFixtureManifestSha256": hashlib.sha256((args.fixture / "manifest.json").read_bytes()).hexdigest(),
        "resources": repairs,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "repairs": repairs}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FixtureError as error:
        raise SystemExit(f"fixture refused: {error}") from None
