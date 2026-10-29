# -*- coding: utf-8 -*-
# 反汇编 3 个 +0x70 写入点的上下文，追解密器对象来源
import struct
import capstone

DLL = r"D:\HY\夕凪荘的S级的女朋友们\resident.dll"
OUTP = r"D:\K\zcode\game\_extracted\_bgm_re3.txt"
out = open(OUTP, "w", encoding="utf-8")
def w(s=""):
    out.write(s + "\n")

d = open(DLL, "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B

def va2off(va):
    return va - IMAGE_BASE - TEXT_VA + TEXT_OFF

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

def dis(va, n, back):
    off = va2off(va - back)
    code = d[off:off + n*10 + back]
    cnt = 0
    for ins in md.disasm(code, va - back):
        w("  0x%08X  %-20s %s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
        cnt += 1
        if cnt >= n:
            break

for site in (0x100017E5, 0x100045FE, 0x10009093):
    w("=" * 72)
    w("site 0x%08X" % site)
    w("=" * 72)
    dis(site, 30, back=0x50)
    w("")

out.close()
print("re3 done")
