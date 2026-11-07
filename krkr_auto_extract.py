# -*- coding: utf-8 -*-
"""
Krkr(KiriKiri) 加密 xp3 动态提取 — 一键自动化工具（可复用）

用法:
  python krkr_auto_extract.py <游戏目录> [--out <输出目录>] [--keep-stage]

流程（每步都实测验证过，见 verified-findings.md §17）:
  1. 在 ASCII 路径下搭 stage（hardlink data*.xp3 + 复制主程序为 game.exe + 复制 KrkrExtract 三件套）
     - CJK 路径会触发引擎 ANSI→Unicode 转换失败弹窗，游戏启动即挂（必须 ASCII）
  2. KrkrExtract.Lite.exe CLI 注入（恰 1 参数 = 游戏 exe 路径）
  3. 等 "KrkrExtract(local ..." UI 窗口出现（DPI 感知，物理坐标）
  4. 对每个 xp3：explorer /select 选中 → UIA 拿 item 物理矩形 → SendInput 真实拖拽
     到 KrkrExtract UI 空白处（Explorer 发起的拖拽才会走 legacy WM_DROPFILES 通道，
     合成消息/OLE 拖拽都不行——实测）
  5. 等任务完成（产物数稳定 + UI 标题回到 idle），再拖下一个 xp3
  6. 输出: <stage>/KrkrExtract_Output（结束后打印位置；--out 时移动过去）

依赖: Python 标准库 + PowerShell(UIA) + explorer；KrkrExtract 三件套在 D:\\K\\galgame\\krkr\\krkr
"""
import os, sys, time, json, ctypes, shutil, subprocess, argparse
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import _xp3_carve
import toolbridge as tb

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()  # 本机 200% 缩放：此后全部坐标为物理像素

# --- 前台 / 置顶（2026-11-06 加固：窗口被别的程序压住时找不到拖拽落点）---
SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
# SetWindowPos 的第二个参数是 HWND。不声明 argtypes 时 ctypes 按 c_int 传参，
# 64 位下 (HWND)-1 会被截成 0xFFFFFFFF，TOPMOST 静默失效 —— 这条必须显式声明。
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

KRKR_TOOL = r"D:\K\galgame\krkr\krkr"


def krkr_tool_dir() -> str:
    """KrkrExtract 三件套所在目录：随包 bin/krkr（冻结包 build_exe.py 打进去的）优先，
    缺了回退开发机的固定位置。三件套必须同目录（Lite.exe 加载旁边的 Core.dll）。"""
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(base, "bin", "krkr")
    if os.path.isfile(os.path.join(bundled, "KrkrExtract.Lite.exe")):
        return bundled
    return KRKR_TOOL

#: ASCII stage 根目录。**必须纯 ASCII**（verified-findings §17.2）：CJK 路径注入后游戏进程活着
#: 但窗口不弹，只弹「ANSI 文字列を UNICODE 文字列に変換できません」。
#: 放在项目目录下（2026-10-29 起主目录是 D:\K\deepseek），名字固定为 `_krkr_stage`，已被 .gitignore 排除。
STAGE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_krkr_stage")

#: 等 KrkrExtract 建窗的上限（秒）。2026-11-06 实测：`教师催眠2` 注入后窗口不是 5 秒内出现，
#: 单次判定把「还没建好」当成「注入失败」；环境变量可覆盖（慢机器/大包调大）。
WINDOW_WAIT = float(os.environ.get("KRKR_WINDOW_WAIT", "40"))

#: 找空白落点的重试轮数（每轮重新把 KrkrExtract 抬到最前）。2026-11-06 教师催眠2
#: 第四轮卡在 `assert drop, "no blank spot"`，日志 blockers={'Chrome_RenderWidgetHostHWND':…}。
DROP_ATTEMPTS = int(os.environ.get("KRKR_DROP_ATTEMPTS", "6"))
#: 落点扫描网格步长（物理像素）；只取主窗口空白背景，不取子控件。
DROP_GRID = 40
#: GA_ROOT：GetAncestor 取顶层祖先，用来判断「这个 hwnd 是不是主窗口的子控件」。
GA_ROOT = 2
#: 没点上 Full Unpack 时默认**明确失败**（不然拖完只有脚本、没有图/音频，是半份产物）。
#: 只有在用户确认界面确实没有该按钮、并已手工开启全解包模式时才允许跳过。
ALLOW_NO_FULL_UNPACK = os.environ.get("KRKR_ALLOW_NO_FULL_UNPACK", "0") == "1"

#: KrkrExtract 注入后主界面的标题前缀（跨版本一致，实测 `KrkrExtract(local 5.0.0.2) - built on …`）。
MAIN_TITLE_PREFIX = "KrkrExtract(local"
#: 模态提示框标题里会出现这些词；它们不是主界面，`dismiss_dialogs` 负责关掉。
MODAL_TITLE_HINTS = ("information", "error", "エラー", "警告", "warning")
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
BST_CHECKED = 1


def _print_log(msg: str) -> None:
    """把日志原样打到 stdout，**中文必须保留**。

    2026-11-06 实跑 `教师催眠2`：旧实现 ``print(msg.encode("ascii","replace")...)``
    把每一句中文都打成了 ``?``。orchestrator 用 ``_run_sibling`` 把这段 stdout
    收进 ``_work/extract.log``，于是日志里只剩一堆问号 —— 真实报错（落点被遮挡、
    Full Unpack 没点上）根本读不出来，排障只能靠猜。

    ``redirect_stdout(StringIO)`` 下不会触发编码问题；直接跑脚本时若控制台编码
    不能表示某个字，退到 ``utf-8 + backslashreplace`` 的 ASCII 安全串，
    **绝不让一次 print 把整条解包链打断**。
    """
    text = str(msg)
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, AttributeError, OSError):
        try:
            safe = text.encode("utf-8", "backslashreplace").decode("ascii", "replace")
            print(safe, flush=True)
        except Exception:                                   # noqa: BLE001
            pass


LOG = os.path.join(STAGE_ROOT, "krkr_auto_extract.log")
def log(msg):
    os.makedirs(STAGE_ROOT, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + str(msg) + "\n")
    _print_log(msg)

def _same_exe_path(a: str, b: str) -> bool:
    """两个镜像路径是否指向同一个可执行文件（Windows 语义：大小写不敏感、斜杠统一）。

    纯函数、单独抽出来是为了能测：这条判据是「杀进程」的唯一依据，判错了就是误杀别人的
    程序；判漏了就是杀掉自己刚起的游戏。两种错都很贵，所以它必须有测试。
    """
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _enum_pids() -> list[int]:
    """EnumProcesses：拿全机器的 pid 列表（psapi；缓冲不够就翻倍重试）。"""
    psapi = ctypes.windll.psapi
    cap = 4096
    for _ in range(3):
        arr = (wintypes.DWORD * cap)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr),
                                   ctypes.byref(needed)):
            raise OSError("EnumProcesses 失败")
        n = needed.value // ctypes.sizeof(wintypes.DWORD)
        if n < cap:                                  # 没填满 = 拿全了
            return [arr[i] for i in range(n)]
        cap *= 2
    return [arr[i] for i in range(cap)]


def _process_image_path(pid: int) -> str | None:
    """QueryFullProcessImageNameW：取进程完整镜像路径；打不开/查不到返回 None。

    用 PROCESS_QUERY_LIMITED_INFORMATION 而不是 QUERY_INFORMATION：前者在
    Vista+ 对多数同用户进程可用，权限要求最低；系统进程读不到就返回 None，
    由调用方跳过（**绝不**退回按名字匹配——那正是要修的毛病）。
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value or None
    finally:
        kernel32.CloseHandle(handle)


def pids_by_exe_path(target) -> list[int]:
    """按**完整镜像路径**找进程（`pids_by_name` 的安全替代）。

    为什么必须换（批次 C5，2026-11-03）：旧实现 `pids_by_name("game.exe")` + 
    `taskkill /F /PID` 会杀掉**全机器上任何**叫 game.exe 的进程——别的 galgame、模拟器、
    甚至用户自己的调试目标都会被牵连。同名的 exe 每天都有几十个，名字根本不是身份。
    这里只认「镜像绝对路径与 stage 里的那份一致」，查不到路径的 pid 跳过并汇总记一笔，
    绝不按名字兜底。
    """
    want = str(target)
    out: list[int] = []
    unreadable = 0
    try:
        my_pid = kernel32.GetCurrentProcessId()
        for pid in _enum_pids():
            if pid == my_pid:
                continue
            path = _process_image_path(pid)
            if path is None:
                unreadable += 1                       # 系统进程/权限不足：跳过，不猜
                continue
            if _same_exe_path(path, want):
                out.append(pid)
    except OSError as exc:
        log("ERROR: 枚举进程失败: %s" % exc)
        return out
    if unreadable:
        log("pids_by_exe_path: %d 个进程读不到镜像路径，已跳过（不按名字兜底）" % unreadable)
    return out


def wnd_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value

def count_files(root):
    total, size_total, by_ext = 0, 0, {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                sz = -1
            total += 1
            size_total += max(sz, 0)
            by_ext[os.path.splitext(fn)[1].lower()] = by_ext.get(os.path.splitext(fn)[1].lower(), 0) + 1
    return total, by_ext, size_total

def find_ui_window(pid):
    res = [None]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and wnd_text(h).startswith(MAIN_TITLE_PREFIX):
            res[0] = h
        return True
    user32.EnumWindows(cb, 0)
    return res[0]


def window_titles(pid):
    """该进程的所有可见顶层窗口标题 —— 注入失败时打诊断用。

    能区分两种失败：**根本没建窗**（注入没成功）与**建了但标题不匹配**（注入成功、判定过严）。
    没有这条，日志里只剩一句「窗口没找到」，排起来全靠猜。
    """
    res = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            t = wnd_text(h)
            if t:
                res.append(t)
        return True
    user32.EnumWindows(cb, 0)
    return res


def wait_ui_window(pid, timeout=None):
    """轮询等 KrkrExtract 窗口出现，返回 (hwnd 或 None, 实际等待秒数)。

    为什么要轮询（2026-11-06 实测 `教师催眠2`）：注入后窗口**不是 5 秒内就有**，
    旧代码只判一次，把「还没建好」当成「注入失败」→ 掉进静态 index 兜底 →
    该游戏有压缩条目、兜底必然抛错 → 整条链路 23 秒退出，还报「GUI 跑过了但没产出」
    （其实 GUI 一步都没走）。上限可用 `KRKR_WINDOW_WAIT` 覆盖，别写死。
    """
    limit = WINDOW_WAIT if timeout is None else timeout
    if limit <= 0:
        # 测试/极端场景：不等待，直接判一次（避免把 40s 的等待带进单测）
        return find_ui_window(pid), 0.0
    start = time.time()
    while True:
        h = find_ui_window(pid)
        waited = time.time() - start
        if h or waited >= limit:
            return h, waited
        time.sleep(1.0)


def all_cabinets(hint=None):
    """枚举资源管理器窗口；给了 hint 就只收标题含它的那些。

    为什么要 hint（2026-11-04）：原来无差别枚举 `CabinetWClass`，`close_all_explorers`
    会把用户自己开着的资源管理器一并关掉——用户可能正在拷文件，这是实打实的数据损失。
    自动化只该收拾**它自己开出来**的窗口。
    """
    res = []
    needle = hint.lower() if hint else None
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        c = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, c, 64)
        if c.value == "CabinetWClass":
            if needle is None or needle in wnd_text(h).lower():
                res.append(h)
        return True
    user32.EnumWindows(cb, 0)
    return res

def close_all_explorers(hint):
    """关掉本次 stage 开出来的资源管理器窗口（hint = stage 目录名）。

    **必须**给 hint（签名故意不设默认值）：无差别关闭会把用户自己的窗口一起关掉。
    """
    for _ in range(6):
        wins = all_cabinets(hint)
        if not wins:
            return
        for h in wins:
            user32.ShowWindow(h, 6)   # minimize: pulls back from other virtual desktops
            time.sleep(0.15)
            user32.ShowWindow(h, 9)   # restore
            time.sleep(0.15)
            user32.PostMessageW(h, 0x0010, 0, 0)
        time.sleep(1.0)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]
class INP(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]
def mouse(flags):
    i = INP(); i.type = 0; i.u.mi.dwFlags = flags
    user32.SendInput(1, (INP * 1)(i), ctypes.sizeof(INP))

def _uia_ps(hwnd, item_name, *, invoke=False, fuzzy=False, retries=1):
    """调一次 UIA 脚本，返回 ``(stdout 行, 换算成物理坐标的矩形或 None)``。

    `_uia_item_rect.ps1` 同时服务两件事：拖拽时拿 Explorer 条目的矩形（原行为），
    和 2026-11-07 新增的「找 Full Unpack 按钮并触发」。`-Invoke` / `-Fuzzy`
    是可选开关，不传时脚本输出与旧版逐字一致，拖拽链路不受影响。
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_uia_item_rect.ps1")
    argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", script, "-ItemName", item_name, "-Hwnd", str(hwnd)]
    if invoke:
        argv.append("-Invoke")
    if fuzzy:
        argv.append("-Fuzzy")
    for _ in range(max(1, retries)):
        try:
            ps = subprocess.run(argv, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        lines = ps.stdout.decode("utf-8", errors="replace").strip().splitlines()
        scr = None
        for ln in lines:
            if ln.startswith("SCR "):
                try:
                    _, sw, sh = ln.split()
                    scr = (int(sw), int(sh))
                except ValueError:
                    pass
                break
        rect = None
        for ln in lines:
            if ln.startswith("RECT "):
                try:
                    _, l, t, r, b = ln.split()
                    l, t, r, b = int(l), int(t), int(r), int(b)
                    scale = user32.GetSystemMetrics(0) // max(scr[0], 1) if scr else 1
                    if scale != 1:
                        l, t, r, b = l * scale, t * scale, r * scale, b * scale
                    rect = (l, t, r, b)
                except (ValueError, IndexError):
                    pass
                break
        return lines, rect
    return [], None


def uia_item_rect(exp_hwnd, item_name):
    """UIA item rect; returns physical (l,t,r,b) or None. Retries; follows hwnd recreation."""
    for _attempt in range(15):
        _lines, rect = _uia_ps(exp_hwnd, item_name)
        if rect:
            return rect
        time.sleep(1.2)
    return None


def uia_click_button(hwnd, label):
    """UIA 兜底：按名字找按钮 → Invoke / Toggle / 鼠标点击（中心点）。

    2026-11-07 真机：`KrkrExtract.Lite.exe` 是 .NET WinForms，主窗口类名不是
    `#32770`、按钮也不是标准 `Button` 类，纯 Win32 子控件枚举会一无所获。
    UIA 能穿透 WinForms 的控件树，所以作为第二道保险；三条触发路径任一成功
    都算点上，并把控件类型/名字/触发方式写进状态供日志复核。
    """
    lines, rect = _uia_ps(hwnd, label, invoke=True, fuzzy=True, retries=2)
    tag = next((ln for ln in lines if ln.startswith(
        ("INVOKED", "TOGGLED", "NO_PATTERN", "NOITEM", "NOWINDOW"))), "")
    item = next((ln[5:] for ln in lines if ln.startswith("ITEM ")), "")
    ctrls = [ln[5:] for ln in lines if ln.startswith("CTRL ")][:12]
    if tag == "INVOKED":
        return True, f"InvokePattern 已触发（{item}）"
    if tag == "TOGGLED":
        state = next((ln for ln in lines if ln.startswith("TOGGLESTATE ")), "状态未知")
        return True, f"TogglePattern 已切换（{item}；{state}）"
    if tag == "NO_PATTERN" and rect:
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        try:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.2)
            mouse(0x0002)                       # left down
            time.sleep(0.1)
            mouse(0x0004)                       # left up
        except Exception as exc:                 # noqa: BLE001
            return False, f"UIA 找到控件但鼠标点击失败：{type(exc).__name__}: {exc}"
        return True, (f"无 Invoke/Toggle，已按 BoundingRectangle 中心鼠标点击"
                      f"（{item}；({x},{y})，勾选状态无法复核）")
    hint = ("；可见控件：" + " / ".join(ctrls)) if ctrls else ""
    return False, f"UIA 未找到 {label!r}（{tag or '脚本无有效输出'}；{item}）{hint}"

def find_explorer_by_title_hint(hint):
    """标题含 hint 的资源管理器窗口；多个时取最后一个（与历史行为一致）。"""
    if not hint:
        return None
    wins = all_cabinets(hint)
    return wins[-1] if wins else None

def drag(x0, y0, x1, y1):
    user32.SetCursorPos(x0, y0)
    time.sleep(0.6)
    mouse(0x0002)               # left down
    time.sleep(0.5)
    user32.SetCursorPos(x0 + 5, y0 + 3)
    time.sleep(0.2)
    user32.SetCursorPos(x0 + 18, y0 + 10)
    time.sleep(0.3)
    steps = 30
    for i in range(1, steps + 1):
        x = x0 + 18 + (x1 - x0 - 18) * i // steps
        y = y0 + 10 + (y1 - y0 - 10) * i // steps
        user32.SetCursorPos(x, y)
        time.sleep(0.04)
    time.sleep(0.5)
    mouse(0x0004)               # left up
    time.sleep(1.0)

_OK_LABELS = ("确定", "OK", "はい", "Yes", "是", "关闭", "Close")


def pid_of_window(hwnd):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def top_windows(pid):
    """该进程的顶层窗口 [(hwnd, 类名, 标题)]。"""
    res = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        if pid_of_window(h) == pid:
            c = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, c, 64)
            t = wnd_text(h)
            if t:
                res.append((h, c.value, t))
        return True
    user32.EnumWindows(cb, 0)
    return res


def dismiss_dialogs(pid):
    """点掉注入进程弹的模态提示框，**绝不碰主界面**。返回被关掉的标题列表。

    2026-11-06 实测 `教师催眠2`（krkrZ + Mai@KF.dll）：注入后游戏自己弹
    `Information / 正常に起動できませんでした`。它不是解包失败——关掉它，
    data.xp3 立刻 +57 个文件（46 .tjs + 11 .ks）—— 但它会
    ① 盖住拖拽落点、② 让完成判定一直看到「还有对话框」，整轮卡在 0 files 到超时。

    主界面标题形如 `KrkrExtract(local 5.0.0.2) - built on …`，实为 .NET WinForms
    窗口（类名 `WindowsForms10.Window.8.app...`，2026-11-07 实证）；这里只处理
    标准 `#32770` 消息框，再按标题前缀兜底排除主界面，绝不把工具自己的窗口关掉。
    """
    closed = []
    for h, cls, title in top_windows(pid):
        if cls != "#32770" or title.startswith(MAIN_TITLE_PREFIX):
            continue
        if not any(k.lower() in title.lower() for k in
                   ("information", "error", "エラー", "警告", "warning", "krkrextract")):
            continue
        hit = []
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(ch, lp, hit=hit):
            c = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(ch, c, 64)
            if c.value == "Button" and wnd_text(ch).strip() in _OK_LABELS:
                hit.append(ch)
            return True
        user32.EnumChildWindows(h, cb, 0)
        for btn in hit:
            user32.SendMessageW(btn, 0x00F5, 0, 0)      # BM_CLICK
        closed.append(title)
    return closed


def _norm_button_label(text: str) -> str:
    """按钮文本归一化：去掉 ``&`` 助记符、首尾空白，大小写不敏感。

    Win32 对话框常把 ``&Full Unpack`` 渲染成带下划线的 ``Full Unpack``，
    ``GetWindowTextW`` 拿到的是带 ``&`` 的原串；只做 ``== label`` 精确比较会
    把明明存在的按钮判成「找不到」。
    """
    return (text or "").replace("&", "").strip().casefold()


def _child_controls(hwnd) -> list[tuple[int, str, str]]:
    """枚举一个窗口的所有子控件，返回 [(hwnd, 类名, 文本)]。"""
    res: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(ch, lp):
        c = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(ch, c, 128)
        res.append((ch, c.value, wnd_text(ch)))
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return res


def _is_modal_title(title: str) -> bool:
    """注入时游戏自己弹的 Information / Error 提示框（不是主界面）。"""
    t = (title or "").lower()
    return any(k in t for k in MODAL_TITLE_HINTS) and not t.startswith(MAIN_TITLE_PREFIX.lower())


def _main_dialogs(pid) -> list[tuple[int, str, str]]:
    """该进程里 KrkrExtract 主界面：按 **pid + 标题** 认，不再要求窗口类名。

    2026-11-07 真机（教师催眠2，15:07 与 15:22 两轮）实证：旧实现硬要求
    `cls == "#32770"`，但 `KrkrExtract.Lite.exe` 是 .NET WinForms（PE 里有
    `System.Windows.Forms`），主窗口类名形如 `WindowsForms10.Window.8.app...`；
    只有注入时弹出的 Information 消息框才是 `#32770`。结果 `wait_ui_window`
    按 pid+标题找得到窗口（rect 有效），按钮枚举却恒为空：
    `主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None`。
    类名现在只用于诊断，不参与「是不是主界面」的判定。
    """
    return [(h, c, t) for h, c, t in top_windows(pid)
            if t.startswith(MAIN_TITLE_PREFIX) and not _is_modal_title(t)]


def _button_candidates(controls, want):
    """挑目标按钮：类名含 BUTTON 优先，其次任何文本精确匹配的控件。

    WinForms 按钮类名是 `WindowsForms10.BUTTON.app.0.xxx`，不是标准 `Button`；
    旧实现 `cls == "Button"` 会把它们全漏掉。仍要求**文本归一化精确相等**，
    不会把同名的静态标签当成按钮去点。
    """
    hits = [(ch, cls, text) for ch, cls, text in controls
            if _norm_button_label(text) == want]
    buttonish = [h for h in hits if "button" in (h[1] or "").lower()]
    return buttonish or hits


def _bm_getcheck(hwnd):
    """点击后复核复选框状态；不是复选框 / 取不到时返回 None（无法复核）。"""
    try:
        rc = user32.SendMessageW(hwnd, BM_GETCHECK, 0, 0)
    except Exception:                                       # noqa: BLE001
        return None
    return rc if rc in (0, 1, 2) else None                  # UNCHECKED / CHECKED / INDETERMINATE


def click_button_ex(pid, label) -> tuple[bool, str]:
    """点主界面按钮，返回 ``(是否点到, 复核状态)``。

    Win32 子控件枚举拿不到按钮时（WPF / 自绘控件），退回 UIA 按名字找并
    Invoke / Toggle / 鼠标点击（``uia_click_button``）。只要有一条路径成功
    并且能复核到「已勾选」，就认为 Full Unpack 真的开了。
    """
    want = _norm_button_label(label)
    if not want:
        return False, "标签为空"
    dialogs = _main_dialogs(pid)
    for h, _cls, _title in dialogs:
        try:
            controls = _child_controls(h)
        except Exception:                                   # noqa: BLE001
            continue                                       # 窗口正销毁：看下一个
        for ch, cls, _text in _button_candidates(controls, want):
            try:
                user32.SendMessageW(ch, BM_CLICK, 0, 0)
            except Exception:                               # noqa: BLE001
                continue
            rc = _bm_getcheck(ch)
            if rc == BST_CHECKED:
                state = "BM_CLICK 已发送，BM_GETCHECK 复核=已勾选"
            elif rc is not None:
                state = f"BM_CLICK 已发送，BM_GETCHECK 复核=未勾选({rc})"
            else:
                state = f"BM_CLICK 已发送（{cls or '未知类名'}，控件不暴露勾选状态，无法复核）"
            return True, state
    for h, _cls, _title in dialogs:
        ok, state = uia_click_button(h, label)
        if ok:
            return True, "UIA 兜底：" + state
    return False, (f"主界面 {len(dialogs)} 个，Win32 与 UIA 都没找到文本为 {label!r} 的控件")


def click_button(pid, label) -> bool:
    """兼容旧调用与既有测试：只关心点到没点到。"""
    return click_button_ex(pid, label)[0]


def describe_unpack_controls(pid) -> dict:
    """**只读诊断**：主界面上到底有哪些控件，'Full Unpack' 有没有被枚举到。

    2026-11-07 补 ``raw_windows`` / ``global_title_matches``：旧版只打印
    「过滤后的空列表」，主窗口到底在不在、类名是什么一概看不到，真因只能靠猜。
    现在失败日志会带上该 pid 的**全部顶层窗口**（hwnd / 类名 / 标题）与
    全局标题命中清单，能直接区分「类名判据过严」和「窗口已消失」。
    """
    diag: dict = {"dialogs": [], "controls": [], "buttons": [],
                  "matched": [], "raw_windows": [], "global_title_matches": [],
                  "error": None}
    try:
        diag["raw_windows"] = list(top_windows(pid))
        dialogs = _main_dialogs(pid)
        if not dialogs:
            # 注入进程 pid 变了 / 主界面重建后，按 pid 过滤会一无所获。
            # 只读地按标题全局再找一次（不点击、不抬窗、不猜按钮），且不再过滤类名。
            found: list[tuple[int, str, str]] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def cb(h, lp):
                title = wnd_text(h)
                if title.startswith(MAIN_TITLE_PREFIX):
                    c = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(h, c, 64)
                    found.append((h, c.value, title))
                return True

            user32.EnumWindows(cb, 0)
            diag["global_title_matches"] = found[:20]
            dialogs = [(h, c, t) for h, c, t in found if not _is_modal_title(t)]
        diag["dialogs"] = [(h, t) for h, _c, t in dialogs]
        for h, _c, _t in dialogs:
            for _ch, cls, text in _child_controls(h):
                diag["controls"].append((cls, text))
                if "button" in (cls or "").lower():
                    diag["buttons"].append(text)
                if _norm_button_label(text) == "full unpack":
                    diag["matched"].append(text)
    except Exception as exc:                                # noqa: BLE001
        diag["error"] = "%s: %s" % (type(exc).__name__, exc)
    return diag


# ---------------------------------------------------------------- 落点 / 遮挡（2026-11-06 加固）

def describe_window(hwnd):
    """遮挡窗口的可读描述 —— 报错要能直接告诉用户「该关哪个窗口」。"""
    if not hwnd:
        # WindowFromPoint 返回 0（该点没有窗口 / 窗口不可见）不是「没有遮挡」：
        # 旧实现统一写 "(none)"，把最需要区分的一类故障糊过去了。
        return "(WindowFromPoint 返回 0 / 无效句柄：该点没有可见窗口)"
    c = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, c, 128)
    return "%s pid=%s title=%r" % (c.value or "?", pid_of_window(hwnd), wnd_text(hwnd)[:60])


def _window_rect(hwnd):
    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return rc


def _rect_valid(rc) -> bool:
    """rect 是否可能包含落点。

    窗口最小化时 Windows 给的是 ``(-32000, -32000, -31840, -31976)`` 这种负坐标
    小矩形；窗口已销毁/句柄失效时 GetWindowRect 给全 0。这两种情况下扫描循环
    ``range(top+6, bottom-6, 40)`` **一次都不会执行** —— 2026-11-06 实跑报错里
    那句 ``(无可见遮挡窗口)`` 就是这么来的：blockers 字典压根是空的，
    并不是「真的没人挡」。
    """
    w, h = rc.right - rc.left, rc.bottom - rc.top
    return (w >= 2 * DROP_GRID and h >= 2 * DROP_GRID
            and rc.left > -30000 and rc.top > -30000
            and rc.right < 60000 and rc.bottom < 60000)


def _win32(name):
    """取 user32 上的可选调用；替身没实现时返回 None（走退化判据，不硬依赖）。"""
    return getattr(user32, name, None)


def _is_window_alive(hwnd) -> bool:
    fn = _win32("IsWindow")
    if fn is None:
        return True                 # 替身没实现：交给 rect / WindowFromPoint 判据
    try:
        return bool(fn(hwnd))
    except Exception:               # noqa: BLE001
        return True


def _is_window_visible(hwnd) -> bool:
    fn = _win32("IsWindowVisible")
    if fn is None:
        return True
    try:
        return bool(fn(hwnd))
    except Exception:               # noqa: BLE001
        return True


def _is_child_of(hwnd, under) -> bool:
    """``under`` 是不是主窗口的子控件（GetAncestor(GA_ROOT) / GetParent 链）。"""
    fn = _win32("GetAncestor")
    if fn is not None:
        try:
            return int(fn(under, GA_ROOT)) == int(hwnd)
        except Exception:           # noqa: BLE001
            pass
    fn = _win32("GetParent")
    if fn is not None:
        try:
            cur = int(under)
            for _ in range(8):
                parent = int(fn(cur))
                if not parent:
                    return False
                if parent == int(hwnd):
                    return True
                cur = parent
        except Exception:           # noqa: BLE001
            pass
    return False


def _classify_point(hwnd, under) -> str:
    """四分类：hit / no_window / child / other。**口径不变**：只有 hit 能当落点。"""
    if not under:
        return "no_window"
    if under == hwnd:
        return "hit"
    if _is_child_of(hwnd, under):
        return "child"
    return "other"


def _rebind_ui_window(hwnd, pid=None):
    """重新枚举 KrkrExtract 主窗口，返回新句柄或 None。

    窗口被关掉再重建、或注入进程 pid 变化后，旧句柄会失效：GetWindowRect 返回全 0，
    扫描循环空转，报错却说「无可见遮挡窗口」。能重新枚举到就自恢复；
    找不到也**不猜**，把真实情况留给报错文本。
    """
    try:
        if pid:
            found = find_ui_window(pid)
            if found and found != hwnd and _is_window_alive(found):
                return found
        res = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(h, lp):
            if wnd_text(h).startswith(MAIN_TITLE_PREFIX) and _is_window_alive(h):
                res.append(h)
            return True

        user32.EnumWindows(cb, 0)
        if res:
            return res[-1]
    except Exception:               # noqa: BLE001
        return None
    return None


def raise_ui_window(hwnd):
    """把 KrkrExtract 主窗口可靠抬到所有普通窗口之上；返回是否拿到前台焦点。

    **前台锁**：Windows 只允许当前前台进程调 ``SetForegroundWindow``，本脚本是被
    orchestrator 拉起的子进程，注入后前台往往还是游戏/浏览器，这个调用会静默返回 0。
    实测 `教师催眠2` 第四轮就是 Chrome 压在 KrkrExtract 上，整块窗口矩形扫不到
    一个可见空白点 → ``no blank spot on KrkrExtract UI``。

    TOPMOST→NOTOPMOST 连招不需要前台权限：先临时置顶越过所有普通窗口，立刻退回
    普通组顶部（Z 序仍在最前），既拿到可见性，也不会把窗口永久置顶留给用户。
    """
    user32.ShowWindow(hwnd, SW_RESTORE)
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


def _scan_drop_point(hwnd, rc):
    """扫一遍窗口矩形，返回 ``(point, blockers, stats)``。

    只接受 ``WindowFromPoint == 主窗口句柄`` 的点：那是父窗口的空白背景，
    ``WM_DROPFILES`` 才会落到注册了拖拽接收的对话框上。按钮 / Static 等子控件
    不一定接受 drop，落到上面会静默丢包，所以**口径不变**：它们不作落点。

    ``stats`` 是 2026-11-06 第二次实跑补的：旧实现只统计「谁挡着」，
    「窗口压根不可见」「采样点全是子控件」「WindowFromPoint 返回 0」这三种
    完全不同的故障会一起塌缩成 ``blockers={}`` → ``(无可见遮挡窗口)``。
    另外旧实现命中第一个点就 ``return``，统计只覆盖命中前的几个点，没有代表性；
    这里扫完整块（约 800 点、每点只是一次 Win32 调用），诊断才有意义。
    """
    blockers: dict[str, int] = {}
    stats: dict = {"sampled": 0, "hit": 0, "no_window": 0, "child": 0, "other": 0,
                   "rect": (rc.left, rc.top, rc.right, rc.bottom),
                   "rect_invalid": False}
    if not _rect_valid(rc):
        stats["rect_invalid"] = True
        return None, blockers, stats
    point = None
    for fy in range(rc.top + 6, rc.bottom - 6, DROP_GRID):
        for fx in range(rc.left + 6, rc.right - 6, DROP_GRID):
            stats["sampled"] += 1
            under = user32.WindowFromPoint(wintypes.POINT(fx, fy))
            kind = _classify_point(hwnd, under)
            stats[kind] += 1
            if kind == "hit":
                if point is None:
                    point = (fx, fy)
                continue                      # 继续扫完，统计才有代表性
            key = ("子控件 " if kind == "child" else "") + describe_window(under)
            blockers[key] = blockers.get(key, 0) + 1
    return point, blockers, stats


def scan_drop_point(hwnd, rc):
    """兼容入口：返回 ``(point, blockers)``；诊断 stats 见 ``_scan_drop_point``。"""
    point, blockers, _stats = _scan_drop_point(hwnd, rc)
    return point, blockers


def _blockers_detail(blockers, stats=None, limit=5):
    """先给采样分类，再列具体遮挡窗口 ——  blockers 为空时也不能说「没人挡」。"""
    top = sorted(blockers.items(), key=lambda kv: -kv[1])[:limit]
    lines = []
    if stats:
        lines.append(
            "  - 采样 %d 点：主窗口空白 %d、无窗口 %d、子控件 %d、其他窗口 %d；rect=%s%s"
            % (stats.get("sampled", 0), stats.get("hit", 0), stats.get("no_window", 0),
               stats.get("child", 0), stats.get("other", 0), stats.get("rect"),
               "（rect 退化/窗口最小化）" if stats.get("rect_invalid") else ""))
    lines += ["  - %s × %d" % (k, v) for k, v in top]
    return "\n".join(lines) or "  - (无可见遮挡窗口)"


def _drop_failure_message(n, blockers, stats, prefix="拖拽落点"):
    """按采样结果给出**如实**的原因，不再一律说「被遮挡」。"""
    sampled = stats.get("sampled", 0)
    if stats.get("rect_invalid") or sampled == 0:
        head = ("%s失败：KrkrExtract 主窗口当前不可见/已关闭（GetWindowRect 返回退化矩形），"
                "重试 %d 轮均未恢复。" % (prefix, n))
    elif stats.get("no_window", 0) == sampled:
        head = ("%s失败：%d 个采样点上 WindowFromPoint 全部返回 0（窗口不可见或已关闭），"
                "重试 %d 轮均未恢复。" % (prefix, sampled, n))
    elif stats.get("child", 0) == sampled:
        head = ("%s失败：窗口内 %d 个采样点全是子控件（按钮/Static 不接收 WM_DROPFILES），"
                "重试 %d 轮仍没有主窗口空白背景。" % (prefix, sampled, n))
    else:
        head = "拖拽落点被遮挡：重试 %d 轮仍未在 KrkrExtract 窗口内找到可见空白点。" % n
    return (head + "\n" + _blockers_detail(blockers, stats) + "\n"
            + "请关闭/最小化上述窗口，确认桌面未锁定、未使用远程桌面；运行期间不要切换窗口。")


def find_drop_point_ex(hwnd, attempts=None):
    """找落点并返回 ``(解析后的主窗口句柄, (x, y))``；全轮失败抛带分类的 RuntimeError。

    每轮：句柄/可见性自检 → 必要时重新枚举主窗口 → 抬窗 → **刷新 rect** → 扫描。
    返回句柄是因为重绑之后调用方（main）必须改用新句柄复核终点、等任务完成，
    否则旧句柄会让后续所有 ``WindowFromPoint == hwnd`` 比较永远失败。
    """
    n = DROP_ATTEMPTS if attempts is None else attempts
    merged: dict[str, int] = {}
    stats: dict = {"sampled": 0, "hit": 0, "no_window": 0, "child": 0, "other": 0}
    cur = hwnd
    for attempt in range(n):
        rc = _window_rect(cur)
        if not _is_window_alive(cur) or not _is_window_visible(cur) or not _rect_valid(rc):
            alt = _rebind_ui_window(cur, pid_of_window(cur))
            if alt:
                log("drop point: 主窗口不可见/句柄失效，已重新绑定到 0x%X" % alt)
                cur = alt
            else:
                log("drop point: 主窗口不可见且重新枚举失败 (rect=(%d,%d,%d,%d))"
                    % (rc.left, rc.top, rc.right, rc.bottom))
        raise_ui_window(cur)
        rc = _window_rect(cur)     # 抬窗后位置/DPI 可能变：必须用新 rect
        point, blockers, stats = _scan_drop_point(cur, rc)
        if point:
            return cur, point
        for k, v in blockers.items():
            merged[k] = merged.get(k, 0) + v
        if attempt + 1 < n:
            time.sleep(1.0)
    raise RuntimeError(_drop_failure_message(n, merged, stats))


def find_drop_point(hwnd, attempts=None):
    """兼容入口：只要落点坐标（既有 7 条替身测试按这个签名用）。"""
    return find_drop_point_ex(hwnd, attempts)[1]


def ensure_drop_point(hwnd, point):
    """拖拽前复核终点：Explorer 被前置后可能又把落点盖住了。

    失效时**只重新扫描、不重新抬窗** —— 抬窗会把 Explorer 压到后面，
    起点（xp3 图标）就点不到了。起点与终点必须同时可见。
    """
    if not _is_window_alive(hwnd) or not _is_window_visible(hwnd):
        raise RuntimeError(
            "拖拽前复核失败：KrkrExtract 主窗口已关闭/不可见，起点与终点无法同时可见。\n"
            "请确认 KrkrExtract 仍在运行、桌面未被锁定；运行期间不要切换窗口。")
    x, y = point
    if user32.WindowFromPoint(wintypes.POINT(x, y)) == hwnd:
        return point
    fresh, blockers, stats = _scan_drop_point(hwnd, _window_rect(hwnd))
    if fresh:
        return fresh
    raise RuntimeError(
        "资源管理器窗口盖住了 KrkrExtract 的全部落点区域，起点与终点无法同时可见。\n%s\n"
        "请把资源管理器窗口缩小或拖到屏幕另一侧后重试；运行期间不要切换窗口。"
        % _blockers_detail(blockers, stats)
    )


def wait_task_done(outdir, ui_hwnd, timeout_min=40):
    """产物数稳定且 UI 标题回 idle 即完成；返回 (total, by_ext, size)。"""
    last, stable = -1, 0
    deadline = time.time() + timeout_min * 60
    last_rep = 0.0
    pid = pid_of_window(ui_hwnd)
    while time.time() < deadline:
        time.sleep(5)
        # 模态提示先关掉：它挡落点、也挡完成判定（见 dismiss_dialogs 的实测说明）
        closed = dismiss_dialogs(pid)
        if closed:
            log("  dismissed dialog(s): %r" % (closed,))
        total, by_ext, size_total = count_files(outdir) if os.path.isdir(outdir) else (0, {}, 0)
        stable = stable + 1 if (total == last and total > 0) else 0
        last = total
        now = time.time()
        if now - last_rep >= 30:
            last_rep = now
            top = sorted(by_ext.items(), key=lambda kv: -kv[1])[:8]
            log("  progress: %d files %.1f MB %s" % (total, size_total / 1048576.0, top))
        # 完成判据：产物数稳定 40s 且确实有产物。**不再**要求「没有任何 #32770」——
        # 主界面自己就是 #32770，旧写法只能靠「标题恰好等于 KrkrExtract」这种巧合来区分，
        # 一旦游戏弹提示就永远判不完成（实测踩过）。
        if stable >= 8:
            log("  task complete (stable 40s)")
            return total, by_ext, size_total
    return last, {}, 0

def write_manifest(outdir, game_dir, per_archive, path):
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    加密 xp3 的地面真相拿不到（GARbro 列不出条目，坑 1 假阴性），
    所以 reconcile.expected 只能是 None + method="no-index-available"
    —— 明说「没对账」，不许用 diff=0 蒙混。

    独立成函数是为了能在没有 GUI 的情况下测（GUI 那半截没法在 CI 里跑）。
    """
    import manifest as mf
    raw_dir = Path(outdir) / "data"
    png_dir = Path(outdir) / "png"
    counts_block = mf.counts(raw_dir, png_dir)
    man = mf.build(
        tool="krkr_auto_extract.py",
        engine="KiriKiri",
        source={"game_dir": os.path.abspath(game_dir),
                "archives": per_archive,
                "encrypted": True,
                "note": "加密 xp3 动态提取：条目数无地面真相（GARbro 列不出），"
                        "故 reconcile 标记为未对账"},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(None, counts_block["raw"]["total"]),
        verify={"verified": False, "reason": "not-run",
                "note": "本工具不做内容级验收，请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[{"tool": "KrkrExtract(内置 tlg→png)", "in": None,
                      "ok": None, "fail": None}] if png_dir.is_dir() else [],
        png_dir=mf.scan_png(png_dir),
    )
    mf.write(Path(path), man)
    return man, counts_block


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_dir")
    ap.add_argument("--out", default=None, help="结束后把 KrkrExtract_Output 移动到这里")
    ap.add_argument("--keep-stage", action="store_true")
    ap.add_argument("--only", default=None, help="逗号分隔的 xp3 文件名列表（断点续传）")
    ap.add_argument("--reuse-stage", action="store_true", help="不重建 stage（续传时用）")
    ap.add_argument("--manifest", default=None,
                    help="manifest.json 输出路径（默认 <--out>/manifest.json）")
    args = ap.parse_args(argv)
    game_dir = args.game_dir
    assert os.path.isdir(game_dir), "game dir not found: %s" % game_dir
    only = [s.strip().lower() for s in args.only.split(",")] if args.only else None

    # ---- 1. stage ----
    # 复制除 *.xp3 外的所有文件（plugin/*.tpm、*.cf 等引擎必需），xp3 用硬链接零拷贝
    stage = os.path.join(STAGE_ROOT, "auto")
    stage_exe = os.path.join(stage, "game.exe")     # 本链路唯一认的「游戏进程」身份
    if args.reuse_stage and os.path.isdir(stage) and os.path.isfile(stage_exe):
        log("reusing existing stage: %s" % stage)
    else:
        for p in pids_by_exe_path(stage_exe):
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
            time.sleep(0.5)
        if os.path.isdir(stage) and not tb.drop_tree(stage):
            # 清不掉就明确失败，别硬往下走：残留的旧 stage 里有上一次的 xp3 硬链接，
            # 复制/硬链接混进去后 KrkrExtract 会拖错包，产物对不上索引，比直接报错难查得多。
            log("ERROR: 无法清理 stage 目录（受保护目录或删除守卫）：%s" % stage)
            return 3
        time.sleep(0.5)
        os.makedirs(stage, exist_ok=True)
        exes = [f for f in os.listdir(game_dir) if f.lower().endswith(".exe") and "krkr" not in f.lower()]
        assert len(exes) == 1, "expected 1 game exe, got %r" % exes
        for dirpath, dirnames, filenames in os.walk(game_dir):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, game_dir)
                dst = os.path.join(stage, rel)
                if fn.lower().endswith(".xp3"):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                else:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
        # 主程序固定为 game.exe（原 exe 已随上面复制，再覆盖一份确保存在）
        shutil.copy2(os.path.join(game_dir, exes[0]), os.path.join(stage, "game.exe"))
        for fn in ("KrkrExtract.Lite.exe", "KrkrExtract.Core.dll", "KrkrExtract.UI.Lite.dll"):
            shutil.copy2(os.path.join(krkr_tool_dir(), fn), os.path.join(stage, fn))
        log("stage ready: %s" % stage)

    # ---- 2. inject（reuse-stage 只跳过文件搬运；游戏进程永远清干净重注入，
    #          否则上一次失败留下的 UI 窗口会叠在新窗口上面互相遮挡）----
    for p in pids_by_exe_path(stage_exe):
        subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
        time.sleep(0.5)
    subprocess.Popen([os.path.join(stage, "KrkrExtract.Lite.exe"), stage_exe], cwd=stage)
    pid = None
    for _ in range(60):
        found = pids_by_exe_path(stage_exe)
        if found:
            pid = found[0]
            break
        time.sleep(0.2)
    assert pid, "game process never appeared"
    time.sleep(5)
    others = [p for p in pids_by_exe_path(stage_exe) if p != pid]
    if others:
        log("killing %d stray game instances" % len(others))
        for p in others:
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
        time.sleep(1.0)
    ui, waited = wait_ui_window(pid)
    if not ui:
        log("KrkrExtract 窗口 %.0fs 内未出现（pid=%d，进程仍在=%s），该 pid 的窗口标题=%r"
            % (waited, pid, bool(pids_by_exe_path(stage_exe)), window_titles(pid)))
        archives = sorted(Path(stage).glob("*.xp3"))
        if only:
            archives = [p for p in archives if p.name.lower() in only]
        pairs = [(p, Path(str(p) + ".index")) for p in archives]
        if not pairs or any(not index.is_file() for _, index in pairs):
            raise RuntimeError("KrkrExtract UI window not found and complete XP3 index dumps unavailable")
        output = Path(stage) / "KrkrExtract_Output"
        dst = Path(args.out) / "KrkrExtract_Output" if args.out else None
        if output.exists() or (dst is not None and dst.exists()):
            raise RuntimeError("XP3 index carve output already exists; refusing to overwrite")
        outdir = output / "data"
        try:
            for archive, index in pairs:
                count = _xp3_carve.extract(archive, index, outdir / archive.stem)
                log("index carve %s: %d files verified" % (archive.name, count))
        except (ValueError, OSError, KeyError) as exc:
            # 消息要把**两件事**都说清：窗口没出现是主因，兜底不适用是次因。
            # 旧的「XP3 index carve failed: …」会让人以为 GUI 跑过了、只是兜底坏了。
            raise RuntimeError(
                "KrkrExtract 窗口 %.0fs 内未出现，静态 index 兜底也不适用：%s" % (waited, exc)
            ) from exc
        if dst is not None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise RuntimeError("XP3 index carve output already exists; refusing to overwrite")
            shutil.move(str(outdir.parent), str(dst))
        return 0
    urc = wintypes.RECT()
    user32.GetWindowRect(ui, ctypes.byref(urc))
    log("injected pid=%d ui=0x%X rect=(%d,%d,%d,%d)" % (pid, ui, urc.left, urc.top, urc.right, urc.bottom))

    # 提示框会盖住整块界面（连落点都找不到）：拖之前先清掉，最多三轮
    for _ in range(3):
        closed = dismiss_dialogs(pid)
        if not closed:
            break
        log("dismissed dialog(s) after inject: %r" % (closed,))
        time.sleep(1.0)

    # 开全模式再拖：否则默认只解脚本（data.xp3 只出 .tjs/.ks，图片/音频包 0 新增）。
    # 2026-11-06 第二次实跑：日志里 `WARNING: ??? 'Full Unpack' ?????` 说明按钮没点上，
    # 旧代码只警告一声就继续拖 11 个包 —— 产物缺图缺音频，而完成判定照样「通过」。
    # **没点上 Full Unpack 必须是明确的失败前置条件**，不能带病继续。
    clicked, click_state = click_button_ex(pid, "Full Unpack")
    if clicked:
        log("unpack mode: Full Unpack 已开启（%s）" % click_state)
    else:
        diag = describe_unpack_controls(pid)
        if diag["matched"]:
            reason = ("按钮文本已枚举到 %r，但 BM_CLICK 没生效（窗口无响应 / 被模态框挡住）"
                      % (diag["matched"],))
        else:
            reason = ("按钮枚举失败：Win32 子控件与 UIA 都没找到文本为 'Full Unpack' 的控件"
                      "（主窗口类名/控件类型与判据不匹配，或主窗口已经消失）")
        # 原始窗口清单必须进日志：15:07/15:22 两轮只打印「过滤后的空列表」，
        # 分不清「类名被过滤」和「窗口真没了」，这次不许再靠猜。
        msg = ("没点上 'Full Unpack'：%s。\n"
               "主窗口=%r；Button 文本=%r；全部子控件=%r；诊断异常=%s\n"
               "该进程顶层窗口(hwnd,类名,标题)=%r\n"
               "全局标题命中=%r\n"
               "点击诊断=%s\n"
               "KrkrExtract 默认只解脚本，继续拖包会交付缺图/缺音频的半份产物，故在此明确失败。"
               % (reason, diag["dialogs"], diag["buttons"],
                  diag["controls"][:20], diag["error"],
                  diag["raw_windows"][:20], diag["global_title_matches"][:20],
                  click_state[:400]))
        log("ERROR: " + msg)
        if ALLOW_NO_FULL_UNPACK:
            log("WARNING: KRKR_ALLOW_NO_FULL_UNPACK=1，跳过该前置检查；产物可能只有脚本（风险自负）")
        else:
            raise RuntimeError(
                msg + "\n若确认该版本界面确实没有该按钮、且已手工开启全解包模式，"
                      "可设 KRKR_ALLOW_NO_FULL_UNPACK=1 跳过本检查（产物缺内容的风险自负）。")
    time.sleep(1.5)

    # 早失败检查：整块窗口被压住时，别等 stage 里开完 Explorer 才发现。
    # 真正的落点在**每个包拖拽前**重新算（find_drop_point_ex + ensure_drop_point）：
    # 中途 Z 序会变 —— Explorer 会被前置、游戏可能弹提示，旧代码 11 个包共用一个
    # 坐标，任何一次遮挡都会让后续全部拖错或卡死。
    # 这里同时接收「重新枚举后的主窗口句柄」：窗口重建后旧句柄会让后续所有比较失效。
    ui, (tx, ty) = find_drop_point_ex(ui)
    log("initial drop point=(%d,%d) ui=0x%X" % (tx, ty, ui))

    outdir = os.path.join(stage, "KrkrExtract_Output")
    before = count_files(outdir)[0] if os.path.isdir(outdir) else 0
    per_archive = []   # 逐包产物数，用于 manifest 的 source.archives

    # ---- 3/4/5. per-xp3 drag ----
    xp3s = sorted(f for f in os.listdir(stage) if f.lower().endswith(".xp3"))
    if only:
        xp3s = [f for f in xp3s if f.lower() in only]
    for fn in xp3s:
        # 每包重新抬窗 + 重扫 + 必要时重绑主窗口：两包之间约 40s，期间窗口被切走也能自恢复。
        ui, (tx, ty) = find_drop_point_ex(ui)
        close_all_explorers(os.path.basename(stage))
        subprocess.Popen(["explorer.exe", "/select," + os.path.join(stage, fn)])
        time.sleep(3.5)
        exp = find_explorer_by_title_hint(os.path.basename(stage))
        assert exp, "explorer window not found for %s" % fn
        user32.SetForegroundWindow(exp)
        time.sleep(1.5)
        # UIA (use the CURRENT explorer hwnd: explorer may recreate it, so re-find until stable)
        rect = None
        for attempt in range(15):
            r = uia_item_rect(exp, fn)
            if r:
                rect = r
                break
            exp = find_explorer_by_title_hint(os.path.basename(stage))
            if not exp:
                break
            time.sleep(1.2)
        assert rect, "UIA item rect not found for %s" % fn
        ix, iy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        # 落点/起点遮挡防御：被挡时前置 Explorer 重取矩形重试（最多 4 次）
        ok_point = False
        for retry in range(4):
            under = user32.WindowFromPoint(wintypes.POINT(ix, iy))
            ucls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(under, ucls, 64)
            log("%s: item center=(%d,%d) under cls=%s (retry %d)" % (fn, ix, iy, ucls.value, retry))
            if "CabinetW" in ucls.value or "DirectUIHWND" in ucls.value:
                ok_point = True
                break
            user32.SetForegroundWindow(exp)
            time.sleep(1.2)
            r = uia_item_rect(exp, fn)
            if r:
                rect = r
                ix, iy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        assert ok_point, "item point blocked for %s" % fn
        dismiss_dialogs(pid)          # 每包前再清一次：游戏可能又弹了提示
        # Explorer 前置后复核终点：盖住了就在当前 Z 序里换个仍可见的空白点。
        tx, ty = ensure_drop_point(ui, (tx, ty))
        log("dragging %s -> (%d,%d) ..." % (fn, tx, ty))
        drag(ix, iy, tx, ty)
        total, by_ext, size_total = wait_task_done(outdir, ui)
        log("%s done: +%d files (total %d)" % (fn, total - before, total))
        # 键名走 manifest 的规范三键（2026-11-04）：加密包没有索引，
        # `entries`（地面真相）只能是 None；本包实测新增数属于 `extracted`。
        # 早前写成 `files/total_after`，下游读 source.archives 得按链路分支兼容。
        per_archive.append({"name": fn, "entries": None, "extracted": total - before,
                            "total_after": total})
        before = total

    total, by_ext, size_total = count_files(outdir)
    log("ALL DONE: %d files %.1f MB" % (total, size_total / 1048576.0))
    log("by_ext %s" % json.dumps(by_ext, sort_keys=True))
    log("output at: %s" % outdir)

    # ---- manifest（software-plan §2 契约，raw/final/converted 三段式）----
    manifest_path = args.manifest
    if manifest_path is None and args.out:
        manifest_path = os.path.join(args.out, "manifest.json")
    if manifest_path:
        try:
            man, counts_block = write_manifest(outdir, game_dir, per_archive, manifest_path)
            log("manifest: %s" % manifest_path)
            log("counts raw=%d final=%d converted=%s"
                % (counts_block["raw"]["total"], counts_block["final"]["total"],
                   json.dumps(counts_block["converted"], sort_keys=True)))
        except Exception as exc:                               # noqa: BLE001
            log("manifest 生成失败（不影响产物）: %s: %s" % (type(exc).__name__, exc))

    if args.out:
        dst = os.path.join(args.out, "KrkrExtract_Output")
        os.makedirs(args.out, exist_ok=True)
        if not tb.drop_tree(dst):
            # shutil.move 到已存在的目录会**静默嵌入一层**（dst/KrkrExtract_Output/...），
            # orchestrator 那边再搬一次就变成 png/png/。宁可失败并留好产物路径。
            log("ERROR: 目标已存在且删不掉，放弃搬移以免嵌层：%s" % dst)
            log("产物仍留在：%s" % outdir)
            return 1
        shutil.move(outdir, dst)
        log("moved output to %s" % dst)

    if not args.keep_stage:
        close_all_explorers(os.path.basename(stage))
        for p in pids_by_exe_path(stage_exe):
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
