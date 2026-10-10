# Run ONCE from an elevated PowerShell (right-click PowerShell > Run as administrator):
#   powershell -ExecutionPolicy Bypass -File .\setup-autostart.ps1
# Registers three hidden scheduled tasks that keep WSL2 (and so the bot) running,
# and puts a "Start OpenClaw" shortcut on the Desktop. Safe to re-run.

$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this from an elevated PowerShell (Run as administrator)." -ForegroundColor Red; exit 1
}

# Stable home for the scripts, so moving/deleting the kit folder doesn't break the tasks.
$dir = "$env:LOCALAPPDATA\OpenClaw"
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item "$PSScriptRoot\openclaw-keepalive-watchdog.ps1", "$PSScriptRoot\start-openclaw.ps1" $dir -Force
$watchdog = "$dir\openclaw-keepalive-watchdog.ps1"
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$psArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdog`""

# 1. Boot WSL at logon and startup. Both triggers: Fast Startup turns "shut down" into hibernate.
$a = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wsl.exe" -Argument "-d Ubuntu -- true"
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -Hidden
Register-ScheduledTask -TaskName "OpenClaw Gateway" -Action $a -Trigger (New-ScheduledTaskTrigger -AtLogOn),(New-ScheduledTaskTrigger -AtStartup) -Settings $s -User "$env:USERNAME" -RunLevel Highest -Force | Out-Null

# 2. Safety net: every 30 minutes, make sure the keepalive client is still there.
$a = New-ScheduledTaskAction -Execute $ps -Argument $psArgs
$t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName "OpenClaw Keepalive" -Action $a -Trigger $t -Settings $s -User "$env:USERNAME" -RunLevel Highest -Force | Out-Null

# 3. Run the same check the moment Windows wakes from sleep (Kernel-Power event 507).
$tc = Get-CimClass -Namespace ROOT\Microsoft\Windows\TaskScheduler -ClassName MSFT_TaskEventTrigger
$t = New-CimInstance -CimClass $tc -ClientOnly -Property @{
    Subscription = "<QueryList><Query Id='0' Path='System'><Select Path='System'>*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=507]]</Select></Query></QueryList>"
    Enabled = $true
}
$s = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "OpenClaw Wake Watchdog" -Action $a -Trigger $t -Settings $s -User "$env:USERNAME" -RunLevel Highest -Force | Out-Null

Start-ScheduledTask -TaskName "OpenClaw Keepalive"

# Desktop shortcut for the manual fallback.
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Start OpenClaw.lnk")
$lnk.TargetPath = $ps
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$dir\start-openclaw.ps1`""
$lnk.Save()

Get-ScheduledTask -TaskName "OpenClaw*" | Format-Table TaskName, State -AutoSize
Write-Host "Done. Autostart is set up, and 'Start OpenClaw' is on your Desktop." -ForegroundColor Green
