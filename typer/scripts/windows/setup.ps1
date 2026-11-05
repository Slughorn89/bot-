# Typer na Windows: instalacja (raz). Uruchom w katalogu repo:
#   powershell -NoProfile -ExecutionPolicy Bypass -File typer\scripts\windows\setup.ps1
# Wymaga Pythona 3.13 (python.org, zaznacz "Add to PATH" albo uzyj launchera py).
# UWAGA: napisane bez mozliwosci uruchomienia na Windows w sesji budowy.
$ErrorActionPreference = "Continue"
function Sprawdz($co) { if ($LASTEXITCODE -ne 0) { Write-Error "${co}: blad (kod $LASTEXITCODE)"; exit 1 } }
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
if (-not (Test-Path ".venv")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.13 -m venv .venv } else { python -m venv .venv }
    Sprawdz "tworzenie .venv (zainstaluj Python 3.13 z python.org)"
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip; Sprawdz "pip"
& $Py -m pip install -r requirements.txt; Sprawdz "instalacja zaleznosci"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Utworzono .env: wpisz API_FOOTBALL_KEY (i opcjonalnie ODDS_API_KEY, N8N_WEBHOOK_URL, LLM_*)."
}
& $Py -m alembic upgrade head; Sprawdz "migracje bazy"
& $Py -m pytest -q -m "not slow"
if ($LASTEXITCODE -ne 0) { Write-Error "Testy nie przeszly, nie instaluj harmonogramu."; exit 1 }
Write-Host "OK. Sprawdz koszt zapytan:  .venv\Scripts\python.exe cli.py lineups --dry-run"
Write-Host "Potem harmonogram:          powershell -ExecutionPolicy Bypass -File scripts\windows\harmonogram.ps1"
