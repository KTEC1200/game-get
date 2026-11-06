#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境自检（`--doctor` / GUI「环境自检」按钮）：把「为什么写不进去」变成一段可复制文本。

为什么要单独一个模块：2026-11-06 排查「输出目录不可写」时，结论是**五六个互不相关的
命令行工具拼出来的** —— `icacls` 看 ACL、`fltmc` 看过滤驱动、服务列表看终端防护、
火绒的 sqlite 看白名单、两次 `runas` 对照看令牌。这些在用户机器上没法现场敲，
也不该要求用户会敲。于是把**只读**探测集中到这里：用户点一下、复制、发过来即可。

纪律（与 `_verify_media` 一类诊断脚本同一套）：
  * **只读**：唯一会落盘的动作是 write-probe（建 `write-probe.txt` 再删），
    不改配置、不删用户文件。
  * **失败不中断**：单项探测抛异常就记一句、继续下一项 —— 残缺的报告也比没有强。
  * **不调 subprocess**：冻结包里没有解释器可拉（AGENTS「打包必修第 1 条」），
    进程与令牌信息全部走 ctypes。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"

#: 扫描进程用的上限（本机实测 300~500 个进程，8192 足够，不必动态扩容）
_MAX_PIDS = 8192
_MAX_PATH = 32768
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: 值得写进报告的安全类进程。键是**小写文件名**，值是给人看的说明。
#: 只列「会挂在文件写入路径上」或「会被误当成拦路者」的那几个，不做全量清单。
WATCH_PROCESSES = {
    "hipsdaemon.exe": "火绒 防护守护进程（真正做防护的是它，托盘退出不会停它）",
    "hipstray.exe": "火绒 托盘界面（关掉它不等于关防护）",
    "usysdiag.exe": "火绒 6.x 主程序",
    "msmpeng.exe": "Microsoft Defender 反恶意软件服务",
    "smartscreen.exe": "Microsoft SmartScreen（只看启动，不拦写入）",
    "ecagent.exe": "深信服 EasyConnect 代理",
    "sangforpwex.exe": "深信服 VPN 安全防护服务",
    "sangforudprotectex.exe": "深信服 UD Protect 组件",
    "360tray.exe": "360 安全卫士",
    "zhudongfangyu.exe": "360 主动防御",
    "qqpcmgr.exe": "腾讯电脑管家",
}

#: 注册表里值得看一眼的驱动/服务名（**注册不等于运行**，报告里会写清楚）
WATCH_SERVICES = ("sysdiag", "hrdevmon", "hrwfpdrv", "HipsDaemon", "WinDefend", "WdFilter")


def _ok(fn, default="未知"):
    """单项探测一律兜住：报告残缺好过整个自检崩掉。"""
    try:
        return fn()
    except Exception as exc:                                  # noqa: BLE001
        return f"{default}（探测异常：{type(exc).__name__}: {exc}）"


def integrity_level() -> str:
    """当前进程的完整性级别。低/中/高对写入能不能成，比「是否管理员」更能说明问题。"""
    if not IS_WIN:
        return "非 Windows"
    adv, k32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    adv.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                     ctypes.POINTER(ctypes.c_void_p)]
    adv.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
    token = ctypes.c_void_p()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return "打不开进程令牌"
    try:
        need = ctypes.c_ulong(0)
        adv.GetTokenInformation(token, 25, None, 0, ctypes.byref(need))   # 25=IntegrityLevel
        buf = ctypes.create_string_buffer(need.value)
        if not adv.GetTokenInformation(token, 25, buf, need, ctypes.byref(need)):
            return "查询令牌信息失败"
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = adv.GetSidSubAuthorityCount(ctypes.c_void_p(sid)).contents.value
        rid = adv.GetSidSubAuthority(ctypes.c_void_p(sid), count - 1).contents.value
    finally:
        k32.CloseHandle(token)
    # 这几个常量是 WinNT.h 的 SECURITY_MANDATORY_*_RID，不会变
    names = {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
             0x2100: "Medium Plus", 0x3000: "High", 0x4000: "System"}
    return f"{names.get(rid, '未知')}（0x{rid:X}）"


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:                                         # noqa: BLE001
        return False


def uac_enabled() -> str:
    """UAC 是否开启。**关掉 UAC 的机器上「右键以管理员身份运行」是个空操作** ——
    不会弹授权框、令牌与双击完全一样（2026-11-06 实测踩过：用户以为试过提权，其实没有）。"""
    if not IS_WIN:
        return "非 Windows"
    try:
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            val, _ = winreg.QueryValueEx(k, "EnableLUA")
        return f"{'开启' if val else '已关闭（提权类操作全部无效）'}（EnableLUA={val}）"
    except OSError as exc:
        return f"读不到（{exc}）"


def running_processes() -> dict[str, str]:
    """小写文件名 → 完整路径。拿不到权限的进程会被跳过，属正常。"""
    if not IS_WIN:
        return {}
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                               ctypes.c_wchar_p,
                                               ctypes.POINTER(ctypes.c_ulong)]
    arr = (ctypes.c_ulong * _MAX_PIDS)()
    need = ctypes.c_ulong()
    if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(need)):
        return {}
    found: dict[str, str] = {}
    for i in range(need.value // ctypes.sizeof(ctypes.c_ulong)):
        pid = arr[i]
        if not pid:
            continue
        h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            size = ctypes.c_ulong(_MAX_PATH)
            buf = ctypes.create_unicode_buffer(_MAX_PATH)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                found[os.path.basename(buf.value).lower()] = buf.value
        finally:
            k32.CloseHandle(h)
    return found


def service_registered(name: str) -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SYSTEM\CurrentControlSet\Services\{name}"):
            return True
    except OSError:
        return False


def probe(path: Path) -> str:
    """能不能在这个目录里「建目录 + 写文件 + 删文件」。与 GUI 的探针同一口径。

    **不留痕**：目录原本不存在时，探完把它删掉（空目录才删得掉，删不掉就留着）。
    自检是诊断，不该顺手在用户盘上/仓库里造一堆空目录出来。
    """
    existed = path.is_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
        f = path / "write-probe.txt"
        f.write_text("x", encoding="utf-8")
        f.unlink()
        verdict = "可写"
    except OSError as exc:
        verdict = f"不可写 —— {type(exc).__name__}: {exc}"
    if not existed:
        try:
            path.rmdir()
        except OSError:
            pass                      # 非空/被占用就算了，别为了干净去递归删
    return verdict


def _free_space(path: Path) -> str:
    try:
        base = path if path.is_dir() else path.parent
        while not base.is_dir() and base.parent != base:
            base = base.parent
        return f"{shutil.disk_usage(base).free / 2**30:.1f} GiB 可用"
    except OSError:
        return "余量未知"


def candidate_dirs(game_dir: Path | None, app_root: Path) -> list[tuple[str, Path]]:
    """要探的位置：从「程序自己的目录」到「用户数据目录」，覆盖典型放行策略。"""
    items: list[tuple[str, Path]] = [("程序目录 output", app_root / "output")]
    if game_dir is not None:
        items.append(("游戏目录 output", game_dir / "output"))
    for label, env in (("LOCALAPPDATA", "LOCALAPPDATA"), ("临时目录", "TEMP"),
                       ("桌面", "USERPROFILE"), ("用户目录", "USERPROFILE")):
        base = os.environ.get(env)
        if not base:
            continue
        root = Path(base)
        if label == "桌面":
            items.append((label, root / "Desktop" / "GalgameUnpacker-output"))
        elif label == "用户目录":
            items.append((label, root / "GalgameUnpacker-output"))
        else:
            items.append((label, root / "GalgameUnpacker" / "output"))
    return items


def doctor_report(game_dir: Path | None = None, app_root: Path | None = None,
                  version: str = "未知") -> str:
    """组装报告。**纯函数**（除了 probe 会建一个探针文件），便于测试。"""
    root = Path(app_root) if app_root else (
        Path(sys.executable).parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)
    game = Path(game_dir) if game_dir else None

    out: list[str] = []
    add = out.append
    add("Galgame Unpacker 环境自检")
    add("=" * 58)

    add("")
    add("[程序]")
    add(f"  版本      : {version}")
    add(f"  打包态    : {'冻结 exe' if getattr(sys, 'frozen', False) else '源码运行'}")
    add(f"  程序路径  : {sys.executable}")
    add(f"  程序目录  : {root}")
    add(f"  当前目录  : {os.getcwd()}")
    add(f"  Python    : {sys.version.split()[0]} / {sys.platform}")

    add("")
    add("[身份与权限]")
    add(f"  用户      : {_ok(lambda: os.environ.get('USERDOMAIN', '?'))}"
        f"\\{_ok(lambda: os.environ.get('USERNAME', '?'))}")
    add(f"  管理员组  : {'是' if _ok(is_admin, False) else '否'}")
    add(f"  完整性级别: {_ok(integrity_level)}")
    add(f"  UAC       : {_ok(uac_enabled)}")

    add("")
    add("[终端防护 / 安全软件]")
    procs = _ok(running_processes, {}) or {}
    hits = [(name, WATCH_PROCESSES[name]) for name in WATCH_PROCESSES if name in procs]
    if hits:
        for name, label in hits:
            add(f"  运行中    : {name} —— {label}")
    else:
        add("  运行中    : 未发现常见安全类进程")
    drivers = [n for n in WATCH_SERVICES if _ok(lambda n=n: service_registered(n), False)]
    add(f"  已注册驱动: {', '.join(drivers) if drivers else '无'}"
        f"（注册 ≠ 运行，仅供对照）")

    add("")
    add("[写探针]（建目录 + 写 write-probe.txt + 删除，与 GUI 判定同一口径）")
    table = candidate_dirs(game, root)
    results: list[tuple[str, Path, str]] = []
    for label, path in table:
        verdict = _ok(lambda p=path: probe(p), "探测异常")
        results.append((label, path, verdict))
        add(f"  {label:<14}: {verdict}")
        add(f"  {'':<14}  {path}（{_free_space(path)}）")

    add("")
    add("[结论]")
    ok_labels = [label for label, _p, v in results if v == "可写"]
    if not ok_labels:
        add("  连程序自身目录都写不进去 —— 拦截在进程级，与选哪个目录无关。")
        add("  建议：退出全部安全软件后复跑本自检；仍失败就换一台机器/虚拟机。")
    elif ok_labels[0] == "程序目录 output" and len(ok_labels) < len(results):
        add("  只有程序自身目录可写，用户数据目录全部不可写。")
        add("  这是「按进程 + 按目录」放行的拦截特征（不是 ACL、不是磁盘只读）。")
        add("  GUI 会自动改用「程序目录\\output」继续跑；产物路径会写在日志第一行。")
    elif len(ok_labels) == len(results):
        add("  全部位置可写，写入链路正常。")
    else:
        add(f"  可写：{'、'.join(ok_labels)}")
        add(f"  不可写：{'、'.join(l for l, _p, v in results if v != '可写')}")

    add("")
    add("把以上内容整段发回即可（不含个人信息以外的内容）。")
    return "\n".join(out)


if __name__ == "__main__":
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(doctor_report(arg))
