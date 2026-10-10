# Manual fallback: wakes WSL2 (which starts the bot) and reports whether the Signal side came up.
Write-Host "Starting WSL2 (Ubuntu)..." -ForegroundColor Cyan
& "$env:LOCALAPPDATA\OpenClaw\openclaw-keepalive-watchdog.ps1"

Write-Host "Waiting for the bot to come up (up to a minute)..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    $result = wsl -d Ubuntu -- bash -lc "curl -s -m 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/check 2>/dev/null"
    if ($result -eq "200") { $ok = $true; break }
    Start-Sleep -Seconds 2
}

if ($ok) {
    Write-Host "`nThe bot is up." -ForegroundColor Green
} else {
    Write-Host "`nWSL2 started, but the Signal side isn't answering yet. Give it another minute, then message the bot." -ForegroundColor Yellow
    Write-Host "If the bot replies, ignore this message - this check is sometimes wrong." -ForegroundColor Yellow
    wsl -d Ubuntu -- bash -lc "systemctl --user status openclaw-gateway.service --no-pager | head -8"
}
Write-Host "`nPress any key to close..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
