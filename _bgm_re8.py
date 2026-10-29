# -*- coding: utf-8 -*-
# 反汇编两个工厂调用点（0x102559DA / 0x10255C55），找 +0x70 安装与解密器构造
import capstone

DLL = r"D:\HY\夕凪荘的S级的女朋友们\resident.dll"
OUTP = r"D:\K\zcode\game\_extracted\_bgm_re8.txt"
out = open(OUTP, "w", encoding="utf-8")
def w(s=""):
    out.write(s + "\n")

d = open(DLL, "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B
def va2off(va):
    return va - IMAGE_BASE - TEXT_VA + TEXT_OFF

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

def dis_range(va_start, va_end):
    off = va2off(va_start)
    code = d[off:off + (va_end - va_start) + 32]
    for ins in md.disasm(code, va_start):
        w("  0x%08X  %-20s %s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
        if ins.address >= va_end:
            break

for site, back, fwd in ((0x102559DA, 0x80, 0x80), (0x10255C55, 0x80, 0x80)):
    w("=" * 72)
    w("factory call site 0x%08X" % site)
    w("=" * 72)
    dis_range(site - back, site + fwd)
    w("")

out.close()
print("re8 done")
