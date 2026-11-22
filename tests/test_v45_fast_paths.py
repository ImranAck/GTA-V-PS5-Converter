"""Guard byte identity and validation on the optimized geometry and texture paths."""
import hashlib
import math
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "motor" / "tools"))

import bc_encode
import pc_mesh_buffers
import pc_skinning_bindings
from gtavmenu_tools import texture_layout, vehicle_contracts
from gtavmenu_tools.asset_formats import AssetError, Limits
from native_octants import changed_spans
from native_resource_builder import BlockIndex, ObjectArena, relocate
from repair_pc_nonfinite_texcoords import sanitize


class FastPathTests(unittest.TestCase):
    def test_tiling_matches_scalar_offsets_with_padding_and_tail(self):
        rng = np.random.default_rng(45)
        for fmt, mode in (("BC1", 5), ("BC3", 9), ("BC5", 1), ("BGRA8", 5)):
            with self.subTest(fmt=fmt, mode=mode):
                layout = texture_layout.surface_layout(519, 205, 8, fmt, mode)
                expected = bytearray(layout.storage_bytes)
                mips = []
                step = layout.block_bytes
                for level, mip in enumerate(layout.mips):
                    data = rng.bytes(mip.width_blocks * mip.height_blocks * step)
                    mips.append(data)
                    for i, offset in enumerate(layout.offsets(level)):
                        expected[offset:offset + step] = data[i * step:(i + 1) * step]
                tiled = texture_layout.tile_mips(mips, layout)
                self.assertEqual(tiled, expected)
                self.assertEqual(texture_layout.untile_mips(tiled, layout), tuple(mips))

    def test_alpha_transcode_identical_to_exhaustive_palette_fit(self):
        rng = np.random.default_rng(44)
        values = rng.integers(0, 16, (263, 16), dtype=np.int16)
        values[:16] = np.arange(16)[:, None]
        ends, palette = bc_encode._bc3_alpha_palettes()
        candidates = np.abs(values[:, None, :, None] * 17 - palette[None, :, None, :])
        selectors = candidates.argmin(axis=-1)
        error = candidates.min(axis=-1).astype(np.int64)
        winners = (error.max(axis=-1) * (1 << 24) + (error ** 2).sum(axis=-1)).argmin(axis=1)
        expected = []
        for row, winner in enumerate(winners):
            bits = sum(int(k) << (3 * i) for i, k in enumerate(selectors[row, winner]))
            expected.append(bytes(ends[winner]) + bits.to_bytes(6, "little"))
        self.assertEqual(bc_encode._bc3_alpha_blocks(values).tobytes(), b"".join(expected))

    def test_numeric_checks_keep_first_signed_zero_and_refuse_nonfinite_positions(self):
        spec = [dict(semantic="Position", type="Float3", offset=0, bytes=12),
                dict(semantic="TexCoord0", type="Float2", offset=12, bytes=8)]
        forms = {"Float3": {"bytes": 12, "scalarCount": 3}, "Float2": {"bytes": 8, "scalarCount": 2}}
        raw = struct.pack("<10f", -0., 1., 3., 0., 4., 0., 2., -2., float("nan"), 7.)
        cleaned, patch = sanitize(raw, 2, 20, spec, forms)
        self.assertEqual(patch, [{"vertex": 1, "semantic": "TexCoord0", "scalar": 0}])
        observed = pc_mesh_buffers.inspect_float_stream(cleaned, 2, 20, spec, forms)
        position = observed["finiteFloatComponents"][0]
        self.assertEqual(position["minimum"], [0., 1., -2.])
        self.assertEqual(math.copysign(1., position["minimum"][0]), -1.)
        with self.assertRaisesRegex(AssetError, "TexCoord0.*vertex 1"):
            pc_mesh_buffers.inspect_float_stream(raw, 2, 20, spec, forms)

    def test_skin_readback_matches_canonical_bindings_and_checks_all_lanes(self):
        contract = vehicle_contracts.load()["pc"]["skinning"]
        geometry = {"vertexCount": 2, "vertexStride": 12, "boneIds": [3, 1],
                    "declarationFlags": int(next(iter(contract["selectedVertexTypes"]))),
                    "declarationTypes": hex(contract["declarationTypes"]),
                    "components": [{"semantic": name, "type": contract["componentType"],
                                    "bytes": 4, "offset": offset}
                                   for name, offset in (("BlendWeights", 1), ("BlendIndices", 6))]}
        raw = bytearray(24)
        raw[1:5], raw[13:17] = b"\xff\0\0\0", b"\x80\x7f\0\0"
        raw[6:10], raw[18:22] = b"\x01\0\0\0", b"\0\x01\0\0"
        expected = b"".join(pc_skinning_bindings.decode_binding(
            raw[base+1:base+5], raw[base+6:base+10], [3, 1], 5, contract
        ).canonical_bytes() for base in (0, 12))
        observed = pc_skinning_bindings.inspect_stream(memoryview(raw), geometry, 5, contract, Limits())
        self.assertEqual(observed["canonicalBindingSha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(observed["rigidBoneVertices"], [{"boneIndex": 1, "vertices": 1}])
        raw[21] = 3
        with self.assertRaisesRegex(AssetError, "vertex 1: skinning palette index out of range"):
            pc_skinning_bindings.inspect_stream(memoryview(raw), geometry, 5, contract, Limits())

    def test_relocation_keeps_owner_constraints_and_pointers(self):
        arena = ObjectArena()
        first = arena.add("header", bytes(8))
        second = arena.add("vertex", b"abcd", 16)
        arena.pointer(first, second + 1)
        data, placement = arena.render(0x50000000)
        self.assertEqual(struct.unpack_from("<Q", relocate(data, placement, 0x60000000))[0],
                         0x60000011)
        self.assertFalse(arena.contains(second - 1, 2))
        index = BlockIndex(reversed(list(placement["blocks"].values())), len(data))
        self.assertEqual(index.find(second)["offset"], second)
        self.assertIsNone(index.find(second + 4))
        with self.assertRaisesRegex(AssetError, "overlap"):
            BlockIndex([{"offset": 0, "bytes": 9}, {"offset": 8, "bytes": 1}])

    def test_octant_diff_retains_disjoint_and_terminal_ranges(self):
        self.assertEqual(changed_spans(b"abcdefgh", b"XbYZefgW"), [(0, 1), (2, 4), (7, 8)])
        self.assertEqual(changed_spans(b"abc", b"abc"), [])


if __name__ == "__main__":
    unittest.main()
