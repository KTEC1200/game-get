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

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()  # 本机 200% 缩放：此后全部坐标为物理像素

KRKR_TOOL = r"D:\K\galgame\krkr\krkr"
#: ASCII stage 根目录。**必须纯 ASCII**（verified-findings §17.2）：CJK 路径注入后游戏进程活着
#: 但窗口不弹，只弹「ANSI 文字列を UNICODE 文字列に変換できません」。
#: 放在项目目录下（2026-10-29 起主目录是 D:\K\deepseek），名字固定为 `_krkr_stage`，已被 .gitignore 排除。
STAGE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_krkr_stage")

LOG = os.path.join(STAGE_ROOT, "krkr_auto_extract.log")
def log(msg):
    os.makedirs(STAGE_ROOT, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + str(msg) + "\n")
    print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)

def pids_by_name(name):
    TH32CS_SNAPPROCESS = 0x2
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    res = []
    e = PE(); e.dwSize = ctypes.sizeof(PE)
    ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        if e.szExeFile.lower() == name.lower():
            res.append(e.th32ProcessID)
        ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    kernel32.CloseHandle(snap)
    return res

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

def all_cabinets():
    res = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        c = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, c, 64)
        if c.value == "CabinetWClass":
            res.append(h)
        return True
    user32.EnumWindows(cb, 0)
    return res

def close_all_explorers():
    for _ in range(6):
        wins = all_cabinets()
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
    res = [None]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, lp):
        c = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, c, 64)
        if c.value == "CabinetWClass" and hint and hint in wnd_text(h):
            res[0] = h
        return True
    user32.EnumWindows(cb, 0)
    return res[0]

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

def wait_task_done(outdir, ui_hwnd, timeout_min=40):
    """产物数稳定且 UI 标题回 idle 即完成；返回 (total, by_ext, size)。"""
    last, stable = -1, 0
    deadline = time.time() + timeout_min * 60
    last_rep = 0.0
    while time.time() < deadline:
        time.sleep(5)
        total, by_ext, size_total = count_files(outdir) if os.path.isdir(outdir) else (0, {}, 0)
        stable = stable + 1 if (total == last and total > 0) else 0
        last = total
        now = time.time()
        if now - last_rep >= 30:
            last_rep = now
            top = sorted(by_ext.items(), key=lambda kv: -kv[1])[:8]
            log("  progress: %d files %.1f MB %s" % (total, size_total / 1048576.0, top))
        box = user32.FindWindowW("#32770", "KrkrExtract")
        if box:
            log("  WARNING: task error dialog (title=KrkrExtract) present")
        if stable >= 8 and not box:
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
        verify={"verified": False,
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
    if args.reuse_stage and os.path.isdir(stage) and os.path.isfile(os.path.join(stage, "game.exe")):
        log("reusing existing stage: %s" % stage)
    else:
        for p in pids_by_name("game.exe"):
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
            time.sleep(0.5)
        if os.path.isdir(stage):
            shutil.rmtree(stage, ignore_errors=True)
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
            shutil.copy2(os.path.join(KRKR_TOOL, fn), os.path.join(stage, fn))
        log("stage ready: %s" % stage)

    # ---- 2. inject（reuse-stage 只跳过文件搬运；游戏进程永远清干净重注入，
    #          否则上一次失败留下的 UI 窗口会叠在新窗口上面互相遮挡）----
    for p in pids_by_name("game.exe"):
        subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
        time.sleep(0.5)
    subprocess.Popen([os.path.join(stage, "KrkrExtract.Lite.exe"), os.path.join(stage, "game.exe")], cwd=stage)
    pid = None
    for _ in range(60):
        if pids_by_name("game.exe"):
            pid = pids_by_name("game.exe")[0]
            break
        time.sleep(0.2)
    assert pid, "game process never appeared"
    time.sleep(5)
    others = [p for p in pids_by_name("game.exe") if p != pid]
    if others:
        log("killing %d stray game instances" % len(others))
        for p in others:
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
        time.sleep(1.0)
    ui = find_ui_window(pid)
    assert ui, "KrkrExtract UI window not found (error dialog? wrong path?)"
    urc = wintypes.RECT()
    user32.GetWindowRect(ui, ctypes.byref(urc))
    log("injected pid=%d ui=0x%X rect=(%d,%d,%d,%d)" % (pid, ui, urc.left, urc.top, urc.right, urc.bottom))

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
        close_all_explorers()
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
        log("dragging %s ..." % fn)
        drag(ix, iy, tx, ty)
        total, by_ext, size_total = wait_task_done(outdir, ui)
        log("%s done: +%d files (total %d)" % (fn, total - before, total))
        per_archive.append({"name": fn, "files": total - before, "total_after": total})
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
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.move(outdir, dst)
        log("moved output to %s" % dst)

    if not args.keep_stage:
        close_all_explorers()
        for p in pids_by_name("game.exe"):
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
