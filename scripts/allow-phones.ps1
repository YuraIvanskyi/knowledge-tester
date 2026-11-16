# Let phones on the local network reach Knowledge Tester: adds a Windows Firewall rule for the
# port and, with -MakePrivate, marks the networks this computer is connected to as private.
# Needs administrator rights; it asks for them itself. Safe to run more than once.
# Usage: scripts\allow-phones.ps1 [-Port 8000] [-MakePrivate]
# To undo: Remove-NetFirewallRule -DisplayName "Knowledge Tester (8000)"
# This file is UTF-8 with a BOM: Windows PowerShell 5.1 needs it to read the Ukrainian text.
param(
    [int]$Port = 8000,
    [switch]$MakePrivate
)

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Port", "$Port")
    if ($MakePrivate) { $arguments += "-MakePrivate" }
    try {
        Start-Process powershell -Verb RunAs -Wait -ArgumentList $arguments
    } catch {
        Write-Host "Дозвіл адміністратора не надано, нічого не змінено." -ForegroundColor Yellow
        exit 1
    }
    exit 0
}

$name = "Knowledge Tester ($Port)"
$failed = $false

if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
    Write-Host "Правило брандмауера «$name» вже є."
} else {
    try {
        # Private and Domain only: on a network marked public the port stays closed.
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Private, Domain -ErrorAction Stop | Out-Null
        Write-Host "Додано правило брандмауера «$name» (вхідні з'єднання на порт $Port у приватних мережах)." -ForegroundColor Green
    } catch {
        Write-Host "Не вдалося додати правило: $($_.Exception.Message)" -ForegroundColor Red
        $failed = $true
    }
}

if ($MakePrivate) {
    $public = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq "Public" -and $_.IPv4Connectivity -ne "Disconnected" })
    foreach ($net in $public) {
        try {
            Set-NetConnectionProfile -InterfaceIndex $net.InterfaceIndex -NetworkCategory Private -ErrorAction Stop
            Write-Host "Мережу «$($net.Name)» позначено як приватну." -ForegroundColor Green
        } catch {
            Write-Host "Не вдалося змінити мережу «$($net.Name)»: $($_.Exception.Message)" -ForegroundColor Red
            $failed = $true
        }
    }
}

if ($failed) {
    Write-Host ""
    Read-Host "Натисніть Enter, щоб закрити"
    exit 1
}
Start-Sleep -Seconds 2
exit 0
