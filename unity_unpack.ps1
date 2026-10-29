# Unity 游戏解包（AssetStudio.CLI）—— 实测可用的完整流程
#
# 用法:
#   .\unity_unpack.ps1 -GameDir "D:\Games\某游戏" [-OutDir <解包目录>]
#
# 本脚本固化了 2026-10-12 在 Unity 2022.3.62f2 / Mono 游戏上的实测结论。
# 关键坑（详见 verified-findings.md §8）：
#   1) AssetStudio.CLI 的 --types 参数**不能用逗号分隔**：`--types A,B,C` 会被
#      静默忽略（退出码仍是 0），结果是 0 个文件。单类型 `--types A` 才有效。
#   2) Start-Process -ArgumentList 不会给含空格的路径加引号 → 路径被拆碎。
#      必须用 PowerShell 调用符 `&`，它会自动加引号。
#   3) 一次性全导 800MB+ 会在收尾时崩（0xC0000374 堆损坏）。
#      → 按类型分批独立导出，每批各自校验。
#   4) AudioClip 若为 FSB5(FMOD) 容器，CLI 单次只能导出很小一部分且静默失败，
#      需配合 _as_audio_collect2.py 多轮分组累积。
param(
    [Parameter(Mandatory = $true)][string]$GameDir,
    [string]$OutDir,
    [string]$Exe = 'D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe',
    [switch]$SkipAudio
)

$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $GameDir)) { throw "游戏目录不存在: $GameDir" }
if (-not (Test-Path -LiteralPath $Exe)) { throw "找不到 AssetStudio.CLI: $Exe" }

# --- 定位 _Data 目录（Unity 标志），没找到就用游戏根目录 ---
$dataDir = Get-ChildItem -LiteralPath $GameDir -Directory |
    Where-Object { $_.Name -like '*_Data' } | Select-Object -First 1
if (-not $dataDir) { $dataDir = Get-Item -LiteralPath $GameDir }
Write-Host "输入(AssetStudio 用): $($dataDir.FullName)"

if (-not $OutDir) { $OutDir = Join-Path $GameDir '_extracted' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-Host "输出: $OutDir"

# --- 读引擎版本与后端（决定是否需要 AssetStudioNext / Il2CppDumper）---
$ver = '<unknown>'
foreach ($n in @('globalgamemanagers', 'level0')) {
    $p = Join-Path $dataDir.FullName $n
    if (Test-Path $p) {
        $fs = [IO.File]::OpenRead($p); $b = New-Object byte[] 4096; $null = $fs.Read($b, 0, 4096); $fs.Close()
        $m = [regex]::Match([Text.Encoding]::ASCII.GetString($b), '\d+\.\d+\.\d+[a-z]\d+')
        if ($m.Success) { $ver = $m.Value; break }
    }
}
$il2cpp = Test-Path (Join-Path $dataDir.FullName 'il2cpp_data')
Write-Host "Unity 版本: $ver   后端: $(if ($il2cpp) { 'IL2CPP' } else { 'Mono' })"
if ($ver -like '6000.*' -or $ver -like '6.*') {
    Write-Host "[注意] Unity 6000 系改过 Shader 序列化，若报 EndOfStreamException 请改用 AssetStudioNext" -ForegroundColor Yellow
}
if ($il2cpp) {
    Write-Host "[注意] IL2CPP 后端：需要先跑 Il2CppDumper（GameAssembly.dll + il2cpp_data/global-metadata.dat）" -ForegroundColor Yellow
}

# --- 分批导出（每批独立目录，规避一次性全导的崩溃）---
$batches = @(
    @{ name = 'Texture2D'; dir = 'Image_Texture2D' },
    @{ name = 'Sprite';    dir = 'Image_Sprite'    }
)
if (-not $SkipAudio) { $batches += @{ name = 'AudioClip'; dir = 'Audio' } }

foreach ($b in $batches) {
    $tmp = Join-Path $OutDir ("_raw_" + $b.name)
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $log = Join-Path $tmp '_log.txt'
    Write-Host "`n--- 导出 $($b.name) ---"
    # 注意：用 & 调用符（自动引号）；--types 只给单类型
    & $Exe $dataDir.FullName $tmp --game Normal --types $b.name --export_type Convert --group_assets ByType *> $log
    $code = $LASTEXITCODE
    # AssetStudio 会把产物放进 <tmp>\<TypeName>\ 子目录
    $sub = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
    $dst = Join-Path $OutDir $b.dir
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    $n = 0
    if ($sub) {
        Get-ChildItem -LiteralPath $sub.FullName -File | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $dst $_.Name) -Force
            $n++
        }
    }
    Write-Host ("    exit={0}  产物={1} -> {2}" -f $code, $n, $b.dir)
    if ($b.name -eq 'AudioClip' -and $n -lt 100) {
        Write-Host "    [提示] 音频导出数偏少：本作音频可能是 FSB5(FMOD) 容器，" -ForegroundColor Yellow
        Write-Host "           请用 _as_audio_collect2.py 做多轮分组累积。" -ForegroundColor Yellow
    }
}

Write-Host "`n==== 汇总 ===="
Get-ChildItem -LiteralPath $OutDir -Directory | Where-Object { $_.Name -notlike '_raw_*' } | ForEach-Object {
    $c = (Get-ChildItem -LiteralPath $_.FullName -File).Count
    $mb = (Get-ChildItem -LiteralPath $_.FullName -File | Measure-Object Length -Sum).Sum / 1MB
    "{0,-22} {1,6} 个文件  {2,9:N1} MB" -f $_.Name, $c, $mb
}
Write-Host "`n验收（务必跑，解包没报错 != 成功）："
Write-Host "  python _verify_images.py `"$OutDir`""
if (-not $SkipAudio) { Write-Host "  python _verify_audio.py `"$OutDir`" .wav" }
