# -*- coding: utf-8 -*-
# 跑游戏 + 自动点击跨过开机提示 + 扫内存。用法: python _bgm_dump2.py [总等待秒]
import ctypes, ctypes.wintypes as wt, os, struct, json, subprocess, sys, time

GAME_DIR = r"D:\HY\夕凪荘的S级的女朋友们"
EXE = os.path.join(GAME_DIR, "Yunagiso.exe")
BGM_DIR = os.path.join(GAME_DIR, "res", "s", "m")
OUTD = r"D:\K\zcode\game\_extracted\_bgm_mem"
SERIALS = r"D:\K\zcode\game\_extracted\_bgm_serials.json"
os.makedirs(OUTD, exist_ok=True)

user32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x20, 0x40, 0x08}
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

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

def enum_windows(pid):
    res = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            res.append((hwnd, buf.value, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return True
    user32.EnumWindows(cb, 0)
    return res

def click_center(hwnd, w_, h_):
    x, y = w_ // 2, h_ // 2
    lparam = (y << 16) | x
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)

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
                                anchor_ok = data[i + hl:i + hl + 48] == ent["anchor"]
                                found[serial] = {"fn": ent["fn"], "addr": addr + i, "anchor_ok": anchor_ok,
                                                 "plain": data[i:i + hl]}
            except Exception as e:
                report.append("region @0x%X fail %r" % (addr, e))
        addr += size if size else 0x1000
    return found, oggs_hits

def main():
    wait_total = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    serial_map = load_serials()
    report = []
    proc = subprocess.Popen([EXE], cwd=GAME_DIR)
    report.append("pid=%d" % proc.pid)
    found = {}
    clicked = False
    t0 = time.time()
    polls = 0
    try:
        while time.time() - t0 < wait_total:
            time.sleep(4)
            polls += 1
            if proc.poll() is not None:
                report.append("EXITED code=%s" % proc.returncode)
                break
            if not clicked and polls >= 2:
                for hwnd, title, l, t, w_, h_ in enum_windows(proc.pid):
                    report.append("win hwnd=0x%X title=%r rect=%dx%d" % (hwnd, title, w_, h_))
                    if w_ > 200 and h_ > 200:
                        click_center(hwnd, w_, h_)
                        report.append("clicked center of 0x%X" % hwnd)
                        clicked = True
            h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, proc.pid)
            if not h:
                continue
            try:
                found, oggs_hits = scan_process(h, serial_map, report)
                report.append("poll#%d oggs=%d matched=%d %s" % (
                    polls, oggs_hits, len(found), ",".join(sorted(v["fn"] for v in found.values()))))
                if any(v["anchor_ok"] for v in found.values()):
                    report.append("GOT anchored hit, stop polling")
                    break
            finally:
                k32.CloseHandle(h)
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
                report.append("killed")
        except Exception:
            pass
    summary = {"report": report, "found": {}}
    for serial, v in found.items():
        ent = serial_map[serial]
        with open(ent["path"], "rb") as f:
            cipher = f.read(v["hlen"])
        ks = bytes(a ^ b for a, b in zip(cipher, v["plain"]))
        base = os.path.join(OUTD, os.path.splitext(v["fn"])[0])
        with open(base + ".plain", "wb") as f:
            f.write(v["plain"])
        with open(base + ".keystream", "wb") as f:
            f.write(ks)
        summary["found"][v["fn"]] = {"serial": serial, "addr": "0x%X" % v["addr"],
                                     "anchor_ok": v["anchor_ok"], "hlen": v["hlen"]}
    with open(os.path.join(OUTD, "_dump_report.json"), "w") as f:
        json.dump(summary, f, indent=1)
    for line in report:
        print(line)
    print("matched:", sorted(summary["found"].keys()))

if __name__ == "__main__":
    main()
