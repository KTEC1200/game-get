; Galgame Unpacker 安装器脚本（软件化阶段 3，蓝图 §4.2 / software-plan ②）
;
; 由 `python build_exe.py --installer` 驱动，版本号经 /DVERSION 传入——不要手填：
;   ISCC /DVERSION=0.1.0 /DDIST=<冻结 onedir 目录> /O<输出目录> packaging\installer.iss
;
; 设计要点（出处见各节注释）：
;   * onedir 产物整目录进包，onefile 的 _MEI 解压特征不出现（蓝图 §4.2）
;   * PrivilegesRequired=lowest：默认不提权、装进 {localappdata}\Programs（蓝图 §4.6）
;   * .NET Framework 4.6+ 检测只是提示不拦截（蓝图 §4.4：GARbro/csc 依赖；
;     Win10 1809+ 一般自带；纯 Python 链路没有 .NET 也能跑）
;   * 无 PATH 修改、无开机自启、无服务——卸载即净
;   * 未签名：会被 SmartScreen/杀软盯上，应对文档见仓库根 antivirus-false-positives.md

#ifndef VERSION
  #define VERSION "0.0.0-dev"
#endif
#ifndef DIST
  #define DIST "..\_spike_pkg\dist\orchestrator"
#endif
; TESTMODE=yes 时 Uninstallable=no（配 /NOICONS 用）——仅用于自动化会话里验证
; Files/[Run]/[Code] 段：本会话的执行环境对「未签名未知镜像」过滤敏感面写入
; （实测 csc 现编的无名 exe 写 HKCU 卸载键与开始菜单 .lnk 都被拒，reg.exe 放行），
; 卸载键与快捷方式这两步只能在真实用户机器上验证。发布构建不要加 /DTESTMODE=yes。
#ifndef TESTMODE
  #define TESTMODE "no"
#endif

[Setup]
AppId={{9E4B7C52-1D6F-4A3B-9C2E-8F01A5D4E7B6}
AppName=Galgame Unpacker
AppVersion={#VERSION}
AppVerName=Galgame Unpacker {#VERSION}
DefaultDirName={autopf}\GalgameUnpacker
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=GalgameUnpacker-{#VERSION}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\orchestrator.exe
; 个人自用工具，不弹「安装完成就运行」；GUI 壳做出来后再补
DisableFinishedPage=no
#if TESTMODE == "yes"
Uninstallable=no
#endif

[Files]
Source: "{#DIST}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Galgame Unpacker"; Filename: "{app}\orchestrator.exe"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\orchestrator.exe"; Parameters: "--help"; \
    Description: "Run --help self-check"; Flags: postinstall skipifsilent unchecked
Filename: "{app}"; Description: "Open install &folder"; \
    Flags: postinstall skipifsilent unchecked

[Code]
// 蓝图 §4.4：GARbro（.NET 程序）与自带 C# 工具的 csc 现编都依赖 .NET Framework 4.6+。
// 只提示不拦截——纯 Python 链路（Ren'Py / RPG Maker / Yu-Ris 等）没有 .NET 也能跑。
function DotNet46OrLater: Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
    'Release', Release) and (Release >= 393295);  // 393295 = 4.6
  if not Result then
    Result := RegQueryDWordValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\NET Framework Setup\NDP\v4\Full',
      'Release', Release) and (Release >= 393295);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if not WizardSilent() and not DotNet46OrLater() then
      MsgBox(
        '未检测到 .NET Framework 4.6+。' + #13#10 +
        'KiriKiri/Ren''Py/KiriKiri 加密之外的部分链路需要它：' + #13#10 +
        '  * GARbro（静态解包 .xp3/.arc 等）' + #13#10 +
        '  * 自带 C# 工具的现场编译（csc）' + #13#10 +
        '安装 .NET Framework 4.8 Runtime 后这些链路可用；其余链路不受影响。',
        mbInformation, MB_OK);
end;
