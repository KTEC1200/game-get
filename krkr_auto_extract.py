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

LOG = os.path.join(STAGE_ROOT, "krkr_auto_extract.log")
def log(msg):
    os.makedirs(STAGE_ROOT, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + str(msg) + "\n")
    print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)

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
        if p.value == pid and wnd_text(h).startswith("KrkrExtract(local"):
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

def uia_item_rect(exp_hwnd, item_name):
    """UIA item rect; returns physical (l,t,r,b) or None. Retries; follows hwnd recreation."""
    for attempt in range(15):
        ps = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_uia_item_rect.ps1"),
                             "-ItemName", item_name, "-Hwnd", str(exp_hwnd)],
                            capture_output=True)
        so = ps.stdout.decode("utf-8", errors="replace").strip()
        scr, rline = None, None
        for ln in so.splitlines():
            if ln.startswith("SCR"):
                _, sw, sh = ln.split()
                scr = (int(sw), int(sh))
            elif ln.startswith("RECT"):
                rline = ln
        if scr and rline:
            _, l, t, r, b = rline.split()
            l, t, r, b = int(l), int(t), int(r), int(b)
            scale = user32.GetSystemMetrics(0) // max(scr[0], 1)
            if scale != 1:
                l, t, r, b = l * scale, t * scale, r * scale, b * scale
            return (l, t, r, b)
        time.sleep(1.2)
    return None

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

    主界面标题形如 `KrkrExtract(local 5.0.0.2) - built on …`，同属 `#32770`，
    必须按标题前缀排除，否则会把工具自己的窗口关掉。
    """
    closed = []
    for h, cls, title in top_windows(pid):
        if cls != "#32770" or title.startswith("KrkrExtract(local"):
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


def click_button(pid, label):
    """按文本点主界面上的按钮，返回是否点到。

    2026-11-06 实测 `教师催眠2` 才发现的坑：KrkrExtract 的解包模式是**开关式**的，
    而本脚本从来没设过 —— 默认只开了「Decompile Script」。后果：
      · data.xp3 拖进去 → 46 个 `.tjs` + 11 个 `.ks`（**纯脚本**，一张图都没有）
      · image00.xp3 拖进去 → 57 → 57，**0 新增**，而且判定为「任务完成」
    教师催眠1 当年能出 2009 张图，是因为那个 stage 里带着上一次手工操作留下的配置 ——
    换句话说，这条链路一直是「碰巧能跑」，换台机器/换次重建就退化成只解脚本。
    """
    for h, cls, title in top_windows(pid):
        if cls != "#32770" or not title.startswith("KrkrExtract(local"):
            continue
        hit = []
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(ch, lp, hit=hit):
            c = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(ch, c, 64)
            if c.value == "Button" and wnd_text(ch).strip() == label:
                hit.append(ch)
            return True
        user32.EnumChildWindows(h, cb, 0)
        for btn in hit:
            user32.SendMessageW(btn, 0x00F5, 0, 0)      # BM_CLICK
        return bool(hit)
    return False


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

    # 开全模式再拖：否则默认只解脚本（data.xp3 只出 .tjs/.ks，图片/音频包 0 新增）
    if click_button(pid, "Full Unpack"):
        log("unpack mode: Full Unpack 已开启")
    else:
        log("WARNING: 没找到 'Full Unpack' 按钮，沿用当前模式（可能只解脚本）")
    time.sleep(1.5)

    # blank drop point on the dialog (raise the window first; retry; log blockers)
    drop = None
    blocker = {}
    for attempt in range(4):
        user32.SetForegroundWindow(ui)
        time.sleep(1.0)
        for fx in range(urc.left + 6, urc.right - 6, 40):
            for fy in range(urc.top + 6, urc.bottom - 6, 40):
                under = user32.WindowFromPoint(wintypes.POINT(fx, fy))
                if under == ui:
                    drop = (fx, fy)
                    break
                if under:
                    c = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(under, c, 64)
                    blocker[c.value] = blocker.get(c.value, 0) + 1
            if drop:
                break
        if drop:
            break
        time.sleep(2.0)
    if not drop:
        log("blockers on dialog: %r" % blocker)
    assert drop, "no blank spot on KrkrExtract UI"
    tx, ty = drop
    log("drop point=(%d,%d)" % drop)

    outdir = os.path.join(stage, "KrkrExtract_Output")
    before = count_files(outdir)[0] if os.path.isdir(outdir) else 0
    per_archive = []   # 逐包产物数，用于 manifest 的 source.archives

    # ---- 3/4/5. per-xp3 drag ----
    xp3s = sorted(f for f in os.listdir(stage) if f.lower().endswith(".xp3"))
    if only:
        xp3s = [f for f in xp3s if f.lower() in only]
    for fn in xp3s:
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
        log("dragging %s ..." % fn)
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
