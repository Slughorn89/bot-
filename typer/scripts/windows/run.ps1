# Typer na Windows: odpowiednik scripts/run.sh dla Harmonogramu zadan.
# Uzycie:  powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 -Zadanie co15
#          powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 -Polecenie "predict --lead-minutes 90"
# Kazdy krok loguje start/koniec/blad do logs\cron.log; blad = wpis w live\alerts.json (trafia do raportu).
# UWAGA: napisane bez mozliwosci uruchomienia na Windows w sesji budowy. Pierwszy raz odpal recznie.
param(
    [ValidateSet("rano", "co15", "noc", "tydzien", "miesiac")] [string]$Zadanie,
    [string]$Polecenie
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # ...\typer
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs"), (Join-Path $Root "live") | Out-Null
$Log = Join-Path $Root "logs\cron.log"

$Zadania = @{
    "rano"    = @("fetch", "snapshot")
    "co15"    = @("snapshot", "lineups --window 90", "predict --lead-minutes 90",
                  "predict --lead-minutes 90 --variant lineup")
    "noc"     = @("settle", "report --send")
    "tydzien" = @("learn")
    "miesiac" = @("backtest --compare online+cal,online+blend+cal")
}

function Ts { (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC" }

function Krok([string]$cmd) {
    Add-Content $Log "$(Ts) START $cmd"
    $argv = $cmd -split " "
    # wyjscie przez Out-String + Add-Content: jedno kodowanie logu (w PS 5.1 *>> pisze UTF-16)
    $out = & $Py cli.py @argv 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($out) { Add-Content $Log $out.TrimEnd() }
    if ($code -eq 0) { Add-Content $Log "$(Ts) OK $cmd"; return $true }
    Add-Content $Log "$(Ts) BLAD($code) $cmd"
    # kod 1/2 z backtest/learn to werdykt, nie awaria
    $werdykt = ($argv[0] -in @("backtest", "learn")) -and ($code -le 2)
    if (-not $werdykt) {
        $null = & $Py -c "from typer.pipeline.daily import alert; alert('zadanie $cmd zakonczone kodem $code')" 2>&1
    }
    return $werdykt
}

$kroki = if ($Polecenie) { @($Polecenie) } elseif ($Zadanie) { $Zadania[$Zadanie] } else {
    Write-Error "Podaj -Zadanie (rano|co15|noc|tydzien|miesiac) albo -Polecenie '...'"; exit 2 }
foreach ($k in $kroki) {
    if (-not (Krok $k)) { exit 1 }    # jak && w crontabie: blad przerywa lancuch
}
exit 0
