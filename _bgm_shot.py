# -*- coding: utf-8 -*-
# 启动游戏 → 等待 → 截屏游戏窗口，保存 BMP 供查看
import ctypes, ctypes.wintypes as wt, os, struct, subprocess, sys, time

GAME_DIR = r"D:\HY\夕凪荘的S级的女朋友们"
EXE = os.path.join(GAME_DIR, "Yunagiso.exe")
OUTD = r"D:\K\zcode\game\_extracted\_bgm_mem"
os.makedirs(OUTD, exist_ok=True)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002

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

class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

def shoot(hwnd, w_, h_, path):
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w_, h_)
    gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    line = ((w_ * 3 + 3) // 4) * 4
    buf = (ctypes.c_char * (line * h_))()
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH)
    bmi.biWidth = w_
    bmi.biHeight = -h_
    bmi.biPlanes = 1
    bmi.biBitCount = 24
    bmi.biSizeImage = line * h_
    gdi32.GetDIBits(mem, bmp, 0, h_, buf, ctypes.byref(bmi), 0)
    fh = b"BM" + (54 + len(buf)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
    ih = (40).to_bytes(4, "little") + w_.to_bytes(4, "little", signed=True) + h_.to_bytes(4, "little", signed=True)
    ih += (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + (0).to_bytes(4, "little")
    ih += (line * h_).to_bytes(4, "little") + (0).to_bytes(16, "little")
    with open(path, "wb") as f:
        f.write(fh + ih + buf.raw)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return ok

def main():
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    proc = subprocess.Popen([EXE], cwd=GAME_DIR)
    time.sleep(wait)
    wins = enum_windows(proc.pid)
    for hwnd, title, l, t, w_, h_ in wins:
        print("win 0x%X %r %dx%d" % (hwnd, title, w_, h_))
    for idx, (hwnd, title, l, t, w_, h_) in enumerate(wins):
        if w_ > 200 and h_ > 200:
            p = os.path.join(OUTD, "screen_%d.bmp" % idx)
            ok = shoot(hwnd, w_, h_, p)
            print("shot %s ok=%d" % (p, ok))
    time.sleep(1)
    try:
        proc.kill()
    except Exception:
        pass

if __name__ == "__main__":
    main()
