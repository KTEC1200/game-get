# -*- coding: utf-8 -*-
import struct
d = open(r"D:\HY\夕凪荘的S级的女朋友们\resident.dll", "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B
RD_VA, RD_OFF, RD_SZ = 0x2D8000, 0x2D6C00, 0x0999F6

def off2va(off):
    if TEXT_OFF <= off < TEXT_OFF + TEXT_SZ:
        return IMAGE_BASE + TEXT_VA + (off - TEXT_OFF)
    if RD_OFF <= off < RD_OFF + RD_SZ:
        return IMAGE_BASE + RD_VA + (off - RD_OFF)
    return None

# 搜指向 0x1029E320 的指针（vtable 槽位）
target = struct.pack("<I", 0x1029E320)
pos = 0
hits = []
while True:
    i = d.find(target, pos)
    if i < 0:
        break
    hits.append(i)
    pos = i + 1
lines = []
for i in hits:
    va = off2va(i)
    lines.append("ptr@file 0x%X va=%s" % (i, ("0x%08X" % va) if va else "?"))
    # 如果在 .rdata 里，往前找 vtable 起点：vtable 前一个 dword 通常不在代码段范围或为 0
    if va and RD_OFF <= i < RD_OFF + RD_SZ:
        # 往回走，直到离开 .rdata 或遇到非代码指针
        j = i
        while j - 4 >= RD_OFF:
            prev = struct.unpack_from("<I", d, j - 4)[0]
            if not (0x10001000 <= prev < 0x102D7000):
                break
            j -= 4
        lines.append("   vtable start guess va=0x%08X ; slot index of func = %d" % (
            IMAGE_BASE + RD_VA + (j - RD_OFF), (i - j) // 4))
        # 列出 vtable 前 8 个槽
        for s in range(0, 8):
            v = struct.unpack_from("<I", d, j + 4*s)[0]
            lines.append("     [%d] 0x%08X" % (s, v))
with open(r"D:\K\zcode\game\_extracted\_bgm_re5.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
