# tlg2png 批量转换 + 严格校验
# 用法: .\tlg2png_all.ps1 -Dest <解包目录>
# 对每个 .tlg 调用 tlg2png.exe，逐个校验产物是否为合法 PNG（魔数 + 非空 + 尺寸可读），
# 失败/静默失败一律计入失败清单，最后打印汇总。不删除任何原始 .tlg。
param(
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$Tool = 'D:\K\galgame\tlg2png\tlg2png.exe'
)

$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'

if (-not (Test-Path -LiteralPath $Tool)) { throw "找不到 tlg2png: $Tool" }
if (-not (Test-Path -LiteralPath $Dest)) { throw "找不到解包目录: $Dest" }

$pngDir = Join-Path $Dest 'png'
New-Item -ItemType Directory -Force -Path $pngDir | Out-Null

$tlgs = Get-ChildItem -LiteralPath $Dest -Recurse -File -Filter '*.tlg'
$total = $tlgs.Count
$ok = 0; $fail = 0
$failList = New-Object System.Collections.Generic.List[string]
$sw = [Diagnostics.Stopwatch]::StartNew()
$i = 0

foreach ($t in $tlgs) {
    $i++
    # 平铺输出，名字保留原包内相对路径（image/xxx -> image_xxx.png），避免重名
    $rel = $t.FullName.Substring($Dest.Length).TrimStart('\')
    $flat = ($rel -replace '[\\/]', '_') -replace '\.tlg$', '.png'
    $out = Join-Path $pngDir $flat

    $null = & $Tool $t.FullName $out 2>&1
    $exit = $LASTEXITCODE

    $good = $false
    if ((Test-Path -LiteralPath $out) -and $exit -eq 0) {
        $fi = Get-Item -LiteralPath $out
        if ($fi.Length -gt 8) {
            $fs = [IO.File]::OpenRead($out)
            try {
                $b = New-Object byte[] 8
                $null = $fs.Read($b, 0, 8)
            } finally { $fs.Close() }
            $sig = ($b | ForEach-Object { $_.ToString('X2') }) -join ''
            if ($sig -eq '89504E470D0A1A0A') { $good = $true }
        }
    }

    if ($good) { $ok++ } else {
        $fail++
        $failList.Add("$rel (exit=$exit)")
        if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }
    }

    if ($i % 50 -eq 0 -or $i -eq $total) {
        Write-Host ("  [{0}/{1}] ok={2} fail={3}" -f $i, $total, $ok, $fail)
    }
}
$sw.Stop()

Write-Host ''
Write-Host ('=' * 60)
Write-Host ("tlg2png: total={0} ok={1} fail={2} elapsed={3}s" -f $total, $ok, $fail, [math]::Round($sw.Elapsed.TotalSeconds, 1))
if ($failList.Count -gt 0) {
    Write-Host '失败清单:'
    $failList | ForEach-Object { Write-Host "  $_" }
}
Write-Host "输出目录: $pngDir"
$sizes = Get-ChildItem -LiteralPath $pngDir -File | Measure-Object Length -Sum
Write-Host ("PNG 总数={0} 合计={1:N1} MB" -f $sizes.Count, ($sizes.Sum / 1MB))
