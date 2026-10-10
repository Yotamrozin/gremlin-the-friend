# Keeps one hidden "wsl -- sleep infinity" client attached so WSL2 doesn't shut the
# distro (and the bot) down. Run by the "OpenClaw Keepalive" and "OpenClaw Wake Watchdog" tasks.
$existing = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'sleep infinity' }
if (-not $existing) {
    Start-Process -FilePath "$env:WINDIR\System32\wsl.exe" -ArgumentList "-d Ubuntu -- sleep infinity" -WindowStyle Hidden
}
