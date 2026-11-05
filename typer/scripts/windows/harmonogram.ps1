# Typer na Windows: harmonogram jak scripts/crontab.txt (czas lokalny komputera = Europe/Warsaw).
#   powershell -ExecutionPolicy Bypass -File typer\scripts\windows\harmonogram.ps1          instaluje zadania
#   powershell -ExecutionPolicy Bypass -File typer\scripts\windows\harmonogram.ps1 -Usun    usuwa zadania
# Zadania dzialaja tylko, gdy komputer jest wlaczony i jestes zalogowany (bez hasla w skrypcie).
# UWAGA: napisane bez mozliwosci uruchomienia na Windows w sesji budowy. Po instalacji:
#   schtasks /query /tn "Typer\co15" /fo LIST   oraz podglad typer\logs\cron.log
param([switch]$Usun)
$Run = Join-Path $PSScriptRoot "run.ps1"
$Tr = { param($z) "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Run`" -Zadanie $z" }
$Def = @(
    @{ n = "Typer\rano";    a = @("/sc", "daily", "/st", "07:00");                     z = "rano" },
    @{ n = "Typer\co15";    a = @("/sc", "minute", "/mo", "15");                        z = "co15" },
    @{ n = "Typer\noc";     a = @("/sc", "daily", "/st", "02:00");                     z = "noc" },
    @{ n = "Typer\tydzien"; a = @("/sc", "weekly", "/d", "MON", "/st", "06:00");       z = "tydzien" },
    @{ n = "Typer\miesiac"; a = @("/sc", "monthly", "/d", "1", "/st", "05:00");        z = "miesiac" }
)
foreach ($d in $Def) {
    if ($Usun) { schtasks /delete /tn $d.n /f; continue }
    $cmd = & $Tr $d.z
    if ($cmd.Length -gt 261) { Write-Error "Za dluga sciezka do run.ps1 dla schtasks (limit 261 znakow): $cmd"; exit 1 }
    schtasks /create /f /tn $d.n /tr $cmd @($d.a)
}
if (-not $Usun) { foreach ($d in $Def) { schtasks /query /tn $d.n /fo LIST | Select-String "TaskName|Next Run|Nastepne|Status" } }
