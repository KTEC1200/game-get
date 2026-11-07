param([string]$ItemName, [long]$Hwnd, [switch]$Invoke, [switch]$Fuzzy)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DPIA {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
}
"@
[DPIA]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 100
Write-Output ('SCR {0} {1}' -f [DPIA]::GetSystemMetrics(0), [DPIA]::GetSystemMetrics(1))
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$target = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
if (-not $target) { Write-Output 'NOWINDOW'; exit 1 }

$nameCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $ItemName)
$item = $target.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nameCond)
if (-not $item -and $Fuzzy) {
    $all = $target.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        $n = $e.Current.Name
        if ($n -and $n.Replace('&', '').Trim() -like "*$ItemName*") { $item = $e; break }
    }
}
if (-not $item) {
    Write-Output 'NOITEM'
    if ($Fuzzy) {
        $all = $target.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
        $i = 0
        foreach ($e in $all) {
            if ($e.Current.Name -and $i -lt 30) {
                Write-Output ('CTRL {0}|{1}' -f $e.Current.ControlType.ProgrammaticName, $e.Current.Name)
                $i++
            }
        }
    }
    exit 1
}

Write-Output ('ITEM {0}|{1}' -f $item.Current.ControlType.ProgrammaticName, $item.Current.Name)
$r = $item.Current.BoundingRectangle
Write-Output ('RECT {0} {1} {2} {3}' -f [int]$r.X, [int]$r.Y, [int]($r.X + $r.Width), [int]($r.Y + $r.Height))

if ($Invoke) {
    try {
        $ip = $item.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $ip.Invoke()
        Write-Output 'INVOKED'
        exit 0
    } catch { }
    try {
        $tp = $item.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        $tp.Toggle()
        Write-Output 'TOGGLED'
        Write-Output ('TOGGLESTATE {0}' -f $tp.Current.ToggleState)
        exit 0
    } catch { }
    Write-Output 'NO_PATTERN'
}
exit 0
