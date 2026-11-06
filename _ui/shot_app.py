#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 GUI 窗口渲染成 PNG（不依赖前台/屏幕捕获）。

为什么不用 ImageGrab：代理会话与交互桌面可能不在同一个桌面上，`CopyFromScreen`
拿到的是空白或直接找不到窗口。`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)`
是**窗口自己绘制自己**，窗口被遮挡也能出图。

用法：python _ui/shot_app.py <输出.png> [宽] [高]
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk  # noqa: E402

import gui  # noqa: E402

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def capture(hwnd: int, out: Path) -> tuple[int, int]:
    from PIL import Image

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top

    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h                     # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)

    out.parent.mkdir(parents=True, exist_ok=True)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(out)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return w, h


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "_ui/shot.png")
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 620

    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:                                              # noqa: BLE001
        root = tk.Tk()
    root.geometry(f"{w}x{h}")
    app = gui.App(root)
    # 塞一点示例内容，截图才看得出层级（真实运行时是空的）
    app.var_game.set(r"D:\HY\教师催眠2")
    app.var_out.set(r"D:\HY\教师催眠2\output")
    app._log("输出目录：D:\\HY\\教师催眠2\\output")
    app._log("[OK  ] detect        1.44s  KiriKiri (score=90)")
    app._log("[OK  ] postprocess   1.43s  2748 个 .tlg → png/ 共 2748 个成品")
    app._log("[OK  ] verify       97.48s  图片 3082/3082、音频 6558/6558、视频 12/12")
    root.update_idletasks()
    root.update()
    root.after(300, lambda: None)
    root.update()

    hwnd = root.winfo_id()
    hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
    print("captured", capture(hwnd, out), "->", out)
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
