"""按窗口标题截图（跨进程）：验证**冻结后的 exe** 渲染的是新界面。"""
import ctypes, sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shot_app import capture  # 复用同一套 PrintWindow 逻辑

u = ctypes.windll.user32
title = sys.argv[1]
out = Path(sys.argv[2])
found = []
def cb(h, lp):
    b = ctypes.create_unicode_buffer(256); u.GetWindowTextW(h, b, 256)
    if b.value == title: found.append(h)
    return True
u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
if not found:
    print("NO_WINDOW"); raise SystemExit(2)
print("captured", capture(found[0], out), "->", out)
