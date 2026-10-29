# -*- coding: utf-8 -*-
# 扫描 .text：找写入 [reg+0x70] 的指令与对象构造点，追解密器 vtable
import struct
import capstone

DLL = r"D:\HY\夕凪荘的S级的女朋友们\resident.dll"
OUTP = r"D:\K\zcode\game\_extracted\_bgm_re2.txt"
out = open(OUTP, "w", encoding="utf-8")
def w(s=""):
    out.write(s + "\n")

d = open(DLL, "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B
code = d[TEXT_OFF:TEXT_OFF + TEXT_SZ]

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True

hits70 = []      # stores to [reg+0x70]
vtable_inits = []  # mov dword [ecx], imm  (constructor vtable init)
for ins in md.disasm(code, IMAGE_BASE + TEXT_VA):
    m = ins.mnemonic
    if m == "mov" and ins.op_str.count(",") == 1:
        dst, src = [x.strip() for x in ins.op_str.split(",")]
        if dst.startswith("dword ptr [") and ("+ 0x70]" in dst or dst.endswith("+0x70]")):
            hits70.append((ins.address, ins.op_str))
        if src.startswith("0x10") and dst in ("dword ptr [ecx]", "dword ptr [edi]", "dword ptr [esi]", "dword ptr [edx]"):
            vtable_inits.append((ins.address, ins.op_str))

w("stores to [reg+0x70]: %d" % len(hits70))
for a, s in hits70:
    w("  0x%08X  mov %s" % (a, s))
w("")
w("vtable inits (mov dword [reg], 0x10xxxxxx): %d" % len(vtable_inits))
for a, s in vtable_inits:
    w("  0x%08X  mov %s" % (a, s))

out.close()
print("scan done: %d +0x70 stores, %d vtable inits" % (len(hits70), len(vtable_inits)))
