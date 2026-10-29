# -*- coding: utf-8 -*-
# resident.dll 静态分析: 定位 BGM 解密器（loader cmp "OggS" @0x1029E43E → 0x1029ECA0 → [esi+0x70] 虚调用）
import struct, sys
import capstone

DLL = r"D:\HY\夕凪荘的S级的女朋友们\resident.dll"
OUTP = r"D:\K\zcode\game\_extracted\_bgm_re_asm.txt"
out = open(OUTP, "w", encoding="utf-8")
def w(s=""):
    out.write(s + "\n")

d = open(DLL, "rb").read()
w("dll size = %d" % len(d))

# ---- PE parse ----
peoff = struct.unpack_from("<I", d, 0x3C)[0]
assert d[peoff:peoff+4] == b"PE\0\0"
machine = struct.unpack_from("<H", d, peoff+4)[0]
nsec = struct.unpack_from("<H", d, peoff+6)[0]
optoff = peoff + 24
magic = struct.unpack_from("<H", d, optoff)[0]
image_base = struct.unpack_from("<I", d, optoff + 28)[0]
w("machine=0x%X secs=%d magic=0x%X image_base=0x%08X" % (machine, nsec, magic, image_base))

secs = []
so = optoff + struct.unpack_from("<H", d, peoff+20)[0]  # SizeOfOptionalHeader
for i in range(nsec):
    name = d[so+i*40:so+i*40+8].rstrip(b"\0").decode("latin1")
    vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", d, so+i*40+8)
    secs.append((name, vaddr, vsize, raddr, rsize))
    w("  sec %-8s va=0x%06X vs=0x%06X raw=0x%06X rs=0x%06X" % (name, vaddr, vsize, raddr, rsize))

def va2off(va):
    rva = va - image_base
    for name, vaddr, vsize, raddr, rsize in secs:
        if vaddr <= rva < vaddr + max(vsize, rsize):
            off = rva - vaddr + raddr
            if off < len(d):
                return off
    return None

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = False

def dis(va, n=60, back=0):
    off = va2off(va - back)
    if off is None:
        w("(va 0x%08X not mapped)" % va)
        return
    code = d[off:off + (n*8 + back)]
    addr = va - back
    cnt = 0
    for ins in md.disasm(code, addr):
        w("  0x%08X  %-22s %s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
        cnt += 1
        if cnt >= n:
            break

# ---- 1) around 0x1029E43E (cmp "OggS") ----
w("")
w("=" * 72)
w("A) context @0x1029E43E (back 0x60, forward 60 ins)")
w("=" * 72)
dis(0x1029E43E, 60, back=0x60)

# ---- 2) around 0x1029ECA0 (the vtable call) ----
w("")
w("=" * 72)
w("B) context @0x1029ECA0 (back 0x40, forward 40 ins)")
w("=" * 72)
dis(0x1029ECA0, 40, back=0x40)

out.close()
print("asm stage1 done")
