# -*- coding: utf-8 -*-
# 跑游戏 + 内存 dump：提取 22 个加密 BGM 的解密头部，XOR 出密钥流
# 用法: python _bgm_dump.py [wait_seconds]
import ctypes, ctypes.wintypes as wt, os, struct, json, subprocess, sys, time

GAME_DIR = r"D:\HY\夕凪荘的S级的女朋友们"
EXE = os.path.join(GAME_DIR, "Yunagiso.exe")
BGM_DIR = os.path.join(GAME_DIR, "res", "s", "m")
OUTD = r"D:\K\zcode\game\_extracted\_bgm_mem"
SERIALS = r"D:\K\zcode\game\_extracted\_bgm_serials.json"
os.makedirs(OUTD, exist_ok=True)

k32 = ctypes.windll.kernel32
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x20, 0x40, 0x08}  # READONLY, READWRITE, EXECUTE_READ, EXECUTE_READWRITE, WRITECOPY

class MBI64(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64),
                ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD),
                ("_pad1", wt.DWORD),
                ("RegionSize", ctypes.c_uint64),
                ("State", wt.DWORD),
                ("Protect", wt.DWORD),
                ("Type", wt.DWORD),
                ("_pad2", wt.DWORD)]

def load_serials():
    with open(SERIALS) as f:
        raw = json.load(f)
    m = {}
    for fn, v in raw.items():
        m[v["serial"]] = {"fn": fn, "hlen": v["header_len"], "anchor": bytes.fromhex(v["anchor_hex"]),
                          "path": os.path.join(BGM_DIR, fn)}
    return m

def scan_process(h, serial_map, report):
    addr = 0
    found = {}
    oggs_hits = 0
    while addr < 0x80000000:
        mbi = MBI64()
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            addr += 0x1000
            continue
        size = mbi.RegionSize
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and size > 0:
            try:
                buf = (ctypes.c_char * size)()
                got = ctypes.c_size_t(0)
                if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)) and got.value > 0:
                    data = buf.raw[:got.value]
                    pos = 0
                    needle = b"OggS\x00\x02"
                    while True:
                        i = data.find(needle, pos)
                        if i < 0:
                            break
                        oggs_hits += 1
                        pos = i + 1
                        if i + 22 > len(data):
                            continue
                        serial = struct.unpack_from("<I", data, i + 14)[0]
                        if serial in serial_map and serial not in found:
                            ent = serial_map[serial]
                            hl = ent["hlen"]
                            if i + hl + 48 <= len(data):
                                plain = data[i:i + hl]
                                anchor_ok = data[i + hl:i + hl + 48] == ent["anchor"]
                                found[serial] = {"fn": ent["fn"], "addr": addr + i, "anchor_ok": anchor_ok,
                                                 "plain": plain}
                        else:
                            report.append("hit serial=0x%08X @0x%X (unknown)" % (serial, addr + i))
            except Exception as e:
                report.append("region @0x%X read fail: %r" % (addr, e))
        addr += size if size else 0x1000
    return found, oggs_hits

def main():
    wait_total = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    serial_map = load_serials()
    report = []
    proc = subprocess.Popen([EXE], cwd=GAME_DIR)
    report.append("launched pid=%d" % proc.pid)
    found = {}
    t0 = time.time()
    polls = 0
    try:
        while time.time() - t0 < wait_total:
            time.sleep(4)
            polls += 1
            if proc.poll() is not None:
                report.append("PROCESS EXITED code=%s" % proc.returncode)
                break
            h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, proc.pid)
            if not h:
                report.append("OpenProcess failed err=%d" % k32.GetLastError())
                continue
            try:
                found, oggs_hits = scan_process(h, serial_map, report)
                report.append("poll#%d: oggs_hits=%d matched=%d %s" % (
                    polls, oggs_hits, len(found),
                    ",".join(sorted(v["fn"] for v in found.values()))))
                if any(v["anchor_ok"] for v in found.values()):
                    break
            finally:
                k32.CloseHandle(h)
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
                report.append("game killed")
        except Exception:
            pass

    summary = {"report": report, "found": {}}
    for serial, v in found.items():
        ent = serial_map[serial]
        with open(ent["path"], "rb") as f:
            cipher = f.read(v["hlen"])
        plain = v["plain"]
        ks = bytes(a ^ b for a, b in zip(cipher, plain))
        base = os.path.join(OUTD, os.path.splitext(v["fn"])[0])
        with open(base + ".plain", "wb") as f:
            f.write(plain)
        with open(base + ".keystream", "wb") as f:
            f.write(ks)
        summary["found"][v["fn"]] = {"serial": serial, "addr": "0x%X" % v["addr"], "anchor_ok": v["anchor_ok"],
                                     "hlen": v["hlen"]}
    with open(os.path.join(OUTD, "_dump_report.json"), "w") as f:
        json.dump(summary, f, indent=1)
    for line in report:
        print(line)
    print("matched files:", sorted(summary["found"].keys()))

if __name__ == "__main__":
    main()
