"""Decode PC skinning bindings (blend weights and indices) from vertex streams.

Bounded parsing; no native code or reference source runs.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

import numpy as np

from gtavmenu_tools.asset_formats import AssetError, Limits


def binary32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


@dataclass(frozen=True)
class SkinBinding:
    weights: tuple[int, ...]
    palette_indices: tuple[int, ...]
    bone_indices: tuple[int, ...]

    def canonical_bytes(self) -> bytes:
        """Host evidence encoding: raw weights, raw indices, then four LE u16 bones."""
        return bytes(self.weights + self.palette_indices) + struct.pack("<4H", *self.bone_indices)


def decode_binding(
    weights: bytes, indices: bytes, palette: list[int], skeleton_count: int, contract: dict
) -> SkinBinding:
    if len(weights) != contract["laneCount"] or len(indices) != contract["laneCount"]:
        raise AssetError("skinning requires complete packed weight/index lanes")
    if not 0 < len(palette) <= contract["matrixCapacity"] or not 0 < skeleton_count <= 65536:
        raise AssetError("skinning palette/skeleton count is unsupported")
    if indices[contract["clothLane"]] > contract["clothThreshold"]:
        raise AssetError("skinning cloth sentinel is unsupported; separately scoped cloth conversion is required")
    if sum(weights) != contract["weightDenominator"]:
        raise AssetError(
            "skinning weights do not meet the selected unit-sum policy; source bytes will not be normalized"
        )
    bones = []
    for index in indices:
        if index >= len(palette):
            raise AssetError("skinning palette index out of range, including zero-weight lanes")
        bone = palette[index]
        if not 0 <= bone < skeleton_count:
            raise AssetError("skinning palette maps outside the skeleton")
        bones.append(bone)
    return SkinBinding(tuple(weights), tuple(indices), tuple(bones))


def inspect_stream(raw: memoryview, geometry: dict, skeleton_count: int, contract: dict, limits: Limits) -> dict:
    count, stride = geometry["vertexCount"], geometry["vertexStride"]
    if count <= 0 or stride <= 0 or len(raw) != count * stride or len(raw) > limits.max_total_bytes:
        raise AssetError("skinning stream extent or byte budget disagrees")
    if (
        str(geometry["declarationFlags"]) not in contract["selectedVertexTypes"]
        or int(geometry["declarationTypes"], 16) != contract["declarationTypes"]
    ):
        raise AssetError("skinning vertex declaration has no selected public consumer contract")
    offsets = {}
    for name in ("BlendWeights", "BlendIndices"):
        components = [c for c in geometry["components"] if c["semantic"] == name]
        if len(components) != 1:
            raise AssetError(f"skinning {name} component missing or ambiguous")
        component = components[0]
        if component["type"] != contract["componentType"] or component["bytes"] != contract["componentBytes"]:
            raise AssetError(f"skinning {name} packed component format unsupported")
        if not 0 <= component["offset"] <= stride - component["bytes"]:
            raise AssetError("skinning component leaves vertex stride")
        offsets[name] = component["offset"]
    woff, ioff = offsets["BlendWeights"], offsets["BlendIndices"]
    if abs(woff - ioff) < contract["componentBytes"]:
        raise AssetError("skinning packed components overlap")
    palette = geometry["boneIds"]
    if len(palette) == skeleton_count and palette != list(range(skeleton_count)):
        raise AssetError("skinning equal-length nonidentity palette bypasses public remapping; unsupported")
    if count * contract["laneCount"] > limits.max_total_bytes:
        raise AssetError("skinning lane work budget exceeded")
    # The published profile uses exactly four byte-sized lanes.
    lanes = contract["laneCount"]
    weights = np.ndarray((count, lanes), dtype=np.uint8, buffer=raw, offset=woff, strides=(stride, 1))
    indices = np.ndarray((count, lanes), dtype=np.uint8, buffer=raw, offset=ioff, strides=(stride, 1))
    if not 0 < len(palette) <= contract["matrixCapacity"] or not 0 < skeleton_count <= 65536:
        raise AssetError("vertex 0: skinning palette/skeleton count is unsupported")
    bones = np.asarray(palette, dtype=np.int64)[np.minimum(indices, len(palette) - 1)]
    invalid = ((indices[:, contract["clothLane"]] > contract["clothThreshold"])
               | (weights.sum(axis=1) != contract["weightDenominator"])
               | (indices >= len(palette)).any(axis=1)
               | ((bones < 0) | (bones >= skeleton_count)).any(axis=1))
    if invalid.any():
        vertex = int(np.flatnonzero(invalid)[0])
        try:
            decode_binding(weights[vertex].tobytes(), indices[vertex].tobytes(), palette, skeleton_count, contract)
        except AssetError as exc:
            raise AssetError(f"vertex {vertex}: {exc}") from exc
    canonical = np.empty((count, 16), dtype=np.uint8)
    canonical[:, :4], canonical[:, 4:8] = weights, indices
    canonical[:, 8:].view('<u2')[:] = bones
    weight_keys, weights_seen = np.unique(canonical[:, :4].copy().view('V4'), return_counts=True)
    if len(weight_keys) > limits.max_entries:
        raise AssetError("skinning distinct weight tuple report budget exceeded")
    active = (weights != 0).sum(axis=1)
    active_lanes, active_counts = np.unique(active, return_counts=True)
    rigid_weights = weights[active == 1]
    rigid = bones[active == 1][np.arange(len(rigid_weights)), rigid_weights.argmax(axis=1)]
    rigid_bones, rigid_counts = np.unique(rigid, return_counts=True)
    return {
        "vertexVisits": count,
        "indexLaneVisits": count * contract["laneCount"],
        "weightTuples": [
            {"weights": list(bytes(key)), "vertices": int(n)} for key, n in zip(weight_keys, weights_seen, strict=True)
        ],
        "nonzeroWeightLaneCounts": [
            {"lanes": int(n), "vertices": int(total)} for n, total in zip(active_lanes, active_counts, strict=True)
        ],
        "rigidBoneVertices": [
            {"boneIndex": int(bone), "vertices": int(n)} for bone, n in zip(rigid_bones, rigid_counts, strict=True)
        ],
        "minimumPaletteIndex": int(indices.min()),
        "maximumPaletteIndex": int(indices.max()),
        "canonicalBindingSha256": hashlib.sha256(canonical).hexdigest(),
        "canonicalBindingBytes": count * 16,
        "sourceBytesPreserved": True,
        "nativeSkinningValidated": False,
    }
