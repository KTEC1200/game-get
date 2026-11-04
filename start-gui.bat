@echo off
rem ============================================================================
rem  用系统 Python 直接跑 GUI（源码态备用入口）
rem
rem  什么时候用它：便携版 orchestrator.exe 被终端防护按进程信誉拦住写不出来，
rem  加白名单又不方便时。python.exe 通常早已在白名单里（它天天装包写文件），
rem  走这条路可以完全绕开 exe 的信誉问题。
rem
rem  前提：本目录是完整仓库（orchestrator.py / rules / cases 都在），且系统里有
rem  Python 3.11+ 与 Pillow。缺依赖会提示，不会闪退。
rem
rem  用法：双击 = 开图形界面；也可传参数，例如
rem        start-gui.bat --gui-smoke        自检（不弹窗）
rem        start-gui.bat "D:\HY\某游戏" --out "D:\HY\某游戏\output"
rem ============================================================================
setlocal
cd /d "%~dp0"

set "LAUNCH="

rem ① 本机显式安装的 3.14（依赖最全的位置）
if exist "C:\Python314\pythonw.exe" (
    "C:\Python314\python.exe" -c "import PIL, tkinter" >nul 2>&1
    if not errorlevel 1 (
        set "LAUNCH=C:\Python314\pythonw.exe"
        set "LAUNCH_CONSOLE=C:\Python314\python.exe"
    )
)

rem ② py 启动器：挑第一个装了 Pillow 的版本
if not defined LAUNCH (
    for %%V in (3.14 3.13 3.12 3.11) do (
        if not defined LAUNCH (
            py -%%V -c "import PIL, tkinter" >nul 2>&1
            if not errorlevel 1 (
                set "LAUNCH=pyw -%%V"
                set "LAUNCH_CONSOLE=py -%%V"
            )
        )
    )
)

rem ③ PATH 里的 python
if not defined LAUNCH (
    python -c "import PIL, tkinter" >nul 2>&1
    if not errorlevel 1 (
        set "LAUNCH=pythonw"
        set "LAUNCH_CONSOLE=python"
    )
)

if not defined LAUNCH (
    echo.
    echo   找不到可用的 Python 3.11+（要求已安装 Pillow）。
    echo.
    echo   两条路选一条：
    echo     1. 仍然用便携版 orchestrator.exe，把解压目录加入杀软信任区
    echo     2. 装 Python 后执行：pip install pillow
    echo.
    pause
    exit /b 1
)

rem 传了参数就用控制台版 python（能看到输出与报错），双击才用 pythonw（不弹黑框）
if "%~1"=="" (
    start "" %LAUNCH% "%~dp0orchestrator.py" --gui
) else (
    %LAUNCH_CONSOLE% "%~dp0orchestrator.py" %*
)
exit /b 0
