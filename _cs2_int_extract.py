#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CatSystem2 .int 提取器（算法照抄 GARbro-Mod ArcFormats/CatSystem/ArcINT.cs + Blowfish.cs）。

加密链: 口令在 cs2.exe 的 PE 资源 DATA/V_CODE2（用 KEY/KEY_CODE^0xCD 或 "windmill" 的
Blowfish 解出）→ EncodePassPhrase 得主密钥 → 每 .int 头 0x4C 处 u32 种子驱动 GARbro-MT
生成 4 字节 Blowfish 密钥 → 索引与条目数据均 Blowfish-ECB（小端打包），文件名 52 字母表轮换。

用法: python _cs2_int_extract.py <游戏根目录> <输出目录>
"""
from __future__ import annotations

import os
import struct
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---------------- Blowfish（标准 Feistel + LE 打包，GARbro 变体） ----------------
P_INIT = [
    0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344, 0xA4093822, 0x299F31D0,
    0x082EFA98, 0xEC4E6C89, 0x452821E6, 0x38D01377, 0xBE5466CF, 0x34E90C6C,
    0xC0AC29B7, 0xC97C50DD, 0x3F84D5B5, 0xB5470917, 0x9216D5D9, 0x8979FB1B,
]
S_INIT = [
    0xD1310BA6, 0x98DFB5AC, 0x2FFD72DB, 0xD01ADFB7, 0xB8E1AFED, 0x6A267E96,
    0xBA7C9045, 0xF12C7F99, 0x24A19947, 0xB3916CF7, 0x0801F2E2, 0x858EFC16,
    0x636920D8, 0x71574E69, 0xA458FEA3, 0xF4933D7E, 0x0D95748F, 0x728EB658,
    0x718BCD58, 0x82154AEE, 0x7B54A41D, 0xC25A59B5, 0x9C30D539, 0x2AF26013,
    0xC5D1B023, 0x286085F0, 0xCA417918, 0xB8DB38EF, 0x8E79DCB0, 0x603A180E,
    0x6C9E0E8B, 0xB01E8A3E, 0xD71577C1, 0xBD314B27, 0x78AF2FDA, 0x55605C60,
    0xE65525F3, 0xAA55AB94, 0x57489862, 0x63E81440, 0x55CA396A, 0x2AAB10B6,
    0xB4CC5C34, 0x1141E8CE, 0xA15486AF, 0x7C72E993, 0xB3EE1411, 0x636FBC2A,
    0x2BA9C55D, 0x741831F6, 0xCE5C3E16, 0x9B87931E, 0xAFD6BA33, 0x6C24CF5C,
    0x7A325381, 0x28958677, 0x3B8F4898, 0x6B4BB9C4, 0xC6B3810D, 0x0A71DCD3,
]


def init_boxes():
    global S_BOXES
    # 标准 Blowfish 常数 = π 的十六进制小数（P 18 项 + S 4×256 项）
    # BBP 级别公式 Decimal 计算；需要 1042 words × 8 hex = 8336 hex 位 ≈ 3010 位十进制 → prec 4200、k≤2700
    # 标准 Blowfish 常数 = π 的十六进制小数（P 18 项 + S 4×256 项 = 1042 words = 8336 hex 位）
    # 整数 Machin 公式：π = 16·arctan(1/5) − 4·arctan(1/239)，纯整数运算
    one = 16 ** 8800

    def arctan_inv(x, one):
        total = term = one // x
        x2 = x * x
        k = 3
        sign = -1
        while term:
            term //= x2
            total += sign * (term // k)
            sign = -sign
            k += 2
        return total

    pi_scaled = 16 * arctan_inv(5, one) - 4 * arctan_inv(239, one)
    hexdigits = format(pi_scaled, 'x')
    assert hexdigits[0] == '3', 'pi int part wrong'
    frac = hexdigits[1:]
    assert len(frac) >= 8336, 'pi hex too short: %d' % len(frac)
    words = [int(frac[i * 8:(i + 1) * 8], 16) for i in range(18 + 1024)]
    p = words[:18]
    s = [words[18 + 256 * r: 18 + 256 * (r + 1)] for r in range(4)]
    # 自检：与标准常数前几项必须一致
    assert p[:6] == P_INIT[:6], 'P mismatch: %08X' % p[0]
    assert s[0][:6] == S_INIT[:6], 'S mismatch: %08X' % s[0][0]
    S_BOXES = (p, s)

init_boxes()


class Blowfish:
    def __init__(self, key: bytes):
        self.key = bytes(key)
        p, s = S_BOXES
        self.p = list(p)
        self.s = [list(r) for r in s]
        j = 0
        for i in range(18):
            word = 0
            for _ in range(4):
                word = ((word << 8) | key[j]) & 0xFFFFFFFF
                j = (j + 1) % len(key)
            self.p[i] ^= word
        xl = xr = 0
        for i in range(0, 18, 2):
            xl, xr = self._encipher(xl, xr)
            self.p[i], self.p[i + 1] = xl, xr
        for r in range(4):
            for i in range(0, 256, 2):
                xl, xr = self._encipher(xl, xr)
                self.s[r][i], self.s[r][i + 1] = xl, xr

    def _f(self, x):
        a = (x >> 24) & 0xFF
        b = (x >> 16) & 0xFF
        c = (x >> 8) & 0xFF
        d = x & 0xFF
        return (((self.s[0][a] + self.s[1][b]) & 0xFFFFFFFF) ^ self.s[2][c]) + self.s[3][d] & 0xFFFFFFFF

    def _encipher(self, xl, xr):
        p = self.p
        for i in range(16):
            xl ^= p[i]
            xr = (self._f(xl) ^ xr) & 0xFFFFFFFF
            xl, xr = xr, xl
        xl, xr = xr, xl
        xr ^= p[16]
        xl ^= p[17]
        return xl, xr

    def decipher_block(self, xl, xr):
        p = self.p
        for i in range(17, 1, -1):
            xl ^= p[i]
            xr = (self._f(xl) ^ xr) & 0xFFFFFFFF
            xl, xr = xr, xl
        xl, xr = xr, xl
        xr ^= p[1]
        xl ^= p[0]
        return xl, xr

    def decipher(self, data: bytearray, length: int):
        assert length % 8 == 0
        for i in range(0, length, 8):
            xl = int.from_bytes(data[i:i + 4], 'little')
            xr = int.from_bytes(data[i + 4:i + 8], 'little')
            xl, xr = self.decipher_block(xl, xr)
            data[i:i + 4] = xl.to_bytes(4, 'little')
            data[i + 4:i + 8] = xr.to_bytes(4, 'little')


def decipher_fast(bf, data: bytearray, length: int):
    """GARbro 小端打包的 Blowfish-ECB 解密 == pycryptodome 大端解密 + 输入/输出半块字节反转。"""
    import numpy as np
    from Crypto.Cipher import Blowfish as PCBlowfish
    c = PCBlowfish.new(bf.key, PCBlowfish.MODE_ECB)
    inn = np.frombuffer(bytes(memoryview(data)[:length]), np.uint8).reshape(-1, 2, 4)[:, :, ::-1].tobytes()
    out = bytearray(c.decrypt(inn))
    swapped = np.frombuffer(out, np.uint8).reshape(-1, 2, 4)[:, :, ::-1].tobytes()
    data[:length] = swapped


# ---------------- GARbro MersenneTwister（自定义 SRand + tempering） ----------------
class MT:
    def __init__(self, seed):
        self.mt = [0] * 624
        self.mti = 624
        self.srand(seed & 0xFFFFFFFF)

    def srand(self, seed):
        for i in range(624):
            upper = seed & 0xFFFF0000
            seed = (69069 * seed + 1) & 0xFFFFFFFF
            self.mt[i] = upper | ((seed & 0xFFFF0000) >> 16)
            seed = (69069 * seed + 1) & 0xFFFFFFFF
        self.mti = 624

    def rand(self):
        if self.mti >= 624:
            mt = self.mt
            for kk in range(227):
                y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7FFFFFFF)
                mt[kk] = mt[kk + 397] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
            for kk in range(227, 623):
                y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7FFFFFFF)
                mt[kk] = mt[kk - 227] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
            y = (mt[623] & 0x80000000) | (mt[0] & 0x7FFFFFFF)
            mt[623] = mt[396] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
            self.mti = 0
        y = self.mt[self.mti]
        self.mti += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y &= 0xFFFFFFFF
        y ^= y >> 18
        return y


# ---------------- CRC32 表（EncodePassPhrase 用） ----------------
def crc32_table():
    tbl = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
        tbl.append(c)
    return tbl
CRC_T = crc32_table()


def encode_passphrase(password: str) -> int:
    key = 0xFFFFFFFF
    for c in password.encode('cp932'):
        key = (~CRC_T[(key >> 24) ^ c]) & 0xFFFFFFFF ^ ((key << 8) & 0xFFFFFFFF)
    return key & 0xFFFFFFFF


ALPHABET = "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA"


def decipher_name(buf: bytes, key: int) -> str:
    k = (key >> 24) + (key >> 16) + (key >> 8) + key
    k &= 0xFF
    out = bytearray()
    for ch in buf:
        if ch == 0:
            break
        j = ALPHABET.find(chr(ch))
        if j != -1:
            j -= k % 0x34
            if j < 0:
                j += 0x34
            out.append(ord(ALPHABET[0x33 - j]))
        else:
            out.append(ch)
        k = (k + 1) & 0xFF
    return out.decode('cp932', 'replace')


# ---------------- PE 资源解析 ----------------
def pe_resources(path: str) -> dict:
    """返回 {(type, name): bytes}（自定义命名资源）"""
    data = open(path, 'rb').read()
    e = struct.unpack_from('<I', data, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from('<H', data, coff + 2)[0]
    opt_size = struct.unpack_from('<H', data, coff + 16)[0]
    opt = coff + 20
    rsrc_rva = struct.unpack_from('<I', data, opt + 112)[0]
    sec_off = opt + opt_size
    secs = []
    for i in range(nsec):
        o = sec_off + i * 40
        name, vsize, vaddr, rsize, roff = struct.unpack_from('<8sIIII', data, o)
        secs.append((vaddr, roff, rsize))

    def rva2off(rva):
        for vaddr, roff, rsize in secs:
            if vaddr <= rva < vaddr + max(rsize, 0x1000):
                return roff + (rva - vaddr)
        return None

    out = {}

    def walk(off, level, path_names):
        if off is None:
            return
        n_named, n_id = struct.unpack_from('<HH', data, off + 12)
        for i in range(n_named + n_id):
            eo = off + 16 + i * 8
            nameid, v = struct.unpack_from('<II', data, eo)
            if nameid & 0x80000000:
                noff = rva2off(rsrc_rva + (nameid & 0x7FFFFFFF))
                ln = struct.unpack_from('<H', data, noff)[0]
                nm = data[noff + 2:noff + 2 + ln * 2].decode('utf-16-le')
            else:
                nm = str(nameid)
            if v & 0x80000000:
                walk(rva2off(rsrc_rva + (v & 0x7FFFFFFF)), level + 1, path_names + [nm])
            else:
                drva, dsize = struct.unpack_from('<II', data, v)
                doff = rva2off(drva)
                out[tuple(path_names)] = data[doff:doff + dsize]

    walk(rva2off(rsrc_rva), 0, [])
    return out


def get_passphrase(exe_path: str) -> str | None:
    res = pe_resources(exe_path)
    code = res.get(('DATA', 'V_CODE2'))
    if not code or len(code) < 8:
        return None
    key = res.get(('KEY', 'KEY_CODE'))
    if key:
        key = bytes(b ^ 0xCD for b in key)
    else:
        key = b"windmill"
    bf = Blowfish(key)
    buf = bytearray(code)
    bf.decipher(buf, len(buf) // 8 * 8)
    nul = buf.find(b'\0')
    return buf[:nul if nul >= 0 else len(buf)].decode('cp932', 'replace')


# ---------------- 主流程 ----------------
def sniff_ext(b: bytes) -> str:
    if b[:4] == b'HG-3' or b[:3] == b'HG-': return '.hg3'
    if b[:4] == b'OggS': return '.ogg'
    if b[:4] == b'RIFF': return '.wav'
    if b[:3] == b'ID3' or (b[0] == 0xFF and b[1] & 0xE0 == 0xE0): return '.mp3'
    if b[:4] == b'KIF\x00': return '.int'
    if b[:4] == b'DDST': return '.dds'
    if b[:2] == b'BM': return '.bmp'
    if b[:3] == b'\x89PNG': return '.png'
    if b[:2] == b'\x78\x9c' or b[:2] == b'\x78\xda': return '.zz'
    if b[:2] == b'PK': return '.zip'
    return '.bin'


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    root, out_root = args[0], args[1]
    no_names = '--no-names' in sys.argv
    exes = ['cs2.exe', 'cs2_Crack.exe']
    passphrase = None
    for e in exes:
        p = os.path.join(root, e)
        if os.path.exists(p):
            try:
                passphrase = get_passphrase(p)
            except Exception:
                passphrase = None
            if passphrase:
                break
    main_key = encode_passphrase(passphrase) if passphrase else 0x212C5F31
    print(f'main_key = {main_key:08X} (names: {"on" if not no_names else "OFF"})')

    ints = sorted(f for f in os.listdir(root) if f.lower().endswith('.int'))
    print(f'{len(ints)} 个 .int')
    grand_ok = grand_fail = 0
    for name in ints:
        path = os.path.join(root, name)
        data = open(path, 'rb').read()
        if data[:4] != b'KIF\x00':
            print(f'[跳过] {name}: 非KIF')
            continue
        count, = struct.unpack_from('<I', data, 4)
        seed, = struct.unpack_from('<I', data, 0x4C)
        mt = MT(seed)
        bf = Blowfish(struct.pack('<I', mt.rand()))
        dest = os.path.join(out_root, name[:-4])
        os.makedirs(dest, exist_ok=True)
        ok = fail = 0
        for i in range(1, count):
            base = 8 + i * 0x48
            name_buf = data[base:base + 0x40]
            off_raw, size_raw = struct.unpack_from('<II', data, base + 0x40)
            off = (off_raw + i) & 0xFFFFFFFF
            xl, xr = bf.decipher_block(off, size_raw)
            foff, fsize = xl, xr
            mt2 = MT(main_key + i)
            nk = mt2.rand()
            fname = decipher_name(name_buf, nk).replace('\\', '/') if not no_names else ''
            if not fname:
                fname = f'e{i:05d}'
            if foff + fsize > len(data) or fsize == 0:
                fail += 1
                if fail <= 3:
                    print(f'  FAIL {fname}: off={foff:#x} size={fsize}')
                continue
            blob = bytearray(data[foff:foff + fsize])
            decipher_fast(bf, blob, fsize // 8 * 8)
            stem, ext = os.path.splitext(fname)
            if no_names:
                ext = sniff_ext(bytes(blob))
                fname = f'{fname}{ext}'
            elif not os.path.splitext(fname)[1]:
                fname = fname + sniff_ext(bytes(blob))
            outp = os.path.join(dest, fname)
            os.makedirs(os.path.dirname(outp) or dest, exist_ok=True)
            with open(outp, 'wb') as fh:
                fh.write(blob)
            ok += 1
        grand_ok += ok
        grand_fail += fail
        flag = 'OK ' if fail == 0 else '!! '
        print(f'{flag}{name:<18} 声明 {count - 1:>6}  落盘 {ok:>6}  失败 {fail}')
    print(f'\n合计 ok {grand_ok} fail {grand_fail}')
    return 0 if grand_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
