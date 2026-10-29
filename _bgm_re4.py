# -*- coding: utf-8 -*-
# 从函数起点反汇编 0x1029E43B 所在函数：找 esi 来源与 +0x70 初始化
import struct
import capstone

DLL = r"D:\HY\夕凪荘的S级的女朋友们\resident.dll"
OUTP = r"D:\K\zcode\game\_extracted\_bgm_re4.txt"
out = open(OUTP, "w", encoding="utf-8")
def w(s=""):
    out.write(s + "\n")

d = open(DLL, "rb").read()
IMAGE_BASE = 0x10000000
TEXT_VA, TEXT_OFF, TEXT_SZ = 0x1000, 0x400, 0x2D679B

def va2off(va):
    return va - IMAGE_BASE - TEXT_VA + TEXT_OFF

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

TARGET = 0x1029E43B
# 往回找 int3 填充（>=2 个 cc）
off_t = va2off(TARGET)
start = off_t
i = off_t
while i > off_t - 0x2000:
    if d[i-1] == 0xCC and d[i-2] == 0xCC:
        start = i
        break
    i -= 1
start_va = IMAGE_BASE + TEXT_VA + (start - TEXT_OFF)
w("function start guess: 0x%08X (int3 run ends)" % start_va)
w("")

code = d[start:off_t + 0x400]
cnt = 0
for ins in md.disasm(code, start_va):
    mark = ""
    if ins.address == TARGET:
        mark = "   <<<< cmp OggS"
    w("  0x%08X  %-22s %s %s%s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str, mark))
    cnt += 1
    if cnt >= 300:
        break

out.close()
print("re4 done, start=0x%08X" % start_va)
