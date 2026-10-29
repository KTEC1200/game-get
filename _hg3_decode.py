#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CatSystem2 HG-3 图片解码器（算法照抄 GARbro-Mod ArcFormats/CatSystem/ImageHG3.cs）。

结构: 'HG-3' + u32 0x0C @4 + "stdinfo\0"@0x14 + HeaderSize@0x1C + W@0x24 + H@0x28
      + BPP@0x2C + CanvasW/H@0x44/48；HeaderSize 起分节链（8字节名 + u32 size，size=0 终止）
img0000: @HS+0x18 四个 i32（packed_data/data/packed_ctl/ctl），数据 @HS+0x28:
      zlib(data) + zlib(ctl)；ctl = LSB 位流: copy标记 + Elias 位计数交替 → 跳/拷 RLE
      → 位面重排 + ConvertValue(0x80 扩展) + 水平/垂直 delta；图自下而上
img_jpg: 分节 TOC；jpeg @toc['img_jpg']+12(i32 size)；可选 img_al alpha(zlib)
用法: python _hg3_decode.py <输入目录或文件> <输出目录>
"""
from __future__ import annotations

import io
import os
import struct
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def convert_value(val: int) -> int:
    carry = val & 1
    val >>= 1
    return (val ^ 0xFF) & 0xFF if carry else val & 0xFF


class LsbBits:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0
        self.bit = 0
        self.cur = 0

    def next_bit(self) -> int:
        # LsbBitStream：每字节从 LSB 到 MSB 依次出位
        if self.bit == 0:
            if self.pos >= len(self.buf):
                raise EOFError
            self.cur = self.buf[self.pos]
            self.pos += 1
            self.bit = 8
        r = self.cur & 1
        self.cur >>= 1
        self.bit -= 1
        return r

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.next_bit()
        return v


def get_bit_count(bits: LsbBits) -> int:
    n = 0
    while bits.next_bit() == 0:
        n += 1
        if n >= 0x20:
            raise ValueError('GetBitCount overflow')
    value = 1
    for _ in range(n):
        value = (value << 1) | bits.next_bit()
    return value


def apply_delta_np(output: bytes, w: int, h: int, psize: int) -> bytes:
    """ApplyDelta 的 numpy 向量化版（位面重排 + ConvertValue + 水平/垂直 delta ≡ cumsum mod 256）。"""
    import numpy as np
    plane_size = len(output) // 4
    b0 = np.frombuffer(output, np.uint8, plane_size, 0).astype(np.uint32)
    b1 = np.frombuffer(output, np.uint8, plane_size, plane_size).astype(np.uint32)
    b2 = np.frombuffer(output, np.uint8, plane_size, plane_size * 2).astype(np.uint32)
    b3 = np.frombuffer(output, np.uint8, plane_size, plane_size * 3).astype(np.uint32)
    i = np.arange(0x100, dtype=np.uint32)
    val = i & np.uint32(0xC0)
    val = (val << np.uint32(6)) | (i & np.uint32(0x30))
    val = (val << np.uint32(6)) | (i & np.uint32(0x0C))
    val = (val << np.uint32(6)) | (i & np.uint32(0x03))
    t0 = val << np.uint32(6)
    t1 = val << np.uint32(4)
    t2 = val << np.uint32(2)
    t3 = val
    v = t0[b0] | t1[b1] | t2[b2] | t3[b3]
    out = np.empty((plane_size, 4), np.uint8)
    for ch in range(4):
        byte = ((v >> np.uint32(8 * ch)) & np.uint32(0xFF)).astype(np.uint8)
        carry = byte & 1
        half = byte >> 1
        out[:, ch] = np.where(carry == 1, half ^ np.uint8(0xFF), half)
    px = out.reshape(-1, psize).cumsum(axis=0, dtype=np.uint8)            # 水平 delta：跨行连续单链
    px = px.reshape(h, w * psize).cumsum(axis=0, dtype=np.uint8)          # 垂直 delta
    return px.tobytes()


def stride_of(w, psize):
    return w * psize


def unpack_img0000_np(data: bytes, hs: int, w: int, h: int, bpp: int):
    psize = bpp // 8
    stride = w * psize
    packed_data, data_size, packed_ctl, ctl_size = struct.unpack_from('<4i', data, hs + 0x18)
    dstart = hs + 0x28
    pixels_raw = zlib.decompress(data[dstart:dstart + packed_data])
    ctl_raw = zlib.decompress(data[dstart + packed_data:dstart + packed_data + packed_ctl])
    bits = LsbBits(ctl_raw)
    copy = bits.next_bit() != 0
    output_size = get_bit_count(bits)
    output = bytearray(output_size)
    src = dst = 0
    while dst < output_size:
        count = get_bit_count(bits)
        if copy:
            output[dst:dst + count] = pixels_raw[src:src + count]
            src += count
        dst += count
        copy = not copy
    px = apply_delta_np(bytes(output), w, h, psize)
    return px, stride, True


def decode_hg3(data: bytes):
    """返回 PIL.Image。本作方言：0x14 起就是分节链（name 8B + u32 size，next = pos + size），
    stdinfo 是第一节； GARbro 模型里 HeaderSize(0x1C) 是 stdinfo 的 size 而非节起始偏移。"""
    from PIL import Image
    if data[:4] != b'HG-3':
        raise ValueError('非 HG-3')
    u32 = lambda o: struct.unpack_from('<I', data, o)[0]
    if u32(4) != 0x0C:
        raise ValueError(f'版本字段 {u32(4)}')
    if data[0x14:0x1C] != b'stdinfo\0':
        raise ValueError('无 stdinfo')
    w, h = u32(0x24), u32(0x28)
    bpp = struct.unpack_from('<i', data, 0x2C)[0]
    if bpp not in (24, 32):
        raise ValueError(f'BPP {bpp}')
    # 分节链从 0x14 开始
    toc = {}
    pos = 0x14
    img_start = None
    for _ in range(64):
        name = data[pos:pos + 8].split(b'\0')[0].decode('latin1')
        size = u32(pos + 8)
        toc[name] = pos
        if name in ('img0000', 'img_jpg', 'img_wbp'):
            img_start = pos
            img_name = name
            break
        if size == 0:
            raise ValueError('分节链终止而无 img 节')
        pos += size
    if img_start is None:
        raise ValueError('无 img 节')
    if img_name == 'img0000':
        # 四个 i32 @ 节起点+0x18，数据 @ 节起点+0x28
        px, stride, flipped = unpack_img0000_np(data, img_start, w, h, bpp)
        mode = 'RGBA' if bpp == 32 else 'RGB'
        im = Image.frombytes(mode, (w, h), px, 'raw',
                             'BGRA' if bpp == 32 else 'BGR', stride)
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
        return im
    if img_name == 'img_jpg':
        jp = img_start + 12
        jpeg_size = struct.unpack_from('<i', data, jp)[0]
        import io as _io
        im = Image.open(_io.BytesIO(data[jp + 4:jp + 4 + jpeg_size]))
        im = im.convert('RGB')
        w2, h2 = im.size
        alpha = None
        if 'img_al' in toc:
            a0 = toc['img_al'] + 0x10
            packed, asize = struct.unpack_from('<2i', data, a0)
            alpha = zlib.decompress(data[a0 + 8:a0 + 8 + packed])
        total = w2 * h2
        out = bytearray(total * 4)
        px = im.tobytes()
        for i in range(total):
            out[i * 4] = px[i * 3]
            out[i * 4 + 1] = px[i * 3 + 1]
            out[i * 4 + 2] = px[i * 3 + 2]
            out[i * 4 + 3] = alpha[i] if alpha else 0xFF
        im2 = Image.frombytes('RGBA', (w2, h2), bytes(out), 'raw', 'BGRA')
        return im2
    raise ValueError('img_wbp(webp) 未支持')


def _decode_one(args):
    p, src, out = args
    from PIL import Image
    try:
        data = p.read_bytes()
        im = decode_hg3(data)
        rel = p.relative_to(src)
        dst = (out / rel).with_suffix('.png')
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst)
        return True, ''
    except Exception as exc:
        return False, f'{p.name}: {exc}'


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else src
    files = [src] if src.is_file() else sorted(p for p in src.rglob('*') if p.suffix.lower() in ('.hg3', '.nm3', '.gf3', '.g3'))
    print(f'{len(files)} 个 HG3 文件')
    import multiprocessing as mp
    ok = fail = 0
    fails = []
    with mp.Pool(8) as pool:
        for i, (good, msg) in enumerate(pool.imap_unordered(_decode_one, [(p, src, out) for p in files]), 1):
            if good:
                ok += 1
            else:
                fail += 1
                if len(fails) < 10:
                    fails.append(msg)
            if i % 500 == 0:
                print(f'  [{i}/{len(files)}] ok={ok} fail={fail}', flush=True)
    print(f'HG3 decode: ok {ok} fail {fail}')
    for m in fails:
        print('  ', m)
    return 0 if fail == 0 else 1


from pathlib import Path

if __name__ == '__main__':
    raise SystemExit(main())
