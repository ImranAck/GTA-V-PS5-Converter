"""Small block-compression encoders for texture authoring (BC1, BC3, BC5).

Quality is "range fit": per 4x4 block the endpoints are the extremes of the block's colours
projected on their principal axis, and each pixel takes the nearest palette entry. Good enough for
logos, liveries and test images; not a production encoder. Output is linear (row-major) blocks of
one mip, ready for texture_layout.tile_mips.

bc2_to_bc3 transcodes BC2 (DXT3) blocks for which no retail PS5 template exists: the colour half
is the same always-4-colour BC1-style block in both formats and is copied bit-exactly; only the
explicit 4-bit alpha is re-encoded as an interpolated BC3 alpha block (best endpoint pair on the
4-bit grid, both BC3 alpha modes, minimum worst-pixel error then minimum squared error).
"""

from __future__ import annotations

import numpy as np


def _blocks(rgba: np.ndarray) -> np.ndarray:
    """(H, W, C) -> (H/4 * W/4, 16, C) with edge padding to multiples of 4."""
    height, width = rgba.shape[:2]
    pad_h, pad_w = (-height) % 4, (-width) % 4
    if pad_h or pad_w:
        rgba = np.pad(rgba, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
    h4, w4 = rgba.shape[0] // 4, rgba.shape[1] // 4
    return rgba.reshape(h4, 4, w4, 4, -1).transpose(0, 2, 1, 3, 4).reshape(h4 * w4, 16, -1)


def _to565(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(np.rint(rgb), 0, 255).astype(np.uint32)
    return ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)


def _from565(value: np.ndarray) -> np.ndarray:
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=-1).astype(np.float32)


def _color_block(pixels: np.ndarray) -> bytes:
    """One opaque 4-colour BC1 colour block (8 bytes) for 16 RGB pixels."""
    mean = pixels.mean(axis=0)
    centered = pixels - mean
    cov = centered.T @ centered
    axis = np.linalg.eigh(cov)[1][:, -1] if cov.any() else np.array([1.0, 1.0, 1.0])
    proj = centered @ axis
    hi, lo = pixels[np.argmax(proj)], pixels[np.argmin(proj)]
    c0, c1 = int(_to565(hi)), int(_to565(lo))
    if c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1:
        return np.array([c0, c1], dtype="<u2").tobytes() + b"\0\0\0\0"
    e0, e1 = _from565(np.array(c0)), _from565(np.array(c1))
    palette = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3])
    index = np.argmin(((pixels[:, None, :] - palette[None]) ** 2).sum(axis=-1), axis=1)
    bits = 0
    for i, value in enumerate(index):
        bits |= int(value) << (2 * i)
    return np.array([c0, c1], dtype="<u2").tobytes() + int(bits).to_bytes(4, "little")


def _bc4_block(values: np.ndarray) -> bytes:
    """One 8-level BC4 block (8 bytes) for 16 single-channel values."""
    a0, a1 = int(values.max()), int(values.min())
    if a0 == a1:
        return bytes((a0, a1)) + b"\0" * 6
    palette = np.array([a0, a1] + [((7 - i) * a0 + i * a1) / 7 for i in range(1, 7)], dtype=np.float32)
    index = np.argmin(np.abs(values[:, None].astype(np.float32) - palette[None]), axis=1)
    bits = 0
    for i, value in enumerate(index):
        bits |= int(value) << (3 * i)
    return bytes((a0, a1)) + int(bits).to_bytes(6, "little")


def _bc3_vectorized(rgba: np.ndarray, batch: int = 4096) -> bytes:
    """BC3 range-fit encoded in bounded NumPy batches.

    Equivalent endpoints, PCA axis, nearest palette, and BC3 alpha selectors to
    the reference block implementation. Batches avoid one Python loop and one
    eigendecomposition call *per block*; no changes to image resolution or mips.
    The reference implementation is retained below for other BC formats.
    """
    blocks = _blocks(rgba.astype(np.uint8))
    out = bytearray(len(blocks) * 16)
    u64 = np.arange(16, dtype=np.uint64)
    byte_shift = np.arange(6, dtype=np.uint64) * 8
    for start in range(0, len(blocks), batch):
        part = blocks[start:start + batch]
        n = len(part)
        pixels = part[:, :, :3].astype(np.float32)
        mean = pixels.mean(axis=1)
        centered = pixels - mean[:, None, :]
        cov = np.matmul(centered.transpose(0, 2, 1), centered)
        axis = np.linalg.eigh(cov)[1][:, :, -1]
        axis[~cov.any(axis=(1, 2))] = np.array([1., 0., 0.], dtype=np.float32)
        proj = np.matmul(centered, axis[:, :, None])[:, :, 0]
        hi = pixels[np.arange(n), np.argmax(proj, axis=1)]
        lo = pixels[np.arange(n), np.argmin(proj, axis=1)]
        a = _to565(hi)
        b = _to565(lo)
        c0, c1 = np.maximum(a, b), np.minimum(a, b)
        e0, e1 = _from565(c0), _from565(c1)
        palette = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], axis=1)
        color_idx = np.argmin(((pixels[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(axis=-1), axis=2)
        color_bits = np.sum(color_idx.astype(np.uint64) << (u64[None, :] * 2), axis=1, dtype=np.uint64).astype('<u4')
        color_bits[c0 == c1] = 0

        alpha = part[:, :, 3]
        a0, a1 = alpha.max(axis=1), alpha.min(axis=1)
        # The scalar reference builds a float32 palette from Python scalars.
        # Explicit float32 here reproduces the same arithmetic and tie order.
        palette_a = np.stack([a0, a1] + [
            ((7 - i) * a0.astype(np.float32) + i * a1.astype(np.float32)) / 7
            for i in range(1, 7)
        ], axis=1).astype(np.float32)
        alpha_idx = np.argmin(np.abs(alpha[:, :, None].astype(np.float32) - palette_a[:, None, :]), axis=2)
        alpha_bits = np.sum(alpha_idx.astype(np.uint64) << (u64[None, :] * 3), axis=1, dtype=np.uint64)
        alpha_bits[a0 == a1] = 0

        raw = np.empty((n, 16), dtype=np.uint8)
        raw[:, 0], raw[:, 1] = a0, a1
        raw[:, 2:8] = (alpha_bits[:, None] >> byte_shift[None, :]).astype(np.uint8)
        raw[:, 8:10] = c0.astype('<u2').view(np.uint8).reshape(n, 2)
        raw[:, 10:12] = c1.astype('<u2').view(np.uint8).reshape(n, 2)
        raw[:, 12:16] = color_bits.view(np.uint8).reshape(n, 4)
        out[start * 16:(start + n) * 16] = raw.tobytes()
    return bytes(out)


def encode(format_name: str, rgba: np.ndarray) -> bytes:
    """Encode an (H, W, 4) uint8 image as linear blocks of `format_name`."""
    if format_name == "BC3":
        try:
            return _bc3_vectorized(rgba)
        except (MemoryError, np.linalg.LinAlgError):
            # Preserve the reviewed reference path if batching is unavailable.
            pass
    blocks = _blocks(rgba.astype(np.uint8))
    out = bytearray()
    for block in blocks:
        rgb = block[:, :3].astype(np.float32)
        if format_name == "BC1":
            out += _color_block(rgb)
        elif format_name == "BC3":
            out += _bc4_block(block[:, 3]) + _color_block(rgb)
        elif format_name == "BC5":
            out += _bc4_block(block[:, 0]) + _bc4_block(block[:, 1])
        else:
            raise ValueError(f"unsupported format {format_name}")
    return bytes(out)


def decode_bc1_rgb(data: bytes, width: int, height: int) -> np.ndarray:
    """Reference decoder for verification: linear BC1 blocks -> (H, W, 3) uint8."""
    w4, h4 = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    image = np.zeros((h4 * 4, w4 * 4, 3), dtype=np.uint8)
    for n in range(w4 * h4):
        block = data[n * 8 : n * 8 + 8]
        c0, c1 = int.from_bytes(block[0:2], "little"), int.from_bytes(block[2:4], "little")
        e0, e1 = _from565(np.array(c0)), _from565(np.array(c1))
        four = c0 > c1
        palette = [e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3] if four else [e0, e1, (e0 + e1) / 2, np.zeros(3)]
        bits = int.from_bytes(block[4:8], "little")
        by, bx = divmod(n, w4)
        for i in range(16):
            image[by * 4 + i // 4, bx * 4 + i % 4] = np.clip(palette[(bits >> (2 * i)) & 3], 0, 255)
    return image[:height, :width]


def _bc3_alpha_palettes() -> tuple[np.ndarray, np.ndarray]:
    """Every BC3 alpha block with endpoints on the 4-bit (x17) grid: (a0, a1) and 8-entry palettes."""
    grid = [17 * v for v in range(16)]
    ends, palettes = [], []
    for lo in grid:
        for hi in grid:
            if hi > lo:  # 8-level mode: a0 > a1
                ends.append((hi, lo))
                palettes.append([hi, lo] + [((7 - k) * hi + k * lo + 3) // 7 for k in range(1, 7)])
            if hi >= lo:  # 6-level mode: a0 <= a1, codes 6/7 are 0/255
                ends.append((lo, hi))
                palettes.append([lo, hi] + [((5 - k) * lo + k * hi + 2) // 5 for k in range(1, 5)] + [0, 255])
    return np.array(ends, dtype=np.uint8), np.array(palettes, dtype=np.int16)


_ALPHA_ENDS, _ALPHA_PALETTES = _bc3_alpha_palettes()


# BC2 source alpha has only sixteen possible values. Precompute each value's
# nearest selector and error for every candidate BC3 endpoint pair.
_ALPHA_DIFF = np.abs((np.arange(16, dtype=np.int16) * 17)[:, None, None] - _ALPHA_PALETTES[None])
_ALPHA_SELECTORS = _ALPHA_DIFF.argmin(axis=-1).astype(np.uint8)
_ALPHA_ERRORS = _ALPHA_DIFF.min(axis=-1)
_ALPHA_SQUARED = _ALPHA_ERRORS.astype(np.int32) ** 2


def _bc3_alpha_blocks(values: np.ndarray, chunk: int = 256) -> np.ndarray:
    """(N, 16) BC2 nibble values -> (N, 8) BC3 alpha blocks, with the same tie order."""
    out = np.empty((len(values), 8), dtype=np.uint8)
    shifts = np.arange(16, dtype=np.uint64) * 3
    for start in range(0, len(values), chunk):
        part = values[start : start + chunk]
        worst = _ALPHA_ERRORS[part].max(axis=1).astype(np.int32)
        squared = _ALPHA_SQUARED[part].sum(axis=1, dtype=np.int32)
        best = (worst * (16 * 255**2 + 1) + squared).argmin(axis=1)
        index = _ALPHA_SELECTORS[part, best[:, None]].astype(np.uint64)
        bits = (index << shifts).sum(axis=-1, dtype=np.uint64)
        out[start : start + len(part), :2] = _ALPHA_ENDS[best]
        out[start : start + len(part), 2:] = (bits[:, None] >> (np.arange(6, dtype=np.uint64) * 8)).astype(np.uint8)
    return out


def bc2_to_bc3(data: bytes) -> bytes:
    """Transcode linear BC2 blocks to BC3: colour halves bit-exact, alpha re-encoded."""
    if len(data) % 16:
        raise ValueError("BC2 data is not a whole number of 16-byte blocks")
    blocks = np.frombuffer(data, dtype=np.uint8).reshape(-1, 16)
    words = blocks[:, :8].copy().view("<u8")[:, 0]
    unique, inverse = np.unique(words, return_inverse=True)
    values = ((unique[:, None] >> (np.arange(16, dtype=np.uint64) * np.uint64(4))) & np.uint64(15)).astype(np.int16)
    out = blocks.copy()
    out[:, :8] = _bc3_alpha_blocks(values)[inverse.reshape(-1)]
    return out.tobytes()


def _block_grid(data: bytes, width: int, height: int, size: int) -> tuple[np.ndarray, int, int]:
    w4, h4 = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    return np.frombuffer(data[: w4 * h4 * size], dtype=np.uint8).reshape(w4 * h4, size), w4, h4


def _untile(values: np.ndarray, w4: int, h4: int, width: int, height: int) -> np.ndarray:
    return values.reshape(h4, w4, 4, 4).transpose(0, 2, 1, 3).reshape(h4 * 4, w4 * 4)[:height, :width]


def decode_bc2_alpha(data: bytes, width: int, height: int) -> np.ndarray:
    """Reference decoder for verification: linear BC2 blocks -> (H, W) uint8 alpha."""
    blocks, w4, h4 = _block_grid(data, width, height, 16)
    words = blocks[:, :8].copy().view("<u8")[:, 0]
    values = (words[:, None] >> (np.arange(16, dtype=np.uint64) * np.uint64(4))) & np.uint64(15)
    return _untile(values.astype(np.uint8) * 17, w4, h4, width, height)


def decode_bc3_alpha(data: bytes, width: int, height: int) -> np.ndarray:
    """Reference decoder for verification: linear BC3 blocks -> (H, W) uint8 alpha."""
    blocks, w4, h4 = _block_grid(data, width, height, 16)
    values = np.empty((len(blocks), 16), dtype=np.uint8)
    for n, block in enumerate(blocks):
        a0, a1 = int(block[0]), int(block[1])
        if a0 > a1:
            palette = [a0, a1] + [((7 - k) * a0 + k * a1 + 3) // 7 for k in range(1, 7)]
        else:
            palette = [a0, a1] + [((5 - k) * a0 + k * a1 + 2) // 5 for k in range(1, 5)] + [0, 255]
        bits = int.from_bytes(bytes(block[2:8]), "little")
        values[n] = [palette[(bits >> (3 * i)) & 7] for i in range(16)]
    return _untile(values, w4, h4, width, height)
