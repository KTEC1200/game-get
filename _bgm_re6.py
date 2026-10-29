# -*- coding: utf-8 -*-
import struct
import capstone
d = open(r"D:\HY\夕凪荘的S级的女朋友们\resident.dll", "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B
vt = struct.pack("<I", 0x102F2718)
pos = 0
hits = []
while True:
    i = d.find(vt, pos)
    if i < 0:
        break
    hits.append(i)
    pos = i + 1
lines = ["vtable ptr occurrences: %d" % len(hits)]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
for i in hits:
    va = IMAGE_BASE + TEXT_VA + (i - TEXT_OFF) if TEXT_OFF <= i < TEXT_OFF + TEXT_SZ else None
    lines.append("file 0x%X va=%s" % (i, ("0x%08X" % va) if va else "not .text"))
    if va:
        off = i - 0x40
        cnt = 0
        for ins in md.disasm(d[off:i + 0x60], IMAGE_BASE + TEXT_VA + (off - TEXT_OFF)):
            mark = "  <<<<" if ins.address == va else ""
            lines.append("  0x%08X  %-18s %s %s%s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str, mark))
            cnt += 1
            if cnt > 40:
                break
        lines.append("")
with open(r"D:\K\zcode\game\_extracted\_bgm_re6.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("done", len(hits))
