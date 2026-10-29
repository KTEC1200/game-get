# -*- coding: utf-8 -*-
import struct
import capstone
d = open(r"D:\HY\夕凪荘的S级的女朋友们\resident.dll", "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B

# ① 搜 call 0x1029E1F0 / 0x1029E280（E8 rel32）
targets = {0x1029E1F0: "ctor", 0x1029E280: "dtor"}
hits = []
for i in range(TEXT_OFF, TEXT_OFF + TEXT_SZ - 5):
    if d[i] == 0xE8:
        rel = struct.unpack_from("<i", d, i + 1)[0]
        site_va = IMAGE_BASE + TEXT_VA + (i - TEXT_OFF)
        tgt = site_va + 5 + rel
        if tgt in targets:
            hits.append((site_va, targets[tgt]))
lines = ["calls to ctor/dtor:"]
for a, t in hits:
    lines.append("  %s called from 0x%08X" % (t, a))

# ② 搜 lea reg, [reg+0x70]（8D /r disp8=0x70）
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
lea_hits = []
code = d[TEXT_OFF:TEXT_OFF + TEXT_SZ]
for ins in md.disasm(code, IMAGE_BASE + TEXT_VA):
    if ins.mnemonic == "lea" and "+ 0x70]" in ins.op_str:
        lea_hits.append((ins.address, ins.op_str))
lines.append("")
lines.append("lea [reg+0x70]: %d" % len(lea_hits))
for a, s in lea_hits:
    lines.append("  0x%08X  lea %s" % (a, s))

with open(r"D:\K\zcode\game\_extracted\_bgm_re7.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines[:50]))
