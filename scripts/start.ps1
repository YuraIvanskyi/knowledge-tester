# One-click start: packages, backup, database update, network check, then the server.
# Normally run by double-clicking Start.cmd in the program folder.
# Usage: scripts\start.ps1 [-Port 8000] [-NoBrowser] [-NoPrompt]
#   -NoBrowser  do not open the browser on this computer
#   -NoPrompt   never ask questions (the firewall question is skipped)
# This file is UTF-8 with a BOM: Windows PowerShell 5.1 needs it to read the Ukrainian text.
param(
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$NoPrompt
)

# "Continue", not "Stop": in Windows PowerShell 5.1 a native program that writes to stderr
# (uv does, for progress) would otherwise end the script. Exit codes are checked by hand.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Say([string]$Text, [string]$Color = "Gray") { Write-Host $Text -ForegroundColor $Color }
function Fail([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    exit 1
}
function Test-Quiet([string]$CommandLine) {
    # Run through cmd so that nothing printed (stdout or stderr) reaches PowerShell.
    cmd /c "$CommandLine >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

Say "Knowledge Tester: запуск" Cyan

# --- 1. uv (the package manager) ------------------------------------------------------------
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uv = @("uv")
} else {
    if (-not (Test-Quiet "python --version")) {
        Fail ("Не знайдено Python. Встановіть Python 3.12 або новіший з https://www.python.org/downloads/ " +
              "(під час встановлення позначте «Add python.exe to PATH») і запустіть цей файл ще раз.")
    }
    if (-not (Test-Quiet "python -m uv --version")) {
        Say "Встановлюю uv (потрібен інтернет, лише першого разу)..."
        python -m pip install --user --quiet uv
        if (-not (Test-Quiet "python -m uv --version")) {
            Fail "Не вдалося встановити uv. Перевірте інтернет і спробуйте ще раз, або встановіть вручну: python -m pip install uv"
        }
    }
    $uv = @("python", "-m", "uv")
}
function Invoke-Uv {
    $rest = @($uv | Select-Object -Skip 1)
    & $uv[0] @rest @args
}

# --- 2. keep the environment out of synced folders -----------------------------------------
# A virtual environment is thousands of small files: OneDrive and friends would sync them all.
if (-not $env:UV_PROJECT_ENVIRONMENT -and $root -match "(?i)\\(OneDrive|Dropbox|Google Drive|GoogleDrive|My Drive)") {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "KnowledgeTester\venv"
}

# --- 3. packages ----------------------------------------------------------------------------
# --inexact: never remove what a developer installed on top (test tools).
Say "Перевіряю пакети..."
Invoke-Uv sync --extra xlsx --no-dev --inexact --quiet
if ($LASTEXITCODE -ne 0) {
    Invoke-Uv run --no-sync python -c "import django, waitress, segno, fpdf"
    if ($LASTEXITCODE -ne 0) {
        Fail "Не вдалося встановити пакети. Для першого запуску потрібен інтернет. Підключіться і запустіть ще раз."
    }
    Say "Не вдалося оновити пакети (немає інтернету?). Запускаю з уже встановленими." Yellow
}

# --- 4. is it already running? --------------------------------------------------------------
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $answer = ""
    try { $answer = (Invoke-WebRequest "http://localhost:$Port/healthz" -UseBasicParsing -TimeoutSec 3).Content } catch { }
    if ($answer -eq "ok") {
        Say "Програма вже запущена в іншому вікні. Відкриваю її в браузері." Green
        if (-not $NoBrowser) { Start-Process "http://localhost:$Port/teach/" }
        exit 0
    }
    Fail "Порт $Port зайнятий іншою програмою. Закрийте її або запустіть так: scripts\start.ps1 -Port 8001"
}

# --- 5. backup, then database update --------------------------------------------------------
Invoke-Uv run --no-sync manage.py backup --reason start --quiet
if ($LASTEXITCODE -ne 0) {
    Say "Увага: не вдалося зробити резервну копію перед запуском (див. повідомлення вище)." Yellow
}
Invoke-Uv run --no-sync manage.py migrate --no-input --verbosity 0
if ($LASTEXITCODE -ne 0) { Fail "Не вдалося оновити базу даних (див. повідомлення вище). Програму не запущено." }

# --- 6. can phones reach this computer? -----------------------------------------------------
function Test-FirewallRule {
    $rules = Get-NetFirewallRule -DisplayName "Knowledge Tester*" -ErrorAction SilentlyContinue |
        Where-Object { $_.Enabled -eq "True" -and $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" }
    foreach ($rule in $rules) {
        $ports = ($rule | Get-NetFirewallPortFilter).LocalPort
        if ($ports -contains "$Port" -or $ports -contains "Any") { return $true }
    }
    return $false
}
function Get-PublicNetworks {
    @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq "Public" -and $_.IPv4Connectivity -ne "Disconnected" })
}

$dataDir = $env:KT_DATA_DIR
if (-not $dataDir) { $dataDir = Join-Path $env:LOCALAPPDATA "KnowledgeTester" }
$skipMarker = Join-Path $dataDir "skip-network-setup"

$ruleMissing = -not (Test-FirewallRule)
$public = Get-PublicNetworks
if ($ruleMissing -or $public.Count -gt 0) {
    Write-Host ""
    if ($ruleMissing) { Say "Брандмауер Windows ще не має правила для порту ${Port}: телефони учнів можуть не підключитися." Yellow }
    foreach ($net in $public) {
        Say "Мережа «$($net.Name)» позначена як публічна: Windows не пускає до комп'ютера інші пристрої з такої мережі." Yellow
    }
    if ($NoPrompt -or (Test-Path $skipMarker)) {
        Say "Щоб виправити, запустіть: scripts\allow-phones.ps1 -Port $Port" Yellow
    } else {
        Say "Виправити зараз? Windows попросить дозвіл адміністратора."
        if ($public.Count -gt 0) {
            Say "Буде додано правило брандмауера, а цю мережу позначено як приватну (робіть так лише в мережі, якій довіряєте: вдома або в класі)."
        }
        $reply = Read-Host "Введіть Y (так) або N (ні, більше не питати)"
        if ($reply -match "^(y|Y|т|Т|д|Д)") {
            $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\allow-phones.ps1`"", "-Port", "$Port")
            if ($public.Count -gt 0) { $arguments += "-MakePrivate" }
            try {
                Start-Process powershell -Verb RunAs -Wait -ArgumentList $arguments
            } catch {
                Say "Дозвіл не надано, нічого не змінено." Yellow
            }
            if (Test-FirewallRule) { Say "Правило брандмауера додано." Green }
            else { Say "Правило не додано. Спробувати ще раз: scripts\allow-phones.ps1 -Port $Port" Yellow }
        } else {
            New-Item -ItemType File -Path $skipMarker -Force | Out-Null
            Say "Гаразд. Якщо телефони не підключатимуться: scripts\allow-phones.ps1 -Port $Port"
        }
    }
    Write-Host ""
}

# --- 7. serve -------------------------------------------------------------------------------
Say "Запускаю сервер. Не закривайте це вікно під час уроку; щоб зупинити, натисніть Ctrl+C." Green
$serveArgs = @("run", "--no-sync", "manage.py", "serve", "--port", "$Port")
if (-not $NoBrowser) { $serveArgs += "--open" }
Invoke-Uv @serveArgs
exit $LASTEXITCODE
