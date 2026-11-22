#!/usr/bin/env python3
"""Repair bounded exporter quirks in an imported PC vehicle fixture.

The same bounded readers used by native conversion detect five admitted shapes: empty octant
item pointers, glass rows without data, identity/NaN placeholder fragment matrices,
shatter maps exactly one column short, and inverted BVH leaf bounds. Every other
reader refusal remains active. Recorded source page hashes and old field values
must match before a new fixture is written. Branch bounds and non-placeholder
matrices are never repaired.

Clearing an empty octant pointer only admits conversion. The converted resource
must subsequently pass native_octants.py, which fills each empty octant with the
bound's full vertex list; an empty native octant is unsafe at runtime.

Placeholder translations up to FRAG_TRANSLATION_LIMIT are recorded explicitly.
The source is unchanged. Verified retail inputs come from --templates; no game
executable, frozen reports, or emulator is used.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import native_collision  # noqa: E402
import native_drawables  # noqa: E402
import native_fragment  # noqa: E402
import pc_physics_damage  # noqa: E402
from gtavmenu_tools import vehicle_contracts  # noqa: E402
from gtavmenu_tools.asset_formats import AssetError, Limits, decode_resource  # noqa: E402
from gtavmenu_tools.asset_textures import SYSTEM_BASE  # noqa: E402
from gtavmenu_tools.vehicle_repair_inputs import FixtureError, copy_fixture, resource_path, validate_fixture  # noqa: E402

FRAG_MATRIX_FIELDS = (
    "FragMatricesIndsPointer",
    "FragMatricesIndsCount",
    "FragMatricesCapacity",
    "FragMatricesPointer",
    "FragMatricesCount",
)
IDENTITY_ROWS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
# An exporter's float noise on the placeholder (KoRn mk6pol: translation z -2.98e-7, the rest exact): still no transform.
IDENTITY_TOLERANCE = 1e-6
# The Prowler bike's placeholder matrix is identity with a 3.7 cm translation (0.0049, 0, 0.0364) that every
# model index points at; a translation up to this bound (metres) is dropped with the arrays and recorded.
FRAG_TRANSLATION_LIMIT = 0.1
DROPPED_TRANSLATIONS: list[list[float]] = []  # translations of the placeholder matrices dropped by the last walk

ORIGINAL_LOOP = """                for count, target in zip(arrays["OctantsPointer"]["values"], ptrs["values"], strict=True):
                    items = integers(target["value"], count["value"], "octant-items")"""
PATCHED_LOOP = """                for _slot, (count, target) in enumerate(
                    zip(arrays["OctantsPointer"]["values"], ptrs["values"], strict=True)
                ):
                    if count["value"] == 0 and target["value"]:
                        _FOUND.append(
                            (hashlib.sha256(system).hexdigest(), h["OctantItemsPointer"] + _slot * 8 - base,
                             8, target["value"])
                        )
                        node["octants"].append(None)
                        continue
                    items = integers(target["value"], count["value"], "octant-items")"""


ORIGINAL_GLASS = """        elif values["ItemDataCount"]:
            raise AssetError("fragment glass row count without data is unsupported")"""
PATCHED_GLASS = """        elif values["ItemDataCount"]:
            _field = contract["window"]["fields"]["ItemDataCount"]
            _FOUND.append(
                (hashlib.sha256(system).hexdigest(), data_start - contract["window"]["bytes"] + _field["offset"],
                 _field["bytes"], values["ItemDataCount"])
            )"""


# 5. BVH leaves with swapped bounds (Rockport Police Coquette, rpdcar5: one composite child's quantized box
#    has MinX 3805 > MaxX -3990): the reader refuses "collision BVH node bounds inverted". For a leaf
#    (ItemCount > 0) the min and max of each inverted axis are swapped back; an inverted branch still refuses.
ORIGINAL_BVH = """                if any(row["Min" + a] > row["Max" + a] for a in "XYZ"):
                    raise AssetError("collision BVH node bounds inverted")"""
PATCHED_BVH = """                if any(row["Min" + a] > row["Max" + a] for a in "XYZ"):
                    if row["ItemCount"] <= 0:
                        raise AssetError("collision BVH node bounds inverted")
                    _node = structs["BVHNode_s"]
                    _at = arrays["Nodes.EntriesPointer"]["sourcePointer"] - base + i * _node["bytes"]
                    for _axis in "XYZ":
                        if row["Min" + _axis] > row["Max" + _axis]:
                            for _name, _new in (("Min" + _axis, row["Max" + _axis]), ("Max" + _axis, row["Min" + _axis])):
                                _f = _node["fields"][_name]
                                _FOUND.append(
                                    (hashlib.sha256(system).hexdigest(), _at + _f["offset"], _f["bytes"],
                                     row[_name] & 0xFFFF, _new & 0xFFFF)
                                )"""


# 4. Shatter maps one column narrower than their rows (Dominator GTX, 6 windows): every full row is
#    [0, ShatterMapWidth] with ShatterMapWidth + 1 data bytes, so the width field is one short. The walk
#    records the width a row needs (end + 1); a row more than one column past the width still refuses.
ORIGINAL_WIDTH = """                    if last >= values["ShatterMapWidth"]:
                        raise AssetError("fragment glass shatter interval exceeds width")"""
PATCHED_WIDTH = """                    if last > values["ShatterMapWidth"]:
                        raise AssetError("fragment glass shatter interval exceeds width")
                    if last == values["ShatterMapWidth"]:
                        _width = contract["window"]["fields"]["ShatterMapWidth"]
                        _FOUND.append(
                            (hashlib.sha256(system).hexdigest(), data_start - contract["window"]["bytes"]
                             + _width["offset"], _width["bytes"], values["ShatterMapWidth"], last + 1)
                        )"""
ORIGINAL_WIDTH2 = """                        if n2 <= 0 or row["end2"] >= values["ShatterMapWidth"]:
                            raise AssetError("fragment glass second shatter interval invalid")"""
PATCHED_WIDTH2 = """                        if n2 <= 0 or row["end2"] > values["ShatterMapWidth"]:
                            raise AssetError("fragment glass second shatter interval invalid")
                        if row["end2"] == values["ShatterMapWidth"]:
                            _width = contract["window"]["fields"]["ShatterMapWidth"]
                            _FOUND.append(
                                (hashlib.sha256(system).hexdigest(), data_start - contract["window"]["bytes"]
                                 + _width["offset"], _width["bytes"], values["ShatterMapWidth"], row["end2"] + 1)
                            )"""


def _patched(module, name: str, original, patched, found: list):
    """MODULE.NAME recompiled with each ORIGINAL text replaced by its PATCHED text (str or parallel tuples)."""
    source = inspect.getsource(getattr(module, name))
    pairs = zip(
        (original,) if isinstance(original, str) else original,
        (patched,) if isinstance(patched, str) else patched,
        strict=True,
    )
    for old, new in pairs:
        if source.count(old) != 1:
            raise SystemExit(f"{module.__name__}.{name} changed; refusing to patch")
        source = source.replace(old, new)
    namespace = dict(vars(module))
    namespace["_FOUND"] = found
    namespace["hashlib"] = hashlib
    exec(compile(source, module.__file__, "exec"), namespace)
    return namespace[name]


def placeholder_frag_matrices(system: bytes, base: int, header: dict) -> bool:
    """True when the drawable's FragMatrices carry no transform: zero indices (or indices below the
    count), identity matrices with zero translation (fourth column ignored: NaN padding) and unused
    all-NaN matrices, every array inside the system pages."""
    count, capacity, index_count = (
        header["FragMatricesCount"],
        header["FragMatricesCapacity"],
        header["FragMatricesIndsCount"],
    )
    indices_at, matrices_at = header["FragMatricesIndsPointer"] - base, header["FragMatricesPointer"] - base
    if not (header["FragMatricesIndsPointer"] and header["FragMatricesPointer"]) or not 0 < count <= capacity <= 256:
        return False
    if index_count > 256 or min(indices_at, matrices_at) < 0:
        return False
    if indices_at + index_count * 8 > len(system) or matrices_at + capacity * 64 > len(system):
        return False
    if any(i >= count for i in struct.unpack_from(f"<{index_count}Q", system, indices_at)):
        return False
    moved = []
    for i in range(capacity):
        m = struct.unpack_from("<16f", system, matrices_at + 64 * i)
        rows = tuple(tuple(m[4 * r : 4 * r + 3]) for r in range(4))
        near = all(
            abs(a - b) <= IDENTITY_TOLERANCE for row, want in zip(rows, IDENTITY_ROWS, strict=True)
            for a, b in zip(row, want, strict=True)
        )  # fmt: skip
        if near or all(math.isnan(x) for x in m):
            continue
        if rows[:3] == IDENTITY_ROWS[:3] and math.hypot(*rows[3]) <= FRAG_TRANSLATION_LIMIT:
            moved.append([round(v, 6) for v in rows[3]])
            continue
        return False
    DROPPED_TRANSLATIONS.extend(t for t in moved if t not in DROPPED_TRANSLATIONS)
    return True


def _drawable_reader(saved, found: list):
    """native_drawables.read that records and nulls placeholder FragMatrices, then reads normally."""

    def read(system, base, root, contract):
        layout = contract["drawable"]
        header, _ = native_drawables.typed(system, root, layout)
        others = [n for n in native_drawables.ZERO_EXTENSION if n not in FRAG_MATRIX_FIELDS and header[n]]
        if (
            any(header[n] for n in FRAG_MATRIX_FIELDS)
            and not others
            and not header["DrawableModelsBlocksSize"]
            and placeholder_frag_matrices(system, base, header)
        ):
            system_sha = hashlib.sha256(system).hexdigest()
            patched = bytearray(system)
            for name in FRAG_MATRIX_FIELDS:
                field = layout["fields"][name]
                at = root + field["offset"]
                found.append((system_sha, at, field["bytes"], header[name]))
                patched[at : at + field["bytes"]] = bytes(field["bytes"])
            system = bytes(patched)
        return saved(system, base, root, contract)

    return read


WALK_STOPPED: list[str] = []  # the converter refusal that ended the last collect() walk early, if any


def collect(fixture: Path, report: Path, manifest: dict) -> list[tuple]:
    """Find supported source-only repairs without building any native component."""
    material = json.loads(report.read_bytes())
    hashes = {row["member"]: row["sha256"] for row in manifest["resources"]}
    observed = {row["member"]: row for row in material["sources"]["resources"] if row["kind"] == "fragment"}
    formats = vehicle_contracts.load()["pc"]
    limits = Limits()
    found = []
    read_collision = _patched(
        native_collision, "read", (ORIGINAL_LOOP, ORIGINAL_BVH), (PATCHED_LOOP, PATCHED_BVH), found
    )
    read_drawable = _drawable_reader(native_drawables.read, found)
    saved_glass = native_fragment.read_glass
    native_fragment.read_glass = _patched(
        native_fragment, "read_glass", (ORIGINAL_GLASS, ORIGINAL_WIDTH, ORIGINAL_WIDTH2),
        (PATCHED_GLASS, PATCHED_WIDTH, PATCHED_WIDTH2), found,
    )
    try:
        for row in material["resources"]:
            member = row["member"]
            evidence = observed[member]
            blob = resource_path(fixture, member).read_bytes()
            digest = hashlib.sha256(blob).hexdigest()
            if digest != hashes[member] or digest != evidence["resourceSha256"]:
                raise FixtureError(f"{member}: fragment differs from its material report")
            header, payload = decode_resource(blob, limits.max_file_bytes)
            if header["version"] != 162 or header["graphicsBytes"]:
                raise FixtureError(f"{member}: unsupported PC Legacy fragment layout")
            if hashlib.sha256(payload).hexdigest() != evidence["payloadSha256"]:
                raise FixtureError(f"{member}: fragment payload differs from its material report")
            system = payload[:header["systemBytes"]]

            try:
                native_fragment.read(system, SYSTEM_BASE, 0, formats["fragment"])
            except (AssetError, struct.error) as error:
                WALK_STOPPED.append(f"{member}: {error}")
            try:
                root = native_collision.scalar(
                    system, SYSTEM_BASE, SYSTEM_BASE, formats["fragment"]["root"], "DrawablePointer"
                )
                if root < SYSTEM_BASE or root - SYSTEM_BASE != row["drawable"]["systemOffset"]:
                    raise AssetError("fragment drawable pointer differs from its material report")
                pointers = [root]
                physics = formats["children"]["physics"]
                group_at = physics["layout"]["fragmentPhysicsLodGroupPointer"]
                if struct.unpack_from("<Q", system, group_at)[0]:
                    info = pc_physics_damage.inspect_payload(payload, header, physics, limits)
                    pointers += [int(child[field], 0)
                                 for lod in info["lods"] if lod is not None
                                 for child in lod["children"]
                                 for field in ("drawable1Pointer", "drawable2Pointer")
                                 if int(child[field], 0)]
                links = []
                for index, pointer in enumerate(dict.fromkeys(pointers)):
                    drawable = read_drawable(system, SYSTEM_BASE, pointer - SYSTEM_BASE, formats["drawable"])
                    bound = drawable["header"]["BoundPointer"]
                    if bound:
                        links.append({"drawableIndex": index, "sourcePointer": bound})
                roots = native_collision.roots(system, SYSTEM_BASE, {"externalCollisionLinks": links},
                                               formats["collision"])
                read_collision(system, SYSTEM_BASE, roots, formats["collision"])
            except (AssetError, struct.error) as error:
                WALK_STOPPED.append(f"{member}: {error}")
    finally:
        native_fragment.read_glass = saved_glass
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--material-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--templates", type=Path, help="accepted for compatibility with the repair pipeline")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"refusing to overwrite {args.output}")
    manifest = validate_fixture(args.fixture)
    WALK_STOPPED.clear()
    DROPPED_TRANSLATIONS.clear()
    found = collect(args.fixture, args.material_report, manifest)
    if not found:
        # Unknown read failures still go through the strict final conversion.
        stopped = f" (walk stopped before the end: {WALK_STOPPED[-1]})" if WALK_STOPPED else ""
        raise SystemExit(f"no quirks found{stopped}")
    copy_fixture(args.fixture, args.output, manifest)
    changes = []
    for row in manifest["resources"]:
        if not row["member"].endswith(".yft"):
            continue
        path = args.output.joinpath("resources", *row["member"].replace("!/", "/").split("/"))
        blob = path.read_bytes()
        from gtavmenu_tools.asset_formats import decode_resource, Limits
        raw = bytearray(decode_resource(blob, Limits().max_file_bytes)[1])
        mine = {}
        # The probe identifies every change by the same few system page sizes.
        # Hash each size once even when a fragment has many empty octants.
        system_hashes = {hashlib.sha256(memoryview(raw)[:n]).hexdigest() for n in _system_sizes(blob)}
        for system_sha, offset, size, value, *new in found:
            if system_sha in system_hashes:
                # a field recorded with new values (shatter widths: one per row) takes the largest
                key = (offset, size, value)
                mine[key] = max(mine.get(key, 0), *new) if new else 0
        if not mine:
            continue
        for (offset, size, value), new_value in sorted(mine.items()):
            fmt = {2: "<H", 4: "<I", 8: "<Q"}[size]
            if struct.unpack_from(fmt, raw, offset)[0] != value:
                raise SystemExit(f"{row['member']}: field {offset:#x} does not hold {value:#x}")
            struct.pack_into(fmt, raw, offset, new_value)
        compressor = zlib.compressobj(1, zlib.DEFLATED, -15)
        new_blob = blob[:16] + compressor.compress(bytes(raw)) + compressor.flush()
        path.write_bytes(new_blob)
        row["bytes"] = row["storedBytes"] = len(new_blob)
        row["sha256"] = hashlib.sha256(new_blob).hexdigest()
        changes.append(
            {
                "member": row["member"],
                "fields": [
                    {"offset": o, "bytes": s, "old": v, **({"new": n} if n else {})}
                    for (o, s, v), n in sorted(mine.items())
                ],
            }
        )
    manifest["fragmentQuirkRepairs"] = {
        "tool": "tools/repair_pc_fragment_quirks.py",
        "reason": (
            "octant item pointer non-null with count 0 (nulled for the reader; native_octants.py fills the"
            " octant after conversion); glass window rows without shatter data; placeholder fragment"
            " matrices (identity/NaN only, zero indices) dropped"
        ),
        "sourceFixtureManifestSha256": hashlib.sha256((args.fixture / "manifest.json").read_bytes()).hexdigest(),
        "resources": changes,
    }
    if DROPPED_TRANSLATIONS:  # placeholder matrices that were identity plus a small translation (Prowler)
        manifest["fragmentQuirkRepairs"]["fragMatrixTranslationsDropped"] = DROPPED_TRANSLATIONS
        print(f"placeholder fragment matrices: translations dropped (metres): {DROPPED_TRANSLATIONS}")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "repaired": len(found), "resources": [c["member"] for c in changes]}))
    return 0


def _system_sizes(blob: bytes) -> list[int]:
    """System page byte sizes the PC header may describe (Legacy v162 page flags)."""
    from gtavmenu_tools.asset_formats import resource_header

    header = resource_header(blob)
    return [header["systemBytes"]]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FixtureError as error:
        raise SystemExit(f"fixture refused: {error}") from None
