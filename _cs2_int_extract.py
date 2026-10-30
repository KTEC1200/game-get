#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CatSystem2 .int 提取器（算法照抄 GARbro-Mod ArcFormats/CatSystem/ArcINT.cs + Blowfish.cs）。

加密链: 口令在 cs2.exe 的 PE 资源 DATA/V_CODE2（用 KEY/KEY_CODE^0xCD 或 "windmill" 的
Blowfish 解出）→ EncodePassPhrase 得主密钥 → 每 .int 头 0x4C 处 u32 种子驱动 GARbro-MT
生成 4 字节 Blowfish 密钥 → 索引与条目数据均 Blowfish-ECB（小端打包），文件名 52 字母表轮换。

用法: python _cs2_int_extract.py <游戏根目录> <输出目录> [--no-names] [--manifest PATH]
"""
from __future__ import annotations

import mmap
import os
import struct
import sys
from pathlib import Path

# 不要把 sys.stdout 换成新的 TextIOWrapper：这个模块会被 orchestrator 在 import 期加载，
# 而 import 期替换 stdout 会把 pytest 的捕获对象挤掉引用、连带关掉它的临时文件
# （症状是 `ValueError: I/O operation on closed file` + 「no tests ran」）。
# 只做原地 reconfigure；拿不到 reconfigure 的流（如测试捕获对象）就跳过。
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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


_PURE_WARNED = False

#: `decipher_fast` 的分块大小：32 MiB 足够大（少调用）又足够小（峰值内存可控）。
#: 本作最大的条目有几百 MB，整段一次性做 numpy 变换会吃掉 4~5 倍内存 —— 13.8 GiB 的
#: 机器上实测被压死（进程被杀、日志都没留）。分块后峰值只跟这个常量有关。
#: 想要更省内存可以调小；必须是 8 的整数倍（Blowfish 块 = 8 字节）。
_CHUNK = 32 * 1024 * 1024


def decipher_fast(bf, data: bytearray, length: int):
    """GARbro 小端打包的 Blowfish-ECB 解密 == pycryptodome 大端解密 + 输入/输出半块字节反转。

    快路径要 numpy + pycryptodome；**缺了不再抛异常崩掉**，退回纯 Python 的
    `Blowfish.decipher()`（正确但慢两个数量级——8 GB 级的 .int 会从分钟变成小时级），
    并明确告诉用户怎么恢复快路径。宁可能跑完但慢，也不要一条 ImportError 把整条链判死。

    **按 `_CHUNK` 分块**：原版一次性对整段做 numpy 变换，峰值内存是数据本身的 4~5 倍——
    本作最大的条目有几百 MB，13.8 GiB 的机器上实测被压死（进程被杀、连日志都没留下）。
    分块后峰值只跟 `_CHUNK` 有关。Blowfish-ECB 逐块独立、半块反转也是每 8 字节一次，
    所以按 8 的整数倍切段**结果完全相同**（`test_decipher_fast_chunking_is_equivalent` 盯着这点）。
    """
    global _PURE_WARNED
    try:
        import numpy as np
        from Crypto.Cipher import Blowfish as PCBlowfish
    except ImportError as exc:
        if not _PURE_WARNED:
            _PURE_WARNED = True
            print(f'[WARN] 快路径不可用（{exc.name} 缺失），退回纯 Python Blowfish——会慢很多；'
                  f'装 `pip install numpy pycryptodome` 可恢复', file=sys.stderr)
        bf.decipher(data, length)
        return
    c = PCBlowfish.new(bf.key, PCBlowfish.MODE_ECB)
    step = max(8, _CHUNK // 8 * 8)                 # 必须是 8 的整数倍（Blowfish 块 = 8B）
    for start in range(0, length, step):
        end = min(start + step, length)
        inn = (np.frombuffer(bytes(memoryview(data)[start:end]), np.uint8)
                 .reshape(-1, 2, 4)[:, :, ::-1].tobytes())
        out = c.decrypt(inn)
        data[start:end] = (np.frombuffer(out, np.uint8)
                             .reshape(-1, 2, 4)[:, :, ::-1].tobytes())


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


# ---------------- 地面真相与清单（唯一出处） ----------------
INT_MAGIC = b'KIF\x00'
HG3_MAGIC = b'HG-3'          # 与 _hg3_tool.cs 的 IsHg3Magic() 逐字节一致，改一处必须改两处
EXE_NAMES = ('cs2.exe', 'cs2_Crack.exe')


def _head(p, n: int = 4) -> bytes:
    """只读文件头 n 字节（别为了看一个魔数把 2 GB 的包整个读进内存）。"""
    try:
        with open(p, 'rb') as fh:
            return fh.read(n)
    except OSError:
        return b''


def is_int(path) -> bool:
    return _head(path) == INT_MAGIC


def is_hg3(path) -> bool:
    """HG-3 家族判据 = 魔数 `HG-3`。

    **只能按魔数，不能按扩展名**：引擎会把扩展名二次混淆（.hg3/.nm3/.gf3 以及任意名），
    照扩展名筛必然漏。与 `_hg3_tool.cs:IsHg3Magic()` 同一判据。
    """
    return _head(path) == HG3_MAGIC


def int_files(root) -> list:
    return sorted(p for p in Path(root).iterdir()
                  if p.is_file() and p.suffix.lower() == '.int')


def expected_counts(root) -> dict:
    """地面真相：每个 KIF `.int` 的条目数（头部声明 `count - 1`，第 0 条是索引自己）。

    **这是唯一出处**：`main()` 的收尾对账与 `orchestrator.py` 的期望值都调它。
    别在两边各写一份——51 个包里一边算 53500、另一边算 53499，谁也说不清谁错。
    """
    by_arc: dict[str, int] = {}
    unlistable: list[str] = []
    for p in int_files(root):
        head = _head(p, 0x50)
        if len(head) < 0x50 or head[:4] != INT_MAGIC:
            unlistable.append(p.name)
            continue
        count, = struct.unpack_from('<I', head, 4)
        by_arc[p.name] = max(0, count - 1)
    return {'total': sum(by_arc.values()), 'by_arc': by_arc,
            'unlistable': unlistable, 'arcs': sorted(by_arc)}


def resolve_main_key(root) -> tuple:
    """口令取自 `cs2.exe` 的 PE 资源 DATA/V_CODE2；读不到就用本作实测值兜底。"""
    for e in EXE_NAMES:
        p = Path(root) / e
        if p.is_file():
            try:
                pp = get_passphrase(str(p))
            except Exception:
                pp = None
            if pp:
                return encode_passphrase(pp), pp
    return 0x212C5F31, None


def write_manifest(out_root, root, exp, n_ok, n_fail, main_key, passphrase, fails, path) -> dict:
    """按 manifest 契约写清单（解密做在落盘之前 → 磁盘上没有中间格式 → 走 counts_flat）。"""
    import manifest as mf
    out_root = Path(out_root)          # main() 传来的是 str，契约函数要 Path
    root = Path(root)
    counts_block = mf.counts_flat(out_root)
    arcs = [{'name': n, 'entries': c} for n, c in sorted(exp['by_arc'].items())]
    for n in exp['unlistable']:
        arcs.append({'name': n, 'entries': None, 'note': '非 KIF 或头不足 0x50，列不出条目'})
    man = mf.build(
        tool='_cs2_int_extract.py',
        engine='CatSystem2',
        source={'game_dir': str(root), 'out_root': str(out_root),
                'main_key': f'{main_key:08X}', 'passphrase_found': bool(passphrase),
                'archives': arcs, 'unlistable': exp['unlistable']},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(exp['total'], counts_block['raw']['total']),
        verify={'verified': False,
                'note': '本工具只做解密/落盘，不做内容级验收；请用 orchestrator.py 或 _verify_media.py'},
        postprocess=[],
        extra={'fail_count': len(fails), 'fails': fails[:50], 'written': n_ok},
    )
    mf.write(path, man)
    return man


# ---------------- 主流程 ----------------
# 魔数 → 扩展名。**CatSystem2 的扩展名是二次混淆过的**：同一批 OggS 语音可能叫
# `.KCC`/`.umm`/`.nff`（实测 pcm_AA 的 3907 个 OggS 里只有 148 个恰好还原成 `.ogg`，
# 约 1/26，正是「按文件轮换、转到 0 才露出真名」的比例），所以「这个文件是什么」
# 只能问内容，不能问名字。表外的归 `.bin`（当数据文件处理，不当媒体）。
_SNIFF = (
    (b'HG-3', '.hg3'),               # 与 _hg3_tool.cs:IsHg3Magic() 逐字节一致，别放宽到 HG-
    (b'OggS', '.ogg'),
    (b'RIFF', '.wav'),
    (b'\x89PNG\r\n\x1a\n', '.png'),
    (b'DDST', '.dds'),
    (b'BM', '.bmp'),
    (b'\xff\xd8\xff', '.jpg'),
    (b'\x00\x00\x01\xba', '.mpg'),   # MPEG-PS（movie.int 里的视频就是它）
    (b'\x00\x00\x01\xb3', '.mpg'),
    (b'\x30\x26\xb2\x75', '.wmv'),   # ASF
    (b'KIF\x00', '.int'),
)


def sniff_ext(b: bytes) -> str:
    """按魔数猜扩展名（内容优先，扩展名不可信）。"""
    for magic, ext in _SNIFF:
        if len(b) >= len(magic) and b.startswith(magic):
            return ext
    if b[4:8] == b'ftyp':
        return '.mp4'
    if b[:3] == b'ID3' or (len(b) >= 2 and b[0] == 0xFF and b[1] & 0xE0 == 0xE0):
        return '.mp3'
    if b[:2] == b'\x78\x9c' or b[:2] == b'\x78\xda':
        return '.zz'
    if b[:2] == b'PK':
        return '.zip'
    return '.bin'


def hg3_files(root) -> list:
    """全部 HG-3 文件：**按魔数扫全树**，不看扩展名（引擎把扩展名混淆掉了）。"""
    root = Path(root)
    return sorted(p for p in root.rglob('*') if p.is_file() and is_hg3(p))


def hg3_expected_png(root, files=None) -> dict:
    """HG-3 → PNG 的期望产出：按 `_hg3_tool` 的落盘规则算**去重后**的 PNG 相对路径。

    `_hg3_tool.cs:222` 是 `dst = Path.ChangeExtension(dst, ".png")`，所以同目录同 stem 的
    两个 HG-3（如 `a.hg3` 与 `a.nm3`）会**互相覆盖**：解码成功数 ≠ PNG 成品数
    （历史实测正好是解 4502、交付 4499）。期望值必须按去重后的路径算，
    拿文件数当 `min_products` 会在有撞车时误判「产物不足」。
    """
    root = Path(root)
    files = hg3_files(root) if files is None else list(files)
    rels = {p.relative_to(root).with_suffix('.png').as_posix() for p in files}
    return {'files': [str(p) for p in files], 'count': len(files),
            'png': sorted(rels), 'png_count': len(rels),
            'collisions': len(files) - len(rels)}


def _extract_one(data, name: str, out_root: str, main_key: int, no_names: bool,
                 fails: list) -> tuple[int, int]:
    """解一个 `.int`（`data` 是 mmap 视图），返回 `(落盘, 失败)`。

    每个条目独立解密：峰值内存 = 单个条目 × `decipher_fast` 的常数因子，
    与包大小无关（2.3 GB 的包也一样）。
    """
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
                print(f'  FAIL {fname}: off={foff:#x} size={fsize}', flush=True)
            fails.append(f'{name}:{fname}: off={foff:#x} size={fsize}')
            continue
        blob = bytearray(data[foff:foff + fsize])
        decipher_fast(bf, blob, fsize // 8 * 8)
        if no_names:
            fname = f'{fname}{sniff_ext(bytes(blob))}'
        elif not os.path.splitext(fname)[1]:
            fname = fname + sniff_ext(bytes(blob))
        outp = os.path.join(dest, fname)
        os.makedirs(os.path.dirname(outp) or dest, exist_ok=True)
        with open(outp, 'wb') as fh:
            fh.write(blob)
        ok += 1
    return ok, fail


def main() -> int:
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith('--')]
    if len(args) < 2:
        print('usage: python _cs2_int_extract.py <游戏根目录> <输出目录> '
              '[--no-names] [--manifest PATH]')
        return 2
    root, out_root = args[0], args[1]
    no_names = '--no-names' in argv
    man_path = None
    if '--manifest' in argv:
        i = argv.index('--manifest')
        if i + 1 >= len(argv) or argv[i + 1].startswith('--'):
            print('[ERROR] --manifest 需要一个路径参数', file=sys.stderr)
            return 2
        man_path = Path(argv[i + 1])

    main_key, passphrase = resolve_main_key(root)
    print(f'main_key = {main_key:08X} (names: {"on" if not no_names else "OFF"})'
          + ('' if passphrase else '  [兜底值：cs2.exe 里没读到口令]'), flush=True)

    # 地面真相先算出来：失败路径也要能报出「期望多少」，否则对账失败时看不出差在哪。
    exp = expected_counts(root)
    print(f'地面真相：{len(exp["arcs"])} 个 .int，共 {exp["total"]} 条'
          + (f'；{len(exp["unlistable"])} 个列不出' if exp['unlistable'] else ''), flush=True)
    if not exp['arcs']:
        print('[ERROR] 这个目录里没有 KIF 格式的 .int', file=sys.stderr)
        return 1

    grand_ok = grand_fail = 0
    fails: list = []
    for name in exp['arcs']:
        path = os.path.join(root, name)
        # **mmap 而不是 read()**：最大的包有 2.3 GB，整包读进内存对 13.8 GiB 的机器是致命的
        # （实测被压死）。mmap 只占可回收的页缓存，条目切片仍按需拷出来。
        with open(path, 'rb') as fh:
            data = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                count, = struct.unpack_from('<I', data, 4)
                ok, fail = _extract_one(data, name, out_root, main_key, no_names, fails)
            finally:
                data.close()
        grand_ok += ok
        grand_fail += fail
        flag = 'OK ' if fail == 0 else '!! '
        # flush=True：万一进程后面被内存压死，日志里也要留下「做到哪了」
        print(f'{flag}{name:<18} 声明 {count - 1:>6}  落盘 {ok:>6}  失败 {fail}', flush=True)
    print(f'\n合计 ok {grand_ok} fail {grand_fail}', flush=True)

    if man_path is not None:
        try:
            man = write_manifest(out_root, root, exp, grand_ok, grand_fail,
                                 main_key, passphrase, fails, man_path)
            rec = man['reconcile']
            print(f'对账：索引 {rec["expected"]} vs 落盘 {rec["actual"]} (diff={rec["diff"]})')
            if rec['diff'] not in (0, None):
                grand_fail += 1
        except Exception as exc:      # 清单写不进去不该影响已经落盘的产物
            print(f'  [WARN] manifest 写入失败（产物不受影响）：{exc}', file=sys.stderr)
    return 0 if grand_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
