param([string]$ItemName, [long]$Hwnd)
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
if (-not $item) { Write-Output 'NOITEM'; exit 1 }

$r = $item.Current.BoundingRectangle
Write-Output ('RECT {0} {1} {2} {3}' -f [int]$r.X, [int]$r.Y, [int]($r.X + $r.Width), [int]($r.Y + $r.Height))
