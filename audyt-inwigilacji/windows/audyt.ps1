<#
.SYNOPSIS
  Audyt inwigilacji dla Windows. Faza czytania: niczego nie usuwa i nie zmienia.

.DESCRIPTION
  Zbiera dane o autostarcie, usługach, zadaniach, procesach, sieci, certyfikatach,
  kamerze i mikrofonie, programach, rozszerzeniach przeglądarek, kontach, zdalnym
  dostępie, Defenderze, dzienniku zdarzeń i kanałach dostępu do telefonu.
  Surowe wyniki trafiają do raw\, a na końcu powstaje RAPORT.md i raport.html
  z pierwszą oceną (POTWIERDZONE / PODEJRZANE / DO WYJAŚNIENIA / CZYSTO).
  Dane zostają na tym komputerze. Jedyny ruch sieciowy to opcjonalne pobranie
  publicznej listy domen stalkerware z GitHuba (tylko za zgodą).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File audyt.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File audyt.ps1 -Out C:\audyt -PobierzIOC -BezPytan
#>
[CmdletBinding()]
param(
    [string]$Out,
    [switch]$PobierzIOC,
    [switch]$BezPytan,
    [switch]$NieOtwieraj
)

Set-StrictMode -Off
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

# ============================================================ podstawy

$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:IsAdmin = $false
$script:UserName = $env:USERNAME
$script:UserSid = ''
try {
    $wid = [Security.Principal.WindowsIdentity]::GetCurrent()
    $script:IsAdmin = (New-Object Security.Principal.WindowsPrincipal($wid)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $script:UserName = $wid.Name
    $script:UserSid = $wid.User.Value
} catch {}

$script:WinDir = ([string]$env:windir).TrimEnd('\')
$script:Sys32 = Join-Path $script:WinDir 'System32'
$script:ProgData = ([string]$env:ProgramData).TrimEnd('\').ToLowerInvariant()
$script:Since = (Get-Date).AddDays(-30)
$script:SelfPid = $PID

if (-not $Out) {
    $Out = Join-Path $env:USERPROFILE ('audyt-inwigilacji\' + (Get-Date -Format 'yyyy-MM-dd_HHmm'))
    if ($script:IsAdmin) { $Out += '_admin' }
}
$script:OutDir = $Out
$script:RawDir = Join-Path $Out 'raw'
foreach ($dir in @($Out, $script:RawDir, (Join-Path $Out 'skrypty'), (Join-Path $Out 'kwarantanna'), (Join-Path $Out 'kopia-rejestru'))) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}
try { Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $Out 'skrypty') -Force } catch {}

# Poprzedni audyt w tym samym trybie (zwykły / admin), żeby pokazać, co doszło od tamtej pory
$script:PrevDir = $null
try {
    $auditRoot = Split-Path -Parent $script:OutDir
    $cands = @(Get-ChildItem -LiteralPath $auditRoot -Directory | Where-Object {
            $_.FullName -ne $script:OutDir -and ($_.Name -like '*_admin') -eq $script:IsAdmin -and (Test-Path -LiteralPath (Join-Path $_.FullName 'raw\_status.json'))
        } | Sort-Object Name -Descending)
    if ($cands.Count -gt 0) { $script:PrevDir = $cands[0].FullName }
} catch {}

$script:D = @{}
$script:Status = New-Object System.Collections.ArrayList
$script:Note = ''
$script:SigCache = @{}

function Format-Date($d) {
    if ($d -is [datetime]) { return $d.ToString('yyyy-MM-dd HH:mm') }
    if ($d) { return [string]$d }
    return $null
}

function Limit-Text([string]$t, [int]$n) {
    if (-not $t) { return $t }
    if ($t.Length -le $n) { return $t }
    return $t.Substring(0, $n) + '...'
}

function Save-Raw([string]$Name, $Data) {
    $script:D[$Name] = $Data
    $json = ConvertTo-Json -InputObject $Data -Depth 6
    if ($null -eq $json) { $json = 'null' }
    [IO.File]::WriteAllText((Join-Path $script:RawDir ($Name + '.json')), $json, $script:Utf8)
}

function Save-Text([string]$Name, [string]$Text) {
    [IO.File]::WriteAllText((Join-Path $script:RawDir ($Name + '.txt')), $Text, $script:Utf8)
}

function Add-Note([string]$t) {
    if ($script:Note) { $script:Note += '; ' }
    $script:Note += $t
}

function Invoke-Test {
    param([string]$Name, [string]$Opis, [scriptblock]$Block, [switch]$Admin)
    $t0 = Get-Date
    $script:Note = ''
    $wynik = 'OK'
    $msg = ''
    Write-Host ('  [{0,2}] {1}...' -f ($script:Status.Count + 1), $Opis) -NoNewline
    if ($Admin -and -not $script:IsAdmin) {
        $wynik = 'POMINIĘTO: brak uprawnień'
    } else {
        try { & $Block } catch { $wynik = 'BŁĄD'; $msg = $_.Exception.Message }
    }
    if ($wynik -eq 'OK' -and $script:Note) { $msg = $script:Note }
    $sek = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    [void]$script:Status.Add([pscustomobject]@{
        test = $Name; opis = $Opis; wynik = $wynik; komunikat = $msg
        czas_s = $sek; wymaga_admina = [bool]$Admin
        zakonczono = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    })
    $kolor = 'Green'
    if ($wynik -ne 'OK') { $kolor = 'Yellow' }
    Write-Host (' {0} ({1} s)' -f $wynik, $sek) -ForegroundColor $kolor
}

function Get-RegValues([string]$Path) {
    $res = @()
    if (-not (Test-Path -LiteralPath $Path)) { return $res }
    $k = Get-Item -LiteralPath $Path
    if (-not $k) { return $res }
    $clean = $Path -replace '^Microsoft\.PowerShell\.Core\\Registry::', ''
    foreach ($n in $k.GetValueNames()) {
        $v = $k.GetValue($n, $null, 'DoNotExpandEnvironmentNames')
        if ($v -is [byte[]]) { $v = Limit-Text ((@($v) | ForEach-Object { $_.ToString('X2') }) -join '') 200 }
        elseif ($v -is [array]) { $v = $v -join ' | ' }
        $res += [pscustomobject]@{ klucz = $clean; nazwa = $n; wartosc = [string]$v }
    }
    return $res
}

function Get-RegTree([string]$Path) {
    $res = @(Get-RegValues $Path)
    foreach ($k in Get-ChildItem -LiteralPath $Path -Recurse) { $res += @(Get-RegValues $k.PSPath) }
    return $res
}

# Wyciąga ścieżkę pliku wykonywalnego z polecenia (cudzysłowy, zmienne, \SystemRoot\ itp.)
function Resolve-ExePath([string]$Cmd) {
    if (-not $Cmd) { return $null }
    $c = [Environment]::ExpandEnvironmentVariables($Cmd.Trim())
    $c = $c -replace '^\\\?\?\\', ''
    $c = $c -replace '^\\SystemRoot\\', ($script:WinDir + '\')
    $c = $c -replace '^system32\\', ($script:Sys32 + '\')
    $p = $null
    if ($c.StartsWith('"')) {
        $end = $c.IndexOf('"', 1)
        if ($end -gt 1) { $p = $c.Substring(1, $end - 1) }
    } else {
        $m = [regex]::Match($c, '^(.+?\.(exe|com|bat|cmd|ps1|vbs|vbe|js|jse|wsf|hta|dll|scr|pif|cpl|msi|jar|lnk|sys))(\s|,|$)', 'IgnoreCase')
        if ($m.Success) { $p = $m.Groups[1].Value } else { $p = ($c -split '\s+')[0] }
    }
    if (-not $p) { return $null }
    if ($p -notmatch '\\') {
        foreach ($dir in @($script:Sys32, $script:WinDir, (Join-Path $script:WinDir 'SysWOW64'))) {
            $cand = Join-Path $dir $p
            if (Test-Path -LiteralPath $cand -PathType Leaf) { return $cand }
            if ($p -notmatch '\.') {
                $cand = $cand + '.exe'
                if (Test-Path -LiteralPath $cand -PathType Leaf) { return $cand }
            }
        }
    }
    return $p
}

# Ścieżki plików podane jako argumenty (np. rundll32 C:\x\y.dll,Start)
function Get-PathsInArgs([string]$Text) {
    $res = @()
    if (-not $Text) { return $res }
    $t = [Environment]::ExpandEnvironmentVariables($Text)
    foreach ($m in [regex]::Matches($t, '([a-zA-Z]:\\[^"''<>|*?\r\n,]+?\.(dll|exe|vbs|vbe|js|jse|wsf|hta|ps1|bat|cmd|ocx|cpl|scr|jar))(?![A-Za-z0-9_])', 'IgnoreCase')) {
        $res += $m.Groups[1].Value
    }
    return $res
}

function Get-PathClass([string]$Path) {
    if (-not $Path) { return 'brak' }
    $p = $Path.ToLowerInvariant()
    if ($p -match '\\appdata\\local\\microsoft\\windowsapps\\') { return 'programfiles' }
    if ($p -match '\\appdata\\|\\temp\\|\\tmp\\|\\users\\public\\|\\downloads\\|\\desktop\\|\\\$recycle\.bin\\|\\windows\\tasks\\|\\windows\\debug\\|^[a-z]:\\perflogs\\') { return 'ryzykowna' }
    if ($script:ProgData -and $p.StartsWith($script:ProgData + '\')) { return 'ryzykowna' }
    if ($p.StartsWith($script:WinDir.ToLowerInvariant() + '\')) { return 'system' }
    if ($p -match '^[a-z]:\\program files( \(x86\))?\\') { return 'programfiles' }
    return 'inna'
}

function Get-Sig([string]$Path) {
    if (-not $Path) { return $null }
    $key = $Path.ToLowerInvariant()
    if ($script:SigCache.ContainsKey($key)) { return $script:SigCache[$key] }
    $r = $null
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        try {
            $s = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
            $signer = ''
            if ($s.SignerCertificate) { $signer = $s.SignerCertificate.Subject }
            $os = $false
            if ($s.PSObject.Properties['IsOSBinary']) { $os = [bool]$s.IsOSBinary }
            $r = [pscustomobject]@{ sciezka = $Path; status = [string]$s.Status; podpisujacy = $signer; systemowy = $os }
        } catch {
            $r = [pscustomobject]@{ sciezka = $Path; status = 'BladOdczytu'; podpisujacy = ''; systemowy = $false }
        }
    } else {
        $r = [pscustomobject]@{ sciezka = $Path; status = 'BrakPliku'; podpisujacy = ''; systemowy = $false }
    }
    $script:SigCache[$key] = $r
    return $r
}

function Test-SigOk($sig) { return ($sig -and $sig.status -eq 'Valid') }

function Get-SignerShort($sig) {
    if (-not $sig) { return 'nie sprawdzono' }
    switch ($sig.status) {
        'Valid' {
            $m = [regex]::Match([string]$sig.podpisujacy, 'CN="?([^,"]+)')
            if ($m.Success) { return ('podpisany: ' + $m.Groups[1].Value) }
            return 'podpisany'
        }
        'NotSigned' { return 'BRAK podpisu' }
        'HashMismatch' { return 'podpis USZKODZONY (plik zmieniony po podpisaniu)' }
        'BrakPliku' { return 'plik nie istnieje' }
        default { return ('podpis: ' + $sig.status) }
    }
}

function Get-Sha256([string]$Path) {
    try { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash } catch { return '' }
}

function Convert-FileTime($v) {
    if ($v -is [long] -and $v -gt 0) {
        try { return [DateTime]::FromFileTime($v).ToString('yyyy-MM-dd HH:mm:ss') } catch {}
    }
    return $null
}

# Rozmiar folderu z limitem czasu: przy ogromnych folderach wynik jest "co najmniej"
function Get-DirSize([string]$Path, [int]$MaxSec = 40) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $null }
    $total = [int64]0
    $count = 0
    $cut = $false
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $stack = New-Object System.Collections.Stack
    $stack.Push((New-Object IO.DirectoryInfo($Path)))
    while ($stack.Count -gt 0) {
        if ($sw.Elapsed.TotalSeconds -gt $MaxSec) { $cut = $true; break }
        $d = $stack.Pop()
        try {
            foreach ($f in $d.EnumerateFiles()) { $total += $f.Length; $count++ }
            foreach ($sd in $d.EnumerateDirectories()) {
                if (($sd.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { $stack.Push($sd) }
            }
        } catch {}
    }
    return [pscustomobject]@{ bajty = $total; pliki = $count; niepelne = $cut }
}

function Format-Size($b) {
    if ($null -eq $b) { return '?' }
    if ($b -ge 1GB) { return ('{0:N1} GB' -f ($b / 1GB)) }
    if ($b -ge 1MB) { return ('{0:N0} MB' -f ($b / 1MB)) }
    return ('{0:N0} KB' -f ($b / 1KB))
}

function Get-EvData($e) {
    $h = @{}
    try {
        $x = [xml]$e.ToXml()
        foreach ($d in @($x.Event.EventData.Data)) { if ($d.Name) { $h[$d.Name] = [string]$d.'#text' } }
    } catch {}
    return $h
}

# Zdarzenia: pusty wynik to nie błąd; inne błędy (np. brak dostępu) idą do notatki
function Get-Events([hashtable]$Filter, [string]$XPath, [string]$LogName, [int]$Max) {
    try {
        if ($XPath) { return @(Get-WinEvent -LogName $LogName -FilterXPath $XPath -MaxEvents $Max -ErrorAction Stop) }
        return @(Get-WinEvent -FilterHashtable $Filter -MaxEvents $Max -ErrorAction Stop)
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') {
            $ln = $LogName
            if (-not $ln -and $Filter) { $ln = [string]$Filter['LogName'] }
            Add-Note ('{0}: {1}' -f $ln, (Limit-Text $_.Exception.Message 120))
        }
        return @()
    }
}

# ============================================================ wzorce nazw

# kategoria;grupa;nazwa;regex (bez rozróżniania wielkości liter)
$tabelaWzorcow = @'
POTWIERDZONE;stalkerware;mSpy;\bmspy
POTWIERDZONE;stalkerware;FlexiSPY;flexi\s?spy
POTWIERDZONE;stalkerware;Spyrix;spyrix
POTWIERDZONE;stalkerware;Refog;\brefog
POTWIERDZONE;stalkerware;Kidlogger;kid\s?logger
POTWIERDZONE;stalkerware;SpyAgent;spy\s?agent
POTWIERDZONE;stalkerware;Spytech;spytech
POTWIERDZONE;stalkerware;Realtime-Spy;realtime[- ]?spy
POTWIERDZONE;stalkerware;Ardamax;ardamax
POTWIERDZONE;stalkerware;Revealer Keylogger;revealer\s?keylogger
POTWIERDZONE;stalkerware;Elite Keylogger;elite\s?keylogger
POTWIERDZONE;stalkerware;Actual Keylogger;actual\s?keylogger
POTWIERDZONE;stalkerware;Best Free Keylogger;best\s?free\s?keylogger
POTWIERDZONE;stalkerware;Hoverwatch;hoverwatch
POTWIERDZONE;stalkerware;Spyera;spyera
POTWIERDZONE;stalkerware;WebWatcher;web\s?watcher
POTWIERDZONE;stalkerware;pcTattletale;tattletale
POTWIERDZONE;stalkerware;Wolfeye;wolfeye
POTWIERDZONE;stalkerware;SentryPC;sentry\s?pc
POTWIERDZONE;stalkerware;iKeyMonitor;ikeymonitor
POTWIERDZONE;stalkerware;KidsGuard (ClevGuard);kidsguard|clevguard
PODEJRZANE;stalkerware;Keylogger (nazwa ogólna);keylogger
DO_WYJASNIENIA;monitoring;Teramind;teramind
DO_WYJASNIENIA;monitoring;ActivTrak;activtrak
DO_WYJASNIENIA;monitoring;Veriato;veriato|spector\s?360|spectorsoft
DO_WYJASNIENIA;monitoring;InterGuard;interguard
DO_WYJASNIENIA;monitoring;Controlio;controlio
DO_WYJASNIENIA;monitoring;Kickidler;kickidler
DO_WYJASNIENIA;monitoring;StaffCop;staffcop
DO_WYJASNIENIA;monitoring;Work Examiner;work\s?examiner
DO_WYJASNIENIA;monitoring;Clever Control;clever\s?control
DO_WYJASNIENIA;monitoring;FamiSafe;famisafe
DO_WYJASNIENIA;monitoring;Qustodio;qustodio
DO_WYJASNIENIA;monitoring;Norton Family;norton\s?family|nortonfamily
DO_WYJASNIENIA;monitoring;Kaspersky Safe Kids;safe\s?kids
POTWIERDZONE;rat;njRAT;njrat|bladabindi
POTWIERDZONE;rat;DarkComet;darkcomet
POTWIERDZONE;rat;Remcos;remcos
POTWIERDZONE;rat;AsyncRAT;asyncrat
POTWIERDZONE;rat;DcRAT;\bdcrat
POTWIERDZONE;rat;NanoCore;nanocore
POTWIERDZONE;rat;NetWire;netwire
POTWIERDZONE;rat;VenomRAT;venomrat
POTWIERDZONE;rat;XWorm;xworm
POTWIERDZONE;rat;AveMaria (Warzone RAT);avemaria|warzone\s?rat
POTWIERDZONE;rat;Quasar RAT;quasar\s?rat
POTWIERDZONE;rat;Orcus RAT;orcus\s?rat
DO_WYJASNIENIA;zdalny;NetSupport;netsupport|\bclient32\.exe
DO_WYJASNIENIA;zdalny;TeamViewer;teamviewer
DO_WYJASNIENIA;zdalny;AnyDesk;anydesk
DO_WYJASNIENIA;zdalny;RustDesk;rustdesk
DO_WYJASNIENIA;zdalny;HopToDesk;hoptodesk
DO_WYJASNIENIA;zdalny;Pulpit zdalny Chrome;chrome remote desktop|remoting_host|chromoting
DO_WYJASNIENIA;zdalny;ScreenConnect (ConnectWise);screenconnect|connectwise
DO_WYJASNIENIA;zdalny;Splashtop;splashtop
DO_WYJASNIENIA;zdalny;LogMeIn;logmein
DO_WYJASNIENIA;zdalny;GoTo (GoToAssist, GoTo Resolve);gotoassist|gotomypc|goto\s?(resolve|assist|opener)
DO_WYJASNIENIA;zdalny;Ammyy Admin;ammyy
DO_WYJASNIENIA;zdalny;Radmin;\bradmin|famatech
DO_WYJASNIENIA;zdalny;UltraVNC;ultravnc|\buvnc
DO_WYJASNIENIA;zdalny;TightVNC;tightvnc|tvnserver
DO_WYJASNIENIA;zdalny;RealVNC;realvnc
DO_WYJASNIENIA;zdalny;TigerVNC;tigervnc
DO_WYJASNIENIA;zdalny;VNC (inny);winvnc|vncserver|vnc server
DO_WYJASNIENIA;zdalny;Supremo;\bsupremo
DO_WYJASNIENIA;zdalny;AeroAdmin;aeroadmin
DO_WYJASNIENIA;zdalny;Remote Utilities;remote\s?utilities|rutserv|rfusclient
DO_WYJASNIENIA;zdalny;Zoho Assist;zoho\s?assist|zohoassist
DO_WYJASNIENIA;zdalny;DWService;dwservice|dwagent
DO_WYJASNIENIA;zdalny;MeshAgent (MeshCentral);meshagent|mesh\s?agent|meshcentral
DO_WYJASNIENIA;zdalny;Atera;\batera
DO_WYJASNIENIA;zdalny;Action1;\baction1
DO_WYJASNIENIA;zdalny;Tactical RMM;tactical\s?rmm|tacticalagent|tacticalrmm
DO_WYJASNIENIA;zdalny;NinjaOne;ninjaone|ninjarmm
DO_WYJASNIENIA;zdalny;Parsec;\bparsec
DO_WYJASNIENIA;zdalny;ngrok;\bngrok
DO_WYJASNIENIA;zdalny;UltraViewer;ultraviewer
DO_WYJASNIENIA;zdalny;ISL Online;isl\s?light|islonline
DO_WYJASNIENIA;zdalny;SimpleHelp;simplehelp|simple-help
DO_WYJASNIENIA;zdalny;Kaseya;kaseya
DO_WYJASNIENIA;zdalny;Iperius Remote;iperius\s?remote
DO_WYJASNIENIA;telefon;AirDroid;airdroid
DO_WYJASNIENIA;telefon;KDE Connect;kde\s?connect|kdeconnect
DO_WYJASNIENIA;telefon;Samsung Flow;samsung\s?flow
DO_WYJASNIENIA;telefon;Samsung Smart Switch;smart\s?switch
DO_WYJASNIENIA;telefon;scrcpy;scrcpy
DO_WYJASNIENIA;telefon;Vysor;vysor
DO_WYJASNIENIA;telefon;Dr.Fone (Wondershare);dr\.?\s?fone|drfone|mobiletrans|mirrorgo|wondershare\s?(tunesgo|mobilego)
DO_WYJASNIENIA;telefon;Tenorshare (iCareFone, UltData);tenorshare|icarefone|ultdata|4ukey|reiboot
DO_WYJASNIENIA;telefon;iMazing;imazing
DO_WYJASNIENIA;telefon;3uTools;3utools
DO_WYJASNIENIA;telefon;iMobie (AnyTrans, PhoneRescue);anytrans|phonerescue|imobie
DO_WYJASNIENIA;telefon;iMyFone;imyfone
DO_WYJASNIENIA;telefon;FonePaw / FoneLab;fonepaw|fonelab|aiseesoft
DO_WYJASNIENIA;telefon;Syncios;syncios
DO_WYJASNIENIA;telefon;CopyTrans;copytrans
DO_WYJASNIENIA;telefon;MOBILedit;mobiledit
DO_WYJASNIENIA;telefon;EaseUS MobiSaver;mobisaver
DO_WYJASNIENIA;forensic;Oxygen Forensic;oxygen\s?forensic
DO_WYJASNIENIA;forensic;Elcomsoft (Phone Breaker);elcomsoft|phone\s?breaker
DO_WYJASNIENIA;forensic;Cellebrite;cellebrite|\bufed
DO_WYJASNIENIA;forensic;Magnet Forensics;magnet\s?(axiom|acquire|forensics)
DO_WYJASNIENIA;forensic;Belkasoft;belkasoft
'@

$script:Wzorce = @()
foreach ($line in ($tabelaWzorcow -split "`r?`n")) {
    $l = $line.Trim()
    if (-not $l -or $l.StartsWith('#')) { continue }
    $parts = $l.Split(';')
    if ($parts.Count -lt 4) { continue }
    $script:Wzorce += [pscustomobject]@{ kat = $parts[0]; grupa = $parts[1]; nazwa = $parts[2]; rx = (New-Object regex($parts[3], 'IgnoreCase')) }
}

$script:GrupaOpis = @{
    stalkerware = 'Stalkerware lub keylogger'
    monitoring  = 'Program do monitorowania (firmowy lub rodzicielski)'
    rat         = 'RAT, czyli trojan zdalnego dostępu'
    zdalny      = 'Narzędzie zdalnego dostępu'
    telefon     = 'Program z dostępem do telefonu'
    forensic    = 'Narzędzie śledcze do wyciągania danych z telefonów'
}

# ============================================================ start

Write-Host ''
Write-Host 'Audyt inwigilacji: faza czytania' -ForegroundColor Cyan
Write-Host 'Sprawdzam autostart, usługi, zadania, procesy, sieć, certyfikaty, kamerę i mikrofon,'
Write-Host 'programy, rozszerzenia przeglądarek, konta, zdalny dostęp, Defendera i dostęp do telefonu.'
Write-Host 'Na tym etapie NICZEGO nie usuwam ani nie zmieniam. Dane zostają na tym komputerze.'
Write-Host ('Folder audytu: {0}' -f $script:OutDir)
if ($script:IsAdmin) { Write-Host 'Tryb: administrator (pełny audyt)' -ForegroundColor Green }
else { Write-Host 'Tryb: zwykły użytkownik. Część testów zostanie pominięta, potem uruchom wersję admin.' -ForegroundColor Yellow }
Write-Host ''

if (-not $PobierzIOC -and -not $BezPytan) {
    Write-Host 'Mogę pobrać z GitHuba publiczną listę domen stalkerware (AssoEchap/stalkerware-indicators)'
    Write-Host 'i porównać ją z pamięcią DNS. To tylko pobranie, niczego stąd nie wysyłam.'
    $odp = Read-Host 'Pobrać listę? [t/N]'
    if ($odp -match '^(t|tak|y|yes)$') { $PobierzIOC = $true }
    Write-Host ''
}

# ============================================================ testy

Invoke-Test 'system' 'Informacje o systemie' {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $cs = Get-CimInstance Win32_ComputerSystem
    $consoleUser = ''
    try {
        $ex = Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Select-Object -First 1
        if ($ex) {
            $o = Invoke-CimMethod -InputObject $ex -MethodName GetOwner
            if ($o.User) { $consoleUser = ('{0}\{1}' -f $o.Domain, $o.User) }
        }
    } catch {}
    $dsreg = ''
    try { $dsreg = (& dsregcmd.exe /status) -join "`n" } catch {}
    Save-Text 'dsregcmd' $dsreg
    Save-Raw 'system' ([pscustomobject]@{
        komputer           = $env:COMPUTERNAME
        system             = $os.Caption
        wersja             = $os.Version
        kompilacja         = $os.BuildNumber
        architektura       = $os.OSArchitecture
        powershell         = $PSVersionTable.PSVersion.ToString()
        uzytkownik         = $script:UserName
        uzytkownik_sid     = $script:UserSid
        uzytkownik_pulpitu = $consoleUser
        admin              = $script:IsAdmin
        domena             = $cs.Domain
        w_domenie          = [bool]$cs.PartOfDomain
        azure_ad           = [bool]($dsreg -match 'AzureAdJoined\s*:\s*YES')
        konto_sluzbowe     = [bool]($dsreg -match 'WorkplaceJoined\s*:\s*YES')
        producent          = $cs.Manufacturer
        model              = $cs.Model
        ram_gb             = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        ostatni_start      = (Format-Date $os.LastBootUpTime)
        data_audytu        = (Get-Date).ToString('yyyy-MM-dd HH:mm')
    })
}

Invoke-Test 'autostart' 'Autostart: rejestr, foldery Autostart, Winlogon, IFEO' {
    $runKeys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run'
    )
    # StartupApproved: pierwszy bajt nieparzysty = wyłączone w Menedżerze zadań
    $approved = @{}
    foreach ($hive in @('HKCU:\Software', 'HKLM:\SOFTWARE')) {
        foreach ($sub in @('Run', 'Run32', 'StartupFolder')) {
            $ak = $hive + '\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\' + $sub
            if (-not (Test-Path -LiteralPath $ak)) { continue }
            $k = Get-Item -LiteralPath $ak
            foreach ($n in $k.GetValueNames()) {
                $b = $k.GetValue($n)
                if ($b -is [byte[]] -and $b.Length -gt 0) { $approved[$n.ToLowerInvariant()] = (($b[0] -band 1) -eq 1) }
            }
        }
    }
    $items = New-Object System.Collections.ArrayList
    foreach ($rk in $runKeys) {
        foreach ($v in @(Get-RegValues $rk)) {
            if (-not $v -or $v.nazwa -eq '') { continue }
            $wyl = $false
            if ($approved.ContainsKey($v.nazwa.ToLowerInvariant())) { $wyl = $approved[$v.nazwa.ToLowerInvariant()] }
            [void]$items.Add([pscustomobject]@{ zrodlo = 'rejestr'; miejsce = $v.klucz; nazwa = $v.nazwa; polecenie = $v.wartosc; plik = (Resolve-ExePath $v.wartosc); wylaczony = $wyl })
        }
    }
    $sh = $null
    try { $sh = New-Object -ComObject WScript.Shell } catch {}
    foreach ($sf in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('CommonStartup'))) {
        if (-not $sf -or -not (Test-Path -LiteralPath $sf)) { continue }
        foreach ($f in Get-ChildItem -LiteralPath $sf -Force -File) {
            if ($f.Name -eq 'desktop.ini') { continue }
            $cmd = $f.FullName
            $exe = $f.FullName
            if ($f.Extension -eq '.lnk' -and $sh) {
                try {
                    $lnk = $sh.CreateShortcut($f.FullName)
                    $cmd = ('"{0}" {1}' -f $lnk.TargetPath, $lnk.Arguments).Trim()
                    $exe = $lnk.TargetPath
                } catch {}
            }
            $wyl = $false
            if ($approved.ContainsKey($f.Name.ToLowerInvariant())) { $wyl = $approved[$f.Name.ToLowerInvariant()] }
            [void]$items.Add([pscustomobject]@{ zrodlo = 'folder Autostart'; miejsce = $sf; nazwa = $f.Name; polecenie = $cmd; plik = $exe; wylaczony = $wyl })
        }
    }
    Save-Raw 'autostart' @($items)

    $special = New-Object System.Collections.ArrayList
    foreach ($wl in @('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon', 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Winlogon')) {
        foreach ($v in @(@(Get-RegValues $wl) | Where-Object { $_.nazwa -in @('Shell', 'Userinit', 'Taskman', 'AppSetup') })) {
            [void]$special.Add([pscustomobject]@{ typ = 'Winlogon'; klucz = $v.klucz; nazwa = $v.nazwa; wartosc = $v.wartosc })
        }
    }
    foreach ($ifeo in @('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Image File Execution Options')) {
        if (-not (Test-Path -LiteralPath $ifeo)) { continue }
        foreach ($k in Get-ChildItem -LiteralPath $ifeo) {
            $dbg = $k.GetValue('Debugger')
            if ($dbg) { [void]$special.Add([pscustomobject]@{ typ = 'IFEO Debugger'; klucz = ($k.Name); nazwa = $k.PSChildName; wartosc = [string]$dbg }) }
        }
    }
    $spe = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SilentProcessExit'
    if (Test-Path -LiteralPath $spe) {
        foreach ($k in Get-ChildItem -LiteralPath $spe) {
            $mp = $k.GetValue('MonitorProcess')
            if ($mp) { [void]$special.Add([pscustomobject]@{ typ = 'SilentProcessExit'; klucz = ($k.Name); nazwa = $k.PSChildName; wartosc = [string]$mp }) }
        }
    }
    foreach ($aw in @('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows')) {
        $vals = @(Get-RegValues $aw)
        $dlls = @($vals | Where-Object { $_.nazwa -eq 'AppInit_DLLs' })
        $load = @($vals | Where-Object { $_.nazwa -eq 'LoadAppInit_DLLs' })
        if ($dlls.Count -gt 0 -and $dlls[0].wartosc) {
            $lv = ''
            if ($load.Count -gt 0) { $lv = $load[0].wartosc }
            [void]$special.Add([pscustomobject]@{ typ = 'AppInit_DLLs'; klucz = $dlls[0].klucz; nazwa = ('LoadAppInit_DLLs=' + $lv); wartosc = $dlls[0].wartosc })
        }
    }
    Save-Raw 'autostart_specjalne' @($special)
}

Invoke-Test 'uslugi' 'Usługi i sterowniki' {
    $list = New-Object System.Collections.ArrayList
    foreach ($s in Get-CimInstance Win32_Service -ErrorAction Stop) {
        $exe = Resolve-ExePath $s.PathName
        $dll = $null
        if ($exe -and $exe -match '\\svchost\.exe$') {
            $base = 'HKLM:\SYSTEM\CurrentControlSet\Services\' + $s.Name
            $dll = (Get-ItemProperty -LiteralPath ($base + '\Parameters') -Name ServiceDll).ServiceDll
            if (-not $dll) { $dll = (Get-ItemProperty -LiteralPath $base -Name ServiceDll).ServiceDll }
            if ($dll) { $dll = [Environment]::ExpandEnvironmentVariables($dll) }
        }
        [void]$list.Add([pscustomobject]@{
            nazwa = $s.Name; wyswietlana = $s.DisplayName; polecenie = $s.PathName; plik = $exe
            service_dll = $dll; start = $s.StartMode; stan = $s.State; konto = $s.StartName
            klasa = (Get-PathClass $exe)
        })
    }
    Save-Raw 'uslugi' @($list)
    $drv = New-Object System.Collections.ArrayList
    foreach ($s in Get-CimInstance Win32_SystemDriver) {
        $exe = Resolve-ExePath $s.PathName
        [void]$drv.Add([pscustomobject]@{ nazwa = $s.Name; wyswietlana = $s.DisplayName; plik = $exe; start = $s.StartMode; stan = $s.State; klasa = (Get-PathClass $exe) })
    }
    Save-Raw 'sterowniki' @($drv)
}

Invoke-Test 'zadania' 'Zaplanowane zadania' {
    $list = New-Object System.Collections.ArrayList
    foreach ($t in Get-ScheduledTask -ErrorAction Stop) {
        $acts = @()
        foreach ($a in @($t.Actions)) {
            if ($null -eq $a) { continue }
            if ($a.CimClass.CimClassName -eq 'MSFT_TaskExecAction') {
                $acts += [pscustomobject]@{ typ = 'exec'; execute = $a.Execute; arguments = $a.Arguments; katalog = $a.WorkingDirectory; plik = (Resolve-ExePath $a.Execute) }
            } else {
                $acts += [pscustomobject]@{ typ = 'com'; execute = $a.ClassId; arguments = (Limit-Text ([string]$a.Data) 300); katalog = $null; plik = $null }
            }
        }
        $trig = (@(@($t.Triggers) | Where-Object { $_ } | ForEach-Object { $_.CimClass.CimClassName -replace '^MSFT_Task', '' -replace 'Trigger$', '' })) -join ', '
        [void]$list.Add([pscustomobject]@{
            nazwa = $t.TaskName; sciezka = $t.TaskPath; stan = [string]$t.State; autor = $t.Author
            zarejestrowano = [string]$t.Date; ukryte = [bool]$t.Settings.Hidden
            uzytkownik = $t.Principal.UserId; poziom = [string]$t.Principal.RunLevel
            wyzwalacze = $trig; akcje = $acts
        })
    }
    Save-Raw 'zadania' @($list)
    if (-not $script:IsAdmin) { Add-Note 'bez admina część zadań systemowych może być niewidoczna' }
}

Invoke-Test 'wmi' 'Subskrypcje WMI (ukryte wyzwalacze)' -Admin {
    $ns = 'root\subscription'
    Save-Raw 'wmi' ([pscustomobject]@{
        filtry            = @(Get-CimInstance -Namespace $ns -ClassName __EventFilter -ErrorAction Stop | Select-Object Name, Query, EventNamespace)
        konsumenci_cmd    = @(Get-CimInstance -Namespace $ns -ClassName CommandLineEventConsumer | Select-Object Name, CommandLineTemplate, ExecutablePath)
        konsumenci_skrypt = @(Get-CimInstance -Namespace $ns -ClassName ActiveScriptEventConsumer | Select-Object Name, ScriptingEngine, ScriptFileName, @{n = 'ScriptText'; e = { Limit-Text $_.ScriptText 500 } })
        powiazania        = @(Get-CimInstance -Namespace $ns -ClassName __FilterToConsumerBinding | Select-Object @{n = 'Filtr'; e = { [string]$_.Filter.Name } }, @{n = 'Konsument'; e = { [string]$_.Consumer.Name } })
    })
}

Invoke-Test 'procesy' 'Działające procesy' {
    $list = New-Object System.Collections.ArrayList
    foreach ($p in Get-CimInstance Win32_Process -ErrorAction Stop) {
        [void]$list.Add([pscustomobject]@{
            pid = [int]$p.ProcessId; ppid = [int]$p.ParentProcessId; nazwa = $p.Name
            plik = $p.ExecutablePath; linia = (Limit-Text $p.CommandLine 1000); start = (Format-Date $p.CreationDate)
        })
    }
    Save-Raw 'procesy' @($list)
    if (-not $script:IsAdmin) { Add-Note 'bez admina nie widać ścieżek części procesów systemowych' }
}

Invoke-Test 'siec_polaczenia' 'Połączenia sieciowe i porty nasłuchujące' {
    $pmap = @{}
    foreach ($p in @($script:D['procesy'])) { if ($p) { $pmap[[int]$p.pid] = $p } }
    $list = New-Object System.Collections.ArrayList
    $conns = $null
    try { $conns = @(Get-NetTCPConnection -ErrorAction Stop) } catch { $conns = $null }
    if ($conns) {
        foreach ($c in $conns) {
            $st = [string]$c.State
            if ($st -ne 'Established' -and $st -ne 'Listen') { continue }
            $pp = $pmap[[int]$c.OwningProcess]
            $pn = ''; $pf = ''
            if ($pp) { $pn = $pp.nazwa; $pf = $pp.plik }
            [void]$list.Add([pscustomobject]@{ stan = $st; lokalny = $c.LocalAddress; lport = [int]$c.LocalPort; zdalny = $c.RemoteAddress; zport = [int]$c.RemotePort; pid = [int]$c.OwningProcess; proces = $pn; plik = $pf })
        }
    } else {
        Add-Note 'użyto netstat zamiast Get-NetTCPConnection'
        foreach ($line in @(& netstat.exe -ano -p TCP)) {
            $cols = ($line.Trim() -split '\s+')
            if ($cols.Count -lt 5 -or $cols[0] -ne 'TCP') { continue }
            $li = $cols[1].LastIndexOf(':'); $ri = $cols[2].LastIndexOf(':')
            $procId = [int]$cols[4]
            $pp = $pmap[$procId]
            $pn = ''; $pf = ''
            if ($pp) { $pn = $pp.nazwa; $pf = $pp.plik }
            $st = 'Established'
            if ($cols[2] -match ':0$') { $st = 'Listen' }
            [void]$list.Add([pscustomobject]@{ stan = $st; lokalny = $cols[1].Substring(0, $li); lport = [int]$cols[1].Substring($li + 1); zdalny = $cols[2].Substring(0, $ri); zport = [int]$cols[2].Substring($ri + 1); pid = $procId; proces = $pn; plik = $pf })
        }
    }
    Save-Raw 'siec_polaczenia' @($list)
}

Invoke-Test 'siec_dns_proxy' 'Pamięć DNS, plik hosts, proxy, serwery DNS' {
    $cache = @()
    try {
        $cache = @(Get-DnsClientCache -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ nazwa = [string]$_.Entry; dane = [string]$_.Data; typ = [int]$_.Type } })
    } catch { Add-Note 'brak dostępu do pamięci DNS' }
    Save-Raw 'dns_cache' $cache

    $hostsPath = Join-Path $script:Sys32 'drivers\etc\hosts'
    $hosts = @()
    if (Test-Path -LiteralPath $hostsPath) {
        $hosts = @(Get-Content -LiteralPath $hostsPath | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    }
    Save-Raw 'hosts' $hosts

    $ie = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    $ieM = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings'
    $winhttp = ''
    try { $winhttp = ((& netsh.exe winhttp show proxy) -join "`n").Trim() } catch {}
    Save-Raw 'proxy' ([pscustomobject]@{
        uzytkownik_wlaczony = $ie.ProxyEnable
        uzytkownik_serwer   = $ie.ProxyServer
        uzytkownik_wyjatki  = $ie.ProxyOverride
        uzytkownik_pac      = $ie.AutoConfigURL
        maszyna_serwer      = $ieM.ProxyServer
        maszyna_pac         = $ieM.AutoConfigURL
        winhttp             = $winhttp
        winhttp_ustawiony   = [bool]($winhttp -match '[A-Za-z0-9][A-Za-z0-9\.\-]*:\d{2,5}')
        env_http_proxy      = (@([Environment]::GetEnvironmentVariable('HTTP_PROXY', 'User'), [Environment]::GetEnvironmentVariable('HTTP_PROXY', 'Machine'), [Environment]::GetEnvironmentVariable('HTTPS_PROXY', 'User'), [Environment]::GetEnvironmentVariable('HTTPS_PROXY', 'Machine')) | Where-Object { $_ }) -join ' | '
    })

    $dnsList = New-Object System.Collections.ArrayList
    $ifRoot = 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces'
    foreach ($ifk in Get-ChildItem -LiteralPath $ifRoot) {
        $ns = [string]$ifk.GetValue('NameServer')
        $dh = [string]$ifk.GetValue('DhcpNameServer')
        if ($ns -or $dh) { [void]$dnsList.Add([pscustomobject]@{ interfejs = $ifk.PSChildName; statyczny = $ns; dhcp = $dh }) }
    }
    Save-Raw 'dns_serwery' @($dnsList)
}

Invoke-Test 'certyfikaty' 'Zaufane certyfikaty główne' {
    $lm = @(Get-ChildItem -Path Cert:\LocalMachine\Root -ErrorAction Stop)
    $cu = @(Get-ChildItem -Path Cert:\CurrentUser\Root)
    $lmT = @{}
    foreach ($c in $lm) { $lmT[$c.Thumbprint] = $true }
    $res = @()
    foreach ($c in $lm) { $res += [pscustomobject]@{ magazyn = 'LocalMachine'; podmiot = $c.Subject; wystawca = $c.Issuer; odcisk = $c.Thumbprint; wazny_od = (Format-Date $c.NotBefore); wazny_do = (Format-Date $c.NotAfter); nazwa = $c.FriendlyName } }
    foreach ($c in $cu) {
        if ($lmT.ContainsKey($c.Thumbprint)) { continue }
        $res += [pscustomobject]@{ magazyn = 'CurrentUser'; podmiot = $c.Subject; wystawca = $c.Issuer; odcisk = $c.Thumbprint; wazny_od = (Format-Date $c.NotBefore); wazny_do = (Format-Date $c.NotAfter); nazwa = $c.FriendlyName }
    }
    Save-Raw 'certyfikaty' $res
}

Invoke-Test 'kamera_mikrofon' 'Kto używał kamery, mikrofonu i lokalizacji' {
    $base = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore'
    $res = New-Object System.Collections.ArrayList
    foreach ($cap in @('webcam', 'microphone', 'location')) {
        $capKey = Join-Path $base $cap
        if (-not (Test-Path -LiteralPath $capKey)) { continue }
        $g = Get-Item -LiteralPath $capKey
        [void]$res.Add([pscustomobject]@{ uprawnienie = $cap; aplikacja = '(ustawienie ogólne)'; typ = 'globalne'; wartosc = [string]$g.GetValue('Value'); start = $null; stop = $null; uzywa_teraz = $false; sciezka = $null })
        $keys = @()
        foreach ($sub in Get-ChildItem -LiteralPath $capKey) {
            if ($sub.PSChildName -eq 'NonPackaged') {
                foreach ($np in Get-ChildItem -LiteralPath $sub.PSPath) { $keys += [pscustomobject]@{ k = $np; typ = 'zwykły program'; sciezka = ($np.PSChildName -replace '#', '\') } }
            } else {
                $keys += [pscustomobject]@{ k = $sub; typ = 'aplikacja Store'; sciezka = $null }
            }
        }
        foreach ($x in $keys) {
            $s = $x.k.GetValue('LastUsedTimeStart')
            $e = $x.k.GetValue('LastUsedTimeStop')
            $teraz = ($s -is [long] -and $s -gt 0 -and ($e -eq 0 -or $null -eq $e))
            [void]$res.Add([pscustomobject]@{ uprawnienie = $cap; aplikacja = $x.k.PSChildName; typ = $x.typ; wartosc = [string]$x.k.GetValue('Value'); start = (Convert-FileTime $s); stop = (Convert-FileTime $e); uzywa_teraz = [bool]$teraz; sciezka = $x.sciezka })
        }
    }
    Save-Raw 'kamera_mikrofon' @($res)
}

Invoke-Test 'programy' 'Zainstalowane programy i aplikacje Store' {
    $list = New-Object System.Collections.ArrayList
    foreach ($root in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall', 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall')) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($k in Get-ChildItem -LiteralPath $root) {
            $dn = $k.GetValue('DisplayName')
            if (-not $dn) { continue }
            [void]$list.Add([pscustomobject]@{
                nazwa = [string]$dn; wersja = [string]$k.GetValue('DisplayVersion'); wydawca = [string]$k.GetValue('Publisher')
                zainstalowano = [string]$k.GetValue('InstallDate'); katalog = [string]$k.GetValue('InstallLocation')
                deinstalator = [string]$k.GetValue('UninstallString'); systemowy = [bool]($k.GetValue('SystemComponent') -eq 1)
                klucz = $k.Name
            })
        }
    }
    Save-Raw 'programy' @($list)
    $appx = @()
    try {
        $appx = @(Get-AppxPackage -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ nazwa = $_.Name; wydawca = $_.Publisher; wersja = [string]$_.Version; katalog = $_.InstallLocation; podpis = [string]$_.SignatureKind; framework = [bool]$_.IsFramework } })
    } catch { Add-Note 'nie udało się pobrać listy aplikacji Store' }
    Save-Raw 'aplikacje_store' $appx
}

function Resolve-ExtName($m, [string]$dir) {
    $n = [string]$m.name
    if ($n -match '^__MSG_(.+)__$') {
        $key = $Matches[1]
        $loc = [string]$m.default_locale
        $cands = @()
        if ($loc) { $cands += (Join-Path $dir ('_locales\' + $loc + '\messages.json')) }
        $cands += (Join-Path $dir '_locales\en\messages.json')
        $cands += (Join-Path $dir '_locales\en_US\messages.json')
        foreach ($c in $cands) {
            if (-not (Test-Path -LiteralPath $c)) { continue }
            try {
                $msgs = [IO.File]::ReadAllText($c) | ConvertFrom-Json
                foreach ($p in $msgs.PSObject.Properties) {
                    if ($p.Name -ieq $key -and $p.Value.message) { return [string]$p.Value.message }
                }
            } catch {}
        }
    }
    return $n
}

Invoke-Test 'rozszerzenia' 'Rozszerzenia przeglądarek' {
    $res = New-Object System.Collections.ArrayList
    $roots = @(
        @{ b = 'Chrome'; p = (Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data') },
        @{ b = 'Edge'; p = (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data') },
        @{ b = 'Brave'; p = (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\User Data') },
        @{ b = 'Vivaldi'; p = (Join-Path $env:LOCALAPPDATA 'Vivaldi\User Data') },
        @{ b = 'Opera'; p = (Join-Path $env:APPDATA 'Opera Software\Opera Stable') },
        @{ b = 'Opera GX'; p = (Join-Path $env:APPDATA 'Opera Software\Opera GX Stable') }
    )
    foreach ($r in $roots) {
        if (-not (Test-Path -LiteralPath $r.p)) { continue }
        $extDirs = @()
        if (Test-Path -LiteralPath (Join-Path $r.p 'Extensions')) { $extDirs += [pscustomobject]@{ profil = '(główny)'; dir = (Join-Path $r.p 'Extensions') } }
        foreach ($prof in Get-ChildItem -LiteralPath $r.p -Directory) {
            $e = Join-Path $prof.FullName 'Extensions'
            if (Test-Path -LiteralPath $e) { $extDirs += [pscustomobject]@{ profil = $prof.Name; dir = $e } }
        }
        foreach ($ed in $extDirs) {
            foreach ($ext in Get-ChildItem -LiteralPath $ed.dir -Directory) {
                if ($ext.Name -eq 'Temp') { continue }
                $ver = Get-ChildItem -LiteralPath $ext.FullName -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if (-not $ver) { continue }
                $mf = Join-Path $ver.FullName 'manifest.json'
                if (-not (Test-Path -LiteralPath $mf)) { continue }
                $m = $null
                try { $m = [IO.File]::ReadAllText($mf) | ConvertFrom-Json } catch {}
                if (-not $m) {
                    [void]$res.Add([pscustomobject]@{ przegladarka = $r.b; profil = $ed.profil; id = $ext.Name; nazwa = '(nie udało się odczytać manifestu)'; wersja = $ver.Name; uprawnienia = @(); ze_sklepu = $null; sciezka = $ver.FullName; zainstalowano = (Format-Date $ext.CreationTime) })
                    continue
                }
                $perms = @()
                foreach ($x in (@($m.permissions) + @($m.host_permissions) + @($m.optional_permissions))) { if ($x -is [string]) { $perms += $x } }
                foreach ($cs in @($m.content_scripts)) { foreach ($mt in @($cs.matches)) { if ($mt -is [string]) { $perms += ('content_script:' + $mt) } } }
                $store = [bool]([string]$m.update_url -match 'clients2\.google\.com|edge\.microsoft\.com|extension-updates\.opera\.com|addons\.opera\.com')
                [void]$res.Add([pscustomobject]@{
                    przegladarka = $r.b; profil = $ed.profil; id = $ext.Name; nazwa = (Resolve-ExtName $m $ver.FullName)
                    wersja = [string]$m.version; uprawnienia = @($perms | Select-Object -Unique); ze_sklepu = $store
                    sciezka = $ver.FullName; zainstalowano = (Format-Date $ext.CreationTime)
                })
            }
        }
    }
    $ffRoot = Join-Path $env:APPDATA 'Mozilla\Firefox\Profiles'
    if (Test-Path -LiteralPath $ffRoot) {
        foreach ($prof in Get-ChildItem -LiteralPath $ffRoot -Directory) {
            $ej = Join-Path $prof.FullName 'extensions.json'
            if (-not (Test-Path -LiteralPath $ej)) { continue }
            $j = $null
            try { $j = [IO.File]::ReadAllText($ej) | ConvertFrom-Json } catch {}
            if (-not $j) { continue }
            foreach ($a in @($j.addons)) {
                if (-not $a -or $a.type -ne 'extension') { continue }
                if ($a.location -in @('app-builtin', 'app-system-defaults', 'app-system-addons')) { continue }
                $perms = @()
                if ($a.userPermissions) { $perms = @(@($a.userPermissions.permissions) + @($a.userPermissions.origins) | Where-Object { $_ -is [string] }) }
                $inst = $null
                if ($a.installDate) { try { $inst = ([DateTime]'1970-01-01').AddMilliseconds([double]$a.installDate).ToLocalTime().ToString('yyyy-MM-dd HH:mm') } catch {} }
                [void]$res.Add([pscustomobject]@{
                    przegladarka = 'Firefox'; profil = $prof.Name; id = $a.id; nazwa = [string]$a.defaultLocale.name
                    wersja = [string]$a.version; uprawnienia = $perms
                    ze_sklepu = [bool]($a.location -eq 'app-profile' -and [string]$a.sourceURI -match 'addons\.mozilla\.org')
                    sciezka = ('lokalizacja: ' + $a.location); zainstalowano = $inst
                })
            }
        }
    }
    Save-Raw 'rozszerzenia' @($res)
}

Invoke-Test 'polityki' 'Polityki przeglądarek i zarządzanie komputerem (MDM)' {
    $pol = New-Object System.Collections.ArrayList
    foreach ($hive in @('HKLM:\SOFTWARE\Policies', 'HKCU:\Software\Policies')) {
        foreach ($b in @('Google\Chrome', 'Microsoft\Edge', 'BraveSoftware\Brave', 'Mozilla\Firefox')) {
            $root = Join-Path $hive $b
            if (-not (Test-Path -LiteralPath $root)) { continue }
            foreach ($v in @(Get-RegTree $root)) { if ($v) { [void]$pol.Add([pscustomobject]@{ przegladarka = $b; klucz = $v.klucz; nazwa = $v.nazwa; wartosc = $v.wartosc }) } }
        }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        $pj = Join-Path $pf 'Mozilla Firefox\distribution\policies.json'
        if (Test-Path -LiteralPath $pj) { [void]$pol.Add([pscustomobject]@{ przegladarka = 'Mozilla\Firefox'; klucz = $pj; nazwa = 'policies.json'; wartosc = (Limit-Text ([IO.File]::ReadAllText($pj)) 2000) }) }
    }
    Save-Raw 'polityki_przegladarek' @($pol)

    $enr = New-Object System.Collections.ArrayList
    $er = 'HKLM:\SOFTWARE\Microsoft\Enrollments'
    if (Test-Path -LiteralPath $er) {
        foreach ($k in Get-ChildItem -LiteralPath $er) {
            $prov = [string]$k.GetValue('ProviderID')
            $upn = [string]$k.GetValue('UPN')
            if ($prov -or $upn) { [void]$enr.Add([pscustomobject]@{ id = $k.PSChildName; dostawca = $prov; konto = $upn; stan = [string]$k.GetValue('EnrollmentState'); typ = [string]$k.GetValue('EnrollmentType') }) }
        }
    }
    Save-Raw 'mdm' @($enr)
}

Invoke-Test 'konta' 'Konta lokalne i administratorzy' {
    $users = @()
    if (Get-Command Get-LocalUser) {
        $users = @(Get-LocalUser -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ nazwa = $_.Name; wlaczone = [bool]$_.Enabled; opis = $_.Description; ostatnie_logowanie = (Format-Date $_.LastLogon); haslo_zmienione = (Format-Date $_.PasswordLastSet); sid = [string]$_.SID.Value } })
    } else {
        $users = @(Get-CimInstance Win32_UserAccount -Filter 'LocalAccount=True' | ForEach-Object { [pscustomobject]@{ nazwa = $_.Name; wlaczone = (-not $_.Disabled); opis = $_.Description; ostatnie_logowanie = $null; haslo_zmienione = $null; sid = $_.SID } })
    }
    Save-Raw 'konta' $users
    $admins = @()
    try {
        $admins = @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ nazwa = $_.Name; typ = [string]$_.ObjectClass; zrodlo = [string]$_.PrincipalSource; sid = [string]$_.SID.Value } })
    } catch {
        try {
            $gname = (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')).Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
            $grp = [ADSI]('WinNT://' + $env:COMPUTERNAME + '/' + $gname + ',group')
            $admins = @(@($grp.Invoke('Members')) | ForEach-Object {
                    $path = $_.GetType().InvokeMember('ADsPath', 'GetProperty', $null, $_, $null)
                    [pscustomobject]@{ nazwa = ($path -replace '^WinNT://', '' -replace '/', '\'); typ = ''; zrodlo = 'ADSI'; sid = '' }
                })
            Add-Note 'lista adminów z ADSI (Get-LocalGroupMember zawiódł)'
        } catch { Add-Note 'nie udało się odczytać grupy Administratorzy' }
    }
    Save-Raw 'administratorzy' $admins
}

Invoke-Test 'zdalny_dostep' 'Zdalny dostęp: RDP, Pomoc zdalna, SSH, WinRM' {
    $ts = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server'
    $ra = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Remote Assistance'
    $svc = @{}
    foreach ($n in @('TermService', 'sshd', 'WinRM', 'RemoteRegistry', 'SessionEnv')) {
        $s = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $n)
        if ($s) { $svc[$n] = ('{0}, start: {1}' -f $s.State, $s.StartMode) } else { $svc[$n] = 'brak' }
    }
    Save-Raw 'zdalny_dostep' ([pscustomobject]@{
        rdp_wylaczone     = $ts.fDenyTSConnections
        pomoc_zdalna      = $ra.fAllowToGetHelp
        pomoc_zdalna_pelna = $ra.fAllowFullControl
        uslugi            = [pscustomobject]$svc
    })
}

Invoke-Test 'defender' 'Microsoft Defender: stan, wykrycia, wykluczenia' {
    $st = $null
    try {
        $s = Get-MpComputerStatus -ErrorAction Stop
        $st = [pscustomobject]@{
            usluga = $s.AMServiceEnabled; antywirus = $s.AntivirusEnabled; ochrona_czasu_rzeczywistego = $s.RealTimeProtectionEnabled
            monitor_zachowan = $s.BehaviorMonitorEnabled; ochrona_przed_manipulacja = $s.IsTamperProtected
            tryb = [string]$s.AMRunningMode; sygnatury_z_dnia = (Format-Date $s.AntivirusSignatureLastUpdated)
            wiek_sygnatur_dni = $s.AntivirusSignatureAge; ostatni_szybki_skan = (Format-Date $s.QuickScanEndTime); ostatni_pelny_skan = (Format-Date $s.FullScanEndTime)
        }
    } catch { Add-Note 'Get-MpComputerStatus niedostępny (inny antywirus albo Defender wyłączony)' }
    $thr = @{}
    foreach ($t in @(Get-MpThreat)) { if ($t) { $thr[[string]$t.ThreatID] = $t } }
    $det = @()
    foreach ($d in @(Get-MpThreatDetection)) {
        if (-not $d) { continue }
        $t = $thr[[string]$d.ThreatID]
        $name = ''; $active = $null; $exec = $null
        if ($t) { $name = $t.ThreatName; $active = $t.IsActive; $exec = $t.DidThreatExecute }
        $det += [pscustomobject]@{
            zagrozenie = $name; id = [string]$d.ThreatID; wykryto = (Format-Date $d.InitialDetectionTime)
            akcja_udana = $d.ActionSuccess; aktywne = $active; uruchomione = $exec
            pliki = (@($d.Resources) -join ' | '); proces = $d.ProcessName; uzytkownik = $d.DomainUser
        }
    }
    $pref = Get-MpPreference
    $excl = $null
    if ($pref) {
        $excl = [pscustomobject]@{
            sciezki = @($pref.ExclusionPath); procesy = @($pref.ExclusionProcess); rozszerzenia = @($pref.ExclusionExtension); adresy_ip = @($pref.ExclusionIpAddress)
            wylaczona_ochrona_rt = $pref.DisableRealtimeMonitoring
        }
        if ((@($pref.ExclusionPath) -join ' ') -match '^N/A') { Add-Note 'wykluczenia widoczne tylko dla admina' }
    }
    $polDef = @(Get-RegTree 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender')
    $av = @()
    try {
        $av = @(Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop | ForEach-Object {
                $hex = '{0:X6}' -f [int]$_.productState
                [pscustomobject]@{ nazwa = $_.displayName; wlaczony = ($hex.Substring(2, 2) -in @('10', '11')); aktualny = ($hex.Substring(4, 2) -eq '00'); plik = $_.pathToSignedProductExe }
            })
    } catch {}
    Save-Raw 'defender' ([pscustomobject]@{ stan = $st; wykrycia = $det; wykluczenia = $excl; polityki = $polDef; antywirusy = $av })
}

Invoke-Test 'dziennik' 'Dziennik zdarzeń z 30 dni' {
    $res = [ordered]@{}
    $res['nowe_uslugi'] = @(Get-Events @{ LogName = 'System'; Id = 7045; StartTime = $script:Since } $null $null 300 | ForEach-Object {
            $h = Get-EvData $_
            [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); usluga = $h['ServiceName']; plik = $h['ImagePath']; start = $h['StartType']; konto = $h['AccountName'] }
        })
    $res['czyszczenie_system'] = @(Get-Events @{ LogName = 'System'; Id = 104; StartTime = $script:Since } $null $null 50 | ForEach-Object { [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); opis = (Limit-Text $_.Message 200) } })
    $res['defender'] = @(Get-Events @{ LogName = 'Microsoft-Windows-Windows Defender/Operational'; Id = @(1116, 1117, 5001, 5007); StartTime = $script:Since } $null $null 300 | ForEach-Object { [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); id = $_.Id; opis = (Limit-Text $_.Message 600) } })
    if ($script:IsAdmin) {
        $xp = "*[System[(EventID=4624) and TimeCreated[timediff(@SystemTime) <= 2592000000]]] and *[EventData[Data[@Name='LogonType']='10']]"
        $res['logowania_rdp'] = @(Get-Events $null $xp 'Security' 200 | ForEach-Object {
                $h = Get-EvData $_
                [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); konto = $h['TargetUserName']; adres = $h['IpAddress']; stacja = $h['WorkstationName'] }
            })
        $res['nowe_konta'] = @(Get-Events @{ LogName = 'Security'; Id = 4720; StartTime = $script:Since } $null $null 50 | ForEach-Object {
                $h = Get-EvData $_
                [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); konto = $h['TargetUserName']; utworzyl = $h['SubjectUserName'] }
            })
        $res['czyszczenie_security'] = @(Get-Events @{ LogName = 'Security'; Id = 1102; StartTime = $script:Since } $null $null 50 | ForEach-Object { [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); opis = (Limit-Text $_.Message 200) } })
    } else {
        Add-Note 'dziennik Security (logowania RDP, nowe konta) wymaga admina'
    }
    Save-Raw 'dziennik' ([pscustomobject]$res)
}

Invoke-Test 'telefon' 'Kanały dostępu do telefonu (Łącze z telefonem, iPhone, Android)' {
    $pl = [ordered]@{}
    $yp = Get-AppxPackage -Name 'Microsoft.YourPhone'
    $pl['zainstalowane'] = [bool]$yp
    $ypDir = Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.YourPhone_8wekyb3d8bbwe'
    $devs = @()
    $idx = Join-Path $ypDir 'LocalCache\Indexed'
    if (Test-Path -LiteralPath $idx) {
        foreach ($d in Get-ChildItem -LiteralPath $idx -Directory) {
            $dbDir = Join-Path $d.FullName 'System\Database'
            $dbs = @()
            if (Test-Path -LiteralPath $dbDir) { $dbs = @(Get-ChildItem -LiteralPath $dbDir -File -Filter '*.db') }
            $last = $null
            if ($dbs.Count -gt 0) { $last = Format-Date (($dbs | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime) }
            $devs += [pscustomobject]@{ id = $d.Name; bazy = (@($dbs | ForEach-Object { $_.Name }) -join ', '); ostatnia_zmiana = $last }
        }
    }
    $pl['urzadzenia'] = $devs
    $pl['proces_dziala'] = [bool](@($script:D['procesy']) | Where-Object { $_ -and $_.nazwa -match '^(PhoneExperienceHost|YourPhone|YourPhoneServer)\.exe$' })
    $ip = [ordered]@{}
    $lock = Join-Path $env:ProgramData 'Apple\Lockdown'
    $ip['lockdown_istnieje'] = (Test-Path -LiteralPath $lock)
    $ip['zaufane_urzadzenia'] = @()
    if ($ip['lockdown_istnieje']) {
        try {
            $ip['zaufane_urzadzenia'] = @(Get-ChildItem -LiteralPath $lock -Filter '*.plist' -File -ErrorAction Stop | Where-Object { $_.Name -ne 'SystemConfiguration.plist' } | ForEach-Object { [pscustomobject]@{ plik = $_.Name; zmieniono = (Format-Date $_.LastWriteTime) } })
        } catch { $ip['zaufane_urzadzenia'] = $null; Add-Note 'rekordy parowania iPhone (Lockdown) wymagają admina' }
    }
    $backs = @()
    foreach ($bd in @((Join-Path $env:APPDATA 'Apple Computer\MobileSync\Backup'), (Join-Path $env:USERPROFILE 'Apple\MobileSync\Backup'))) {
        if (-not (Test-Path -LiteralPath $bd)) { continue }
        foreach ($b in Get-ChildItem -LiteralPath $bd -Directory) {
            $info = Join-Path $b.FullName 'Info.plist'
            $txt = ''
            if (Test-Path -LiteralPath $info) { try { $txt = [IO.File]::ReadAllText($info) } catch {} }
            $get = { param($k) $mm = [regex]::Match($txt, '<key>' + $k + '</key>\s*<(string|date)>([^<]*)</'); if ($mm.Success) { $mm.Groups[2].Value } else { '' } }
            $enc = 'nieznane'
            $db = Join-Path $b.FullName 'Manifest.db'
            if (Test-Path -LiteralPath $db) {
                try {
                    $fs = [IO.File]::OpenRead($db)
                    $buf = New-Object byte[] 16
                    [void]$fs.Read($buf, 0, 16)
                    $fs.Close()
                    if ([Text.Encoding]::ASCII.GetString($buf, 0, 15) -eq 'SQLite format 3') { $enc = 'NIE' } else { $enc = 'tak' }
                } catch {}
            }
            if ($enc -eq 'nieznane') {
                $mp = Join-Path $b.FullName 'Manifest.plist'
                if (Test-Path -LiteralPath $mp) {
                    $mt = ''
                    try { $mt = [IO.File]::ReadAllText($mp) } catch {}
                    if ($mt -match '<key>IsEncrypted</key>\s*<true/>') { $enc = 'tak' } elseif ($mt -match '<key>IsEncrypted</key>\s*<false/>') { $enc = 'NIE' }
                }
            }
            $backs += [pscustomobject]@{ folder = $b.FullName; urzadzenie = (& $get 'Device Name'); model = (& $get 'Product Type'); ios = (& $get 'Product Version'); ostatnia_kopia = (& $get 'Last Backup Date'); zmodyfikowano = (Format-Date $b.LastWriteTime); zaszyfrowana = $enc }
        }
    }
    $ip['kopie'] = $backs
    $an = [ordered]@{}
    $adbPaths = @()
    $cmd = Get-Command adb.exe
    if ($cmd) { $adbPaths += $cmd.Source }
    foreach ($c in @((Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'), 'C:\platform-tools\adb.exe', (Join-Path $env:USERPROFILE 'platform-tools\adb.exe'), (Join-Path $env:USERPROFILE 'Downloads\platform-tools\adb.exe'), 'C:\adb\adb.exe')) {
        if ((Test-Path -LiteralPath $c) -and ($adbPaths -notcontains $c)) { $adbPaths += $c }
    }
    $an['adb'] = $adbPaths
    $key = Join-Path $env:USERPROFILE '.android\adbkey'
    $an['adbkey'] = $null
    if (Test-Path -LiteralPath $key) { $fi = Get-Item -LiteralPath $key -Force; $an['adbkey'] = [pscustomobject]@{ utworzono = (Format-Date $fi.CreationTime); zmieniono = (Format-Date $fi.LastWriteTime) } }
    $an['parowanie_bezprzewodowe'] = (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.android\adb_known_hosts.pb'))
    $sc = @()
    $scCmd = Get-Command scrcpy.exe
    if ($scCmd) { $sc += $scCmd.Source }
    $dl = Join-Path $env:USERPROFILE 'Downloads'
    if (Test-Path -LiteralPath $dl) { $sc += @(Get-ChildItem -LiteralPath $dl -Directory -Filter 'scrcpy*' | ForEach-Object { $_.FullName }) }
    $an['scrcpy'] = $sc
    $bt = @()
    try {
        $bt = @(Get-PnpDevice -Class Bluetooth -ErrorAction Stop | Where-Object { $_.InstanceId -match '^(BTHENUM|BTHLE|BTHLEDEVICE)\\' } | ForEach-Object { [pscustomobject]@{ nazwa = $_.FriendlyName; stan = [string]$_.Status } } | Sort-Object nazwa -Unique)
    } catch { Add-Note 'brak listy urządzeń Bluetooth' }
    Save-Raw 'telefon' ([pscustomobject]@{ lacze_z_telefonem = [pscustomobject]$pl; iphone = [pscustomobject]$ip; android = [pscustomobject]$an; bluetooth = $bt })
}

$script:IocDir = Join-Path $script:OutDir 'ioc'
if ($PobierzIOC) {
    Invoke-Test 'ioc' 'Pobieranie publicznej listy domen stalkerware' {
        if (-not (Test-Path -LiteralPath $script:IocDir)) { New-Item -ItemType Directory -Path $script:IocDir -Force | Out-Null }
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
        $base = 'https://raw.githubusercontent.com/AssoEchap/stalkerware-indicators/master/'
        Invoke-WebRequest -UseBasicParsing -Uri ($base + 'generated/hosts_full') -OutFile (Join-Path $script:IocDir 'hosts_full') -ErrorAction Stop
        Invoke-WebRequest -UseBasicParsing -Uri ($base + 'ioc.yaml') -OutFile (Join-Path $script:IocDir 'ioc.yaml') -ErrorAction Stop
    }
}

Invoke-Test 'zapora' 'Zapora systemu Windows i reguły przychodzące' {
    $prof = @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ profil = $_.Name; wlaczona = [string]$_.Enabled; przychodzace = [string]$_.DefaultInboundAction } })
    $rules = @{}
    foreach ($r in @(Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow)) { if ($r) { $rules[$r.InstanceID] = $r } }
    $list = New-Object System.Collections.ArrayList
    foreach ($af in @(Get-NetFirewallApplicationFilter -All)) {
        if (-not $af -or -not $rules.ContainsKey($af.InstanceID)) { continue }
        $prog = [string]$af.Program
        if (-not $prog -or $prog -eq 'Any' -or $prog -eq 'System') { continue }
        $r = $rules[$af.InstanceID]
        $pth = [Environment]::ExpandEnvironmentVariables($prog)
        [void]$list.Add([pscustomobject]@{ regula = $r.DisplayName; grupa = $r.DisplayGroup; profil = [string]$r.Profile; program = $pth; klasa = (Get-PathClass $pth) })
    }
    Save-Raw 'zapora' ([pscustomobject]@{ profile = $prof; reguly = @($list) })
}

Invoke-Test 'podpisy' 'Podpisy cyfrowe plików z autostartu, usług, zadań i procesów' {
    $paths = @{}
    $add = { param($p) if ($p -and -not $paths.ContainsKey($p.ToLowerInvariant())) { $paths[$p.ToLowerInvariant()] = $p } }
    foreach ($a in @($script:D['autostart'])) { if ($a) { & $add $a.plik; foreach ($x in @(Get-PathsInArgs $a.polecenie)) { & $add $x } } }
    foreach ($s in @($script:D['uslugi'])) { if ($s) { & $add $s.plik; & $add $s.service_dll } }
    foreach ($s in @($script:D['sterowniki'])) { if ($s -and $s.klasa -ne 'system') { & $add $s.plik } }
    foreach ($t in @($script:D['zadania'])) {
        if (-not $t) { continue }
        foreach ($a in @($t.akcje)) { if ($a -and $a.typ -eq 'exec') { & $add $a.plik; foreach ($x in @(Get-PathsInArgs $a.arguments)) { & $add $x } } }
    }
    foreach ($p in @($script:D['procesy'])) { if ($p) { & $add $p.plik } }
    foreach ($c in @($script:D['kamera_mikrofon'])) { if ($c -and $c.sciezka) { & $add $c.sciezka } }
    if ($script:D['zapora']) { foreach ($r in @($script:D['zapora'].reguly)) { if ($r -and $r.klasa -eq 'ryzykowna') { & $add $r.program } } }
    $res = New-Object System.Collections.ArrayList
    foreach ($p in $paths.Values) { $s = Get-Sig $p; if ($s) { [void]$res.Add($s) } }
    Save-Raw 'podpisy' @($res)
}

Invoke-Test 'wydajnosc' 'Dysk, wolne miejsce i obciążenie (tylko pomiar)' {
    $disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object { [pscustomobject]@{ dysk = $_.DeviceID; rozmiar_gb = [math]::Round($_.Size / 1GB, 1); wolne_gb = [math]::Round($_.FreeSpace / 1GB, 1) } })
    $phys = @()
    try { $phys = @(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ nazwa = $_.FriendlyName; typ = [string]$_.MediaType; zdrowie = [string]$_.HealthStatus; stan = [string]$_.OperationalStatus; rozmiar_gb = [math]::Round($_.Size / 1GB, 1) } }) } catch {}
    $smart = @(Get-CimInstance Win32_DiskDrive | ForEach-Object { [pscustomobject]@{ model = $_.Model; status = $_.Status } })
    $rel = @()
    if ($script:IsAdmin) {
        try { $rel = @(Get-PhysicalDisk | Get-StorageReliabilityCounter -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ dysk = $_.DeviceId; temperatura = $_.Temperature; zuzycie_proc = $_.Wear; bledy_odczytu = $_.ReadErrorsUncorrected; bledy_zapisu = $_.WriteErrorsUncorrected; godziny_pracy = $_.PowerOnHours } }) } catch {}
    }
    $folders = @(
        @{ n = 'Pliki tymczasowe użytkownika (%TEMP%)'; p = $env:TEMP },
        @{ n = 'Pliki tymczasowe Windows (C:\Windows\Temp)'; p = (Join-Path $script:WinDir 'Temp') },
        @{ n = 'Pobrane aktualizacje Windows Update'; p = (Join-Path $script:WinDir 'SoftwareDistribution\Download') },
        @{ n = 'Stara instalacja Windows (Windows.old)'; p = ($env:SystemDrive + '\Windows.old') },
        @{ n = 'Pulpit'; p = (Join-Path $env:USERPROFILE 'Desktop') },
        @{ n = 'Dokumenty'; p = (Join-Path $env:USERPROFILE 'Documents') },
        @{ n = 'Pobrane'; p = (Join-Path $env:USERPROFILE 'Downloads') },
        @{ n = 'Obrazy'; p = (Join-Path $env:USERPROFILE 'Pictures') },
        @{ n = 'Wideo'; p = (Join-Path $env:USERPROFILE 'Videos') },
        @{ n = 'Muzyka'; p = (Join-Path $env:USERPROFILE 'Music') },
        @{ n = 'AppData\Local'; p = $env:LOCALAPPDATA },
        @{ n = 'AppData\Roaming'; p = $env:APPDATA }
    )
    foreach ($b in @(@{ n = 'Chrome'; p = 'Google\Chrome\User Data' }, @{ n = 'Edge'; p = 'Microsoft\Edge\User Data' }, @{ n = 'Brave'; p = 'BraveSoftware\Brave-Browser\User Data' })) {
        $ud = Join-Path $env:LOCALAPPDATA $b.p
        if (-not (Test-Path -LiteralPath $ud)) { continue }
        foreach ($prof in Get-ChildItem -LiteralPath $ud -Directory) {
            foreach ($cd in @('Cache', 'Code Cache', 'GPUCache')) {
                $cp = Join-Path $prof.FullName $cd
                if (Test-Path -LiteralPath $cp) { $folders += @{ n = ('Pamięć podręczna {0} ({1}, {2})' -f $b.n, $prof.Name, $cd); p = $cp } }
            }
        }
    }
    $ffc = Join-Path $env:LOCALAPPDATA 'Mozilla\Firefox\Profiles'
    if (Test-Path -LiteralPath $ffc) { foreach ($prof in Get-ChildItem -LiteralPath $ffc -Directory) { $cp = Join-Path $prof.FullName 'cache2'; if (Test-Path -LiteralPath $cp) { $folders += @{ n = ('Pamięć podręczna Firefox ({0})' -f $prof.Name); p = $cp } } } }
    $sizes = @()
    foreach ($f in $folders) {
        $s = Get-DirSize $f.p
        if ($s) {
            $rz = Format-Size $s.bajty
            if ($s.niepelne) { $rz = 'co najmniej ' + $rz; Add-Note ('liczenie przerwane po 40 s: ' + $f.n) }
            $sizes += [pscustomobject]@{ nazwa = $f.n; sciezka = $f.p; bajty = $s.bajty; rozmiar = $rz; pliki = $s.pliki }
        }
    }
    $thumb = @(Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer') -Filter 'thumbcache_*.db' -File -Force)
    $tb = [int64]0
    foreach ($t in $thumb) { $tb += $t.Length }
    $sizes += [pscustomobject]@{ nazwa = 'Miniatury (thumbcache)'; sciezka = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'); bajty = $tb; rozmiar = (Format-Size $tb); pliki = $thumb.Count }
    try {
        $shell = New-Object -ComObject Shell.Application
        $rb = [int64]0
        $cnt = 0
        foreach ($it in @($shell.Namespace(10).Items())) { $rb += [int64]$it.Size; $cnt++ }
        $sizes += [pscustomobject]@{ nazwa = 'Kosz'; sciezka = 'Kosz'; bajty = $rb; rozmiar = (Format-Size $rb); pliki = $cnt }
    } catch {}
    $topCpu = @(Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 | ForEach-Object { [pscustomobject]@{ proces = $_.ProcessName; cpu_s = [math]::Round($_.CPU, 0); ram_mb = [math]::Round($_.WorkingSet64 / 1MB, 0) } })
    $topRam = @(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 | ForEach-Object { [pscustomobject]@{ proces = $_.ProcessName; cpu_s = [math]::Round($_.CPU, 0); ram_mb = [math]::Round($_.WorkingSet64 / 1MB, 0) } })
    $os = Get-CimInstance Win32_OperatingSystem
    $lastHf = Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1
    # Czas startu systemu i programy, które go spowalniają (dziennik Diagnostics-Performance)
    $boot = @(); $slow = @()
    if ($script:IsAdmin) {
        $perfLog = 'Microsoft-Windows-Diagnostics-Performance/Operational'
        $boot = @(Get-Events @{ LogName = $perfLog; Id = 100 } $null $null 5 | ForEach-Object {
                $h = Get-EvData $_
                [pscustomobject]@{ czas = (Format-Date $_.TimeCreated); start_s = [math]::Round([double]$h['BootTime'] / 1000, 0); po_zalogowaniu_s = [math]::Round([double]$h['BootPostBootTime'] / 1000, 0) }
            })
        $slow = @(Get-Events @{ LogName = $perfLog; Id = 101; StartTime = $script:Since } $null $null 200 | ForEach-Object {
                $h = Get-EvData $_
                $nm = $h['FriendlyName']
                if (-not $nm) { $nm = $h['Name'] }
                [pscustomobject]@{ program = $nm; plik = $h['FileName']; opoznienie_s = [math]::Round([double]$h['DegradationTime'] / 1000, 1) }
            } | Sort-Object opoznienie_s -Descending | Select-Object -First 8)
    } else {
        Add-Note 'czas startu systemu wymaga admina'
    }
    Save-Raw 'wydajnosc' ([pscustomobject]@{
        dyski = $disks; dyski_fizyczne = $phys; smart = $smart; niezawodnosc = $rel; foldery = $sizes
        top_cpu = $topCpu; top_ram = $topRam; start_systemu = $boot; spowalniajace_start = $slow
        ram_wolne_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1); ram_razem_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        ostatnia_aktualizacja = $(if ($lastHf) { Format-Date $lastHf.InstalledOn } else { $null })
        ostatnia_aktualizacja_kb = $(if ($lastHf) { $lastHf.HotFixID } else { $null })
    })
}

Save-Raw '_status' @($script:Status)

# ============================================================ analiza

Write-Host ''
Write-Host 'Analizuję wyniki...' -ForegroundColor Cyan

$script:F = New-Object System.Collections.ArrayList
$script:Clean = New-Object System.Collections.ArrayList
$script:Phone = New-Object System.Collections.ArrayList
$script:Hits = [ordered]@{}
$script:Obszary = @{}

function Add-Finding {
    param([string]$Kat, [string]$Obszar, [string]$Co, [string]$Gdzie, $Dowod, [string]$Dlaczego, [string]$Dalej, [string]$Pytanie, $Tabela, [string]$Plik)
    $dw = @()
    foreach ($d in @($Dowod)) { if ($d) { $dw += [string]$d } }
    if ($Plik -and (Test-Path -LiteralPath $Plik -PathType Leaf)) {
        $h = Get-Sha256 $Plik
        if ($h) { $dw += ('SHA256: ' + $h) }
    }
    $tb = @()
    foreach ($t in @($Tabela)) { if ($t) { $tb += [string]$t } }
    [void]$script:F.Add([pscustomobject]@{ kat = $Kat; obszar = $Obszar; co = $Co; gdzie = $Gdzie; dowod = $dw; dlaczego = $Dlaczego; dalej = $Dalej; pytanie = $Pytanie; tabela = $tb })
    $script:Obszary[$Obszar] = 1 + [int]$script:Obszary[$Obszar]
}

# Elementy obecne teraz, których nie było w poprzednim audycie (porównanie po kluczu).
# Brak pliku z poprzedniego audytu = nie porównujemy. Pusta lista to poprawny stan,
# chyba że -SkipIfEmpty (np. programy: pusta lista oznacza nieudany test).
function Get-NewItems([string]$Name, [scriptblock]$Key, [scriptblock]$Show, [scriptblock]$Filter, [switch]$SkipIfEmpty) {
    $res = @()
    if (-not $script:PrevDir) { return $res }
    $p = Join-Path $script:PrevDir ('raw\' + $Name + '.json')
    if (-not (Test-Path -LiteralPath $p)) { return $res }
    $prev = $null
    try { $prev = [IO.File]::ReadAllText($p) | ConvertFrom-Json } catch { return $res }
    $prevList = @($prev | Where-Object { $_ })
    $Current = @($script:D[$Name] | Where-Object { $_ })
    if ($Filter) {
        $prevList = @($prevList | Where-Object $Filter)
        $Current = @($Current | Where-Object $Filter)
    }
    if ($SkipIfEmpty -and $prevList.Count -eq 0) { return $res }
    $old = @{}
    foreach ($x in $prevList) { $old[[string](& $Key $x)] = 1 }
    foreach ($x in $Current) {
        if (-not $old.ContainsKey([string](& $Key $x))) { $res += [string](& $Show $x) }
    }
    return $res
}

function Add-Clean([string]$Obszar, [string]$Tekst) {
    if (-not $script:Obszary.ContainsKey($Obszar)) { [void]$script:Clean.Add($Tekst) }
}

function Add-Phone([string]$Kanal, [string]$Stan, [string]$Szczegoly, [string]$Ryzyko) {
    [void]$script:Phone.Add([pscustomobject]@{ kanal = $Kanal; stan = $Stan; szczegoly = $Szczegoly; ryzyko = $Ryzyko })
}

function Test-Wzorce([string]$Tekst, [string]$Zrodlo, [string]$Pokaz, [string]$Plik) {
    if (-not $Tekst) { return }
    foreach ($w in $script:Wzorce) {
        if ($w.rx.IsMatch($Tekst)) {
            if (-not $script:Hits.Contains($w.nazwa)) {
                $script:Hits[$w.nazwa] = [pscustomobject]@{ w = $w; dowody = (New-Object System.Collections.ArrayList); pliki = (New-Object System.Collections.ArrayList) }
            }
            $h = $script:Hits[$w.nazwa]
            $p = $Pokaz
            if (-not $p) { $p = $Tekst }
            $ev = ('{0}: {1}' -f $Zrodlo, (Limit-Text $p 200))
            if (-not $h.dowody.Contains($ev) -and $h.dowody.Count -lt 12) { [void]$h.dowody.Add($ev) }
            if ($Plik -and -not $h.pliki.Contains($Plik)) { [void]$h.pliki.Add($Plik) }
            return
        }
    }
}

# Flagi w linii poleceń: silne (prawie zawsze złe) i słabe (podejrzane w kontekście)
function Get-CmdFlags([string]$c) {
    $silne = @(); $slabe = @()
    if ($c) {
        $isPs = $c -match '(?i)powershell|pwsh'
        if ($isPs -and $c -match '(?i)\s[-/]e[a-z]*\s+[A-Za-z0-9+/=]{16,}') { $silne += 'zakodowany PowerShell (-enc)' }
        if ($c -match '(?i)downloadstring|downloadfile|net\.webclient|start-bitstransfer|bitsadmin.*/transfer|certutil.*-urlcache|frombase64string|invoke-expression|\biex\b') { $silne += 'pobieranie lub wykonywanie kodu z sieci albo z tekstu' }
        if ($c -match '(?i)mshta(\.exe)?["'']?\s+["'']?(https?:|vbscript:|javascript:)') { $silne += 'mshta uruchamia skrypt z sieci' }
        if ($c -match '(?i)regsvr32.*(/i:\s*https?:|scrobj\.dll)') { $silne += 'regsvr32 ładuje skrypt (technika Squiblydoo)' }
        if ($isPs -and $c -match '(?i)\s[-/]w[a-z]*\s+(h|hidden|1)\b') { $slabe += 'ukryte okno PowerShell' }
        if ($c -match '(?i)\b(wscript|cscript|mshta|rundll32|regsvr32)(\.exe)?\b') {
            foreach ($p in @(Get-PathsInArgs $c)) {
                if ((Get-PathClass $p) -ne 'ryzykowna') { continue }
                $ps = $script:SigCache[$p.ToLowerInvariant()]
                if (-not $ps) { $ps = Get-Sig $p }
                if (-not (Test-SigOk $ps)) { $silne += ('host skryptów uruchamia niepodpisany plik z nietypowego miejsca: ' + $p) }
            }
        }
    }
    return [pscustomobject]@{ silne = $silne; slabe = $slabe }
}

$script:SysNames = @{
    'svchost.exe' = 'system32'; 'lsass.exe' = 'system32'; 'csrss.exe' = 'system32'; 'winlogon.exe' = 'system32'
    'services.exe' = 'system32'; 'smss.exe' = 'system32'; 'wininit.exe' = 'system32'; 'spoolsv.exe' = 'system32'
    'taskhostw.exe' = 'system32'; 'dllhost.exe' = 'system32'; 'conhost.exe' = 'system32'; 'rundll32.exe' = 'system32'
    'dwm.exe' = 'system32'; 'sihost.exe' = 'system32'; 'ctfmon.exe' = 'system32'; 'runtimebroker.exe' = 'system32'
    'searchindexer.exe' = 'system32'; 'lsm.exe' = 'system32'; 'explorer.exe' = 'windows'; 'regsvr32.exe' = 'system32'
}

function Test-Masquerade([string]$Path) {
    if (-not $Path) { return $null }
    try {
        $name = [IO.Path]::GetFileName($Path).ToLowerInvariant()
        $dir = ([string][IO.Path]::GetDirectoryName($Path)).ToLowerInvariant()
    } catch { return $null }
    $w = $script:WinDir.ToLowerInvariant()
    if ($script:SysNames.ContainsKey($name)) {
        $ok = @(($w + '\system32'), ($w + '\syswow64'))
        if ($script:SysNames[$name] -eq 'windows') { $ok += $w }
        if ($ok -notcontains $dir -and $dir -notlike ($w + '\winsxs\*')) { return ('nazwa systemowa {0} poza katalogiem Windows' -f $name) }
    }
    if ($name -match '^(svch0st|scvhost|svhost|svchosts|svchost32|lsasss|lsas|isass|1sass|csrsss|crss|winlogin|expl0rer|explorer32|taskhost32|rundl32|rundll|dllhst|wuaucit|smsss|servises|scvhosts)\.exe$') { return ('nazwa łudząco podobna do systemowej: ' + $name) }
    if ($name -match '^(chrome|msedge|firefox|opera|brave)\.exe$' -and $dir -match '\\appdata\\roaming(\\|$)') { return ('przeglądarka uruchamiana z AppData\Roaming: ' + $name) }
    return $null
}

function Test-DoubleExt([string]$Path) {
    if (-not $Path) { return $false }
    return ($Path -match '(?i)\.(pdf|docx?|xlsx?|jpe?g|png|txt|mp4|mp3|zip|rar)\.(exe|scr|com|bat|cmd|vbs|js|pif)$')
}

$sigOf = { param($p) if ($p) { $script:SigCache[$p.ToLowerInvariant()] } else { $null } }

function Describe-File([string]$Path) {
    $s = $null
    if ($Path) { $s = $script:SigCache[$Path.ToLowerInvariant()] }
    if (-not $s -and $Path) { $s = Get-Sig $Path }
    return ('{0} ({1})' -f $Path, (Get-SignerShort $s))
}

$autostartFiles = @{}
$netByPid = @{}

try {
    # ---------- autostart
    $as = @($script:D['autostart'] | Where-Object { $_ })
    foreach ($a in $as) {
        if ($a.plik) { $autostartFiles[$a.plik.ToLowerInvariant()] = $true }
        Test-Wzorce ($a.nazwa + ' ' + $a.polecenie) 'autostart' ('{0} = {1}' -f $a.nazwa, $a.polecenie) $a.plik
        $sig = & $sigOf $a.plik
        $cls = Get-PathClass $a.plik
        $fl = Get-CmdFlags $a.polecenie
        $masq = Test-Masquerade $a.plik
        $pow = @()
        if ($masq) { $pow += $masq }
        if (Test-DoubleExt $a.plik) { $pow += 'podwójne rozszerzenie pliku' }
        $pow += @($fl.silne)
        if ($cls -eq 'ryzykowna' -and $sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') { $pow += ('plik w nietypowym miejscu i ' + (Get-SignerShort $sig)) }
        if ($fl.slabe.Count -gt 0 -and $cls -ne 'programfiles') { $pow += @($fl.slabe) }
        foreach ($x in @(Get-PathsInArgs $a.polecenie)) {
            $xs = & $sigOf $x
            if ((Get-PathClass $x) -eq 'ryzykowna' -and $xs -and $xs.status -ne 'Valid' -and $xs.status -ne 'BrakPliku') { $pow += ('uruchamia niepodpisany plik ' + $x) }
        }
        if ($pow.Count -gt 0) {
            $wyl = ''
            if ($a.wylaczony) { $wyl = ' Wpis jest wyłączony w Menedżerze zadań, ale nadal istnieje.' }
            Add-Finding 'PODEJRZANE' 'autostart' ('Wpis autostartu: ' + $a.nazwa) ($a.miejsce) @(('polecenie: ' + $a.polecenie), (Describe-File $a.plik)) (($pow -join '; ') + '.' + $wyl) 'Nie usuwaj na razie. Sprawdźmy razem, czy to coś, co instalowałeś. Jeśli nie, usuniemy wpis i plik (z kopią rejestru i kwarantanną).' $null $null $a.plik
        }
    }
    $sp = @($script:D['autostart_specjalne'] | Where-Object { $_ })
    foreach ($s in $sp) {
        $zle = $null
        if ($s.typ -eq 'Winlogon') {
            if ($s.nazwa -eq 'Shell' -and $s.wartosc -notmatch '^\s*explorer\.exe\s*,?\s*$') { $zle = 'Shell powinien mieć wartość explorer.exe' }
            if ($s.nazwa -eq 'Userinit' -and $s.wartosc -notmatch '^\s*[a-z]:\\windows\\system32\\userinit\.exe\s*,?\s*$') { $zle = 'Userinit powinien wskazywać tylko C:\Windows\system32\userinit.exe' }
            if ($s.klucz -like 'HKCU:*' -and $s.nazwa -eq 'Shell') { $zle = 'Shell ustawiony dla użytkownika (normalnie go tam nie ma)' }
            if ($s.nazwa -in @('Taskman', 'AppSetup') -and $s.wartosc) { $zle = ('nietypowa wartość ' + $s.nazwa) }
        } elseif ($s.typ -eq 'IFEO Debugger') {
            $zle = ('przy każdym uruchomieniu {0} startuje zamiast niego: {1}' -f $s.nazwa, $s.wartosc)
        } elseif ($s.typ -eq 'SilentProcessExit') {
            $zle = ('po zamknięciu {0} uruchamia się: {1}' -f $s.nazwa, $s.wartosc)
        } elseif ($s.typ -eq 'AppInit_DLLs' -and $s.nazwa -match '=1') {
            $zle = 'biblioteki wstrzykiwane do każdego programu z interfejsem'
        }
        if ($zle) {
            $kat = 'PODEJRZANE'
            if ($s.typ -eq 'IFEO Debugger' -and $s.wartosc -match '(?i)procexp|vsjitdebugger|systemexplorer|processhacker') { $kat = 'DO_WYJASNIENIA' }
            Add-Finding $kat 'autostart' ('Ukryty punkt startowy: ' + $s.typ) $s.klucz @(('{0} = {1}' -f $s.nazwa, $s.wartosc)) ($zle + '. To jedno z klasycznych miejsc, w których malware się zagnieżdża.') 'Omówimy przed zmianą. Klucz zostanie najpierw wyeksportowany do kopia-rejestru.' 'Czy instalowałeś narzędzie, które podmienia Menedżera zadań albo inny program (np. Process Explorer)?' $null (Resolve-ExePath $s.wartosc)
        }
    }
    $wylCount = @($as | Where-Object { $_.wylaczony }).Count
    Add-Clean 'autostart' ('Autostart: {0} wpisów w rejestrze i folderach Autostart ({1} wyłączonych), Winlogon, IFEO i AppInit_DLLs bez podejrzanych zmian.' -f $as.Count, $wylCount)

    # ---------- usługi i sterowniki
    $svcs = @($script:D['uslugi'] | Where-Object { $_ })
    $outside = 0
    foreach ($s in $svcs) {
        Test-Wzorce ($s.nazwa + ' ' + $s.wyswietlana + ' ' + $s.polecenie) 'usługa' ('{0} ({1}), {2}, stan: {3}' -f $s.wyswietlana, $s.nazwa, $s.polecenie, $s.stan) $s.plik
        if ($s.klasa -ne 'system' -and $s.klasa -ne 'programfiles') { $outside++ }
        $sig = & $sigOf $s.plik
        $pow = @()
        $masq = Test-Masquerade $s.plik
        if ($masq) { $pow += $masq }
        if ($s.klasa -eq 'ryzykowna' -and $sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') { $pow += ('plik usługi w nietypowym miejscu i ' + (Get-SignerShort $sig)) }
        if ($s.klasa -eq 'inna' -and $sig -and ($sig.status -eq 'NotSigned' -or $sig.status -eq 'HashMismatch')) { $pow += ('plik usługi poza Windows i Program Files, ' + (Get-SignerShort $sig)) }
        $pow += @((Get-CmdFlags $s.polecenie).silne)
        if ($s.service_dll -and (Get-PathClass $s.service_dll) -ne 'system') {
            $ds = & $sigOf $s.service_dll
            if (-not (Test-SigOk $ds)) { $pow += ('biblioteka usługi spoza System32: ' + (Describe-File $s.service_dll)) }
        }
        if ($pow.Count -gt 0) {
            Add-Finding 'PODEJRZANE' 'usługi' ('Usługa: {0} ({1})' -f $s.wyswietlana, $s.nazwa) ('HKLM\SYSTEM\CurrentControlSet\Services\' + $s.nazwa) @(('polecenie: ' + $s.polecenie), ('start: {0}, stan: {1}, konto: {2}' -f $s.start, $s.stan, $s.konto), (Describe-File $s.plik)) (($pow -join '; ') + '.') 'Sprawdzimy, do jakiego programu należy. Jeśli do żadnego znanego, zatrzymamy ją i usuniemy po kopii rejestru.' $null $null $s.plik
        }
    }
    foreach ($d in @($script:D['sterowniki'] | Where-Object { $_ -and $_.klasa -ne 'system' })) {
        $sig = & $sigOf $d.plik
        if ($sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') {
            Add-Finding 'PODEJRZANE' 'usługi' ('Sterownik poza katalogiem Windows: ' + $d.nazwa) ('HKLM\SYSTEM\CurrentControlSet\Services\' + $d.nazwa) @((Describe-File $d.plik), ('start: {0}, stan: {1}' -f $d.start, $d.stan)) 'Sterownik działa z najwyższymi uprawnieniami, a ten nie ma ważnego podpisu i leży poza katalogiem systemowym.' 'Nie ruszamy sterowników bez dokładnego sprawdzenia: najpierw ustalimy, do czego należy.' $null $null $d.plik
        }
    }
    Add-Clean 'usługi' ('Usługi: {0}, w tym {1} spoza Windows i Program Files. Żadna nie wygląda na podszywanie się, pliki spoza standardowych miejsc mają ważne podpisy. Sterowniki bez uwag.' -f $svcs.Count, $outside)

    # ---------- zadania
    $tasks = @($script:D['zadania'] | Where-Object { $_ })
    $nonMs = 0
    foreach ($t in $tasks) {
        $isMs = ($t.sciezka -like '\Microsoft\*')
        if (-not $isMs) { $nonMs++ }
        foreach ($a in @($t.akcje | Where-Object { $_ -and $_.typ -eq 'exec' })) {
            $full = ('{0} {1}' -f $a.execute, $a.arguments).Trim()
            if (-not $isMs) { Test-Wzorce ($t.nazwa + ' ' + $full) 'zadanie' ('{0}{1}: {2}' -f $t.sciezka, $t.nazwa, $full) $a.plik }
            $fl = Get-CmdFlags $full
            $sig = & $sigOf $a.plik
            $cls = Get-PathClass $a.plik
            $pow = @()
            $pow += @($fl.silne)
            $masq = Test-Masquerade $a.plik
            if ($masq) { $pow += $masq }
            if ($cls -eq 'ryzykowna' -and $sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') { $pow += ('uruchamia plik z nietypowego miejsca, ' + (Get-SignerShort $sig)) }
            if (-not $isMs -and $fl.slabe.Count -gt 0 -and $cls -ne 'programfiles') { $pow += @($fl.slabe) }
            if (-not $isMs -and $t.ukryte -and $a.execute -match '(?i)(powershell|pwsh|wscript|cscript|mshta|cmd)(\.exe)?$') { $pow += 'ukryte zadanie uruchamiające interpreter skryptów' }
            if ($pow.Count -gt 0) {
                Add-Finding 'PODEJRZANE' 'zadania' ('Zaplanowane zadanie: {0}{1}' -f $t.sciezka, $t.nazwa) ('Harmonogram zadań: ' + $t.sciezka + $t.nazwa) @(('akcja: ' + $full), ('wyzwalacze: {0}; autor: {1}; uruchamia jako: {2}; ukryte: {3}' -f $t.wyzwalacze, $t.autor, $t.uzytkownik, $t.ukryte), (Describe-File $a.plik)) (($pow -join '; ') + '.') 'Omówimy przed zmianą. Jeśli to nie Twoje, najpierw wyłączymy zadanie (da się włączyć z powrotem), dopiero potem usuniemy.' $null $null $a.plik
            }
        }
    }
    Add-Clean 'zadania' ('Zaplanowane zadania: {0} (w tym {1} spoza folderu Microsoft), bez zakodowanego PowerShella, ukrytych skryptów i plików z nietypowych miejsc.' -f $tasks.Count, $nonMs)

    # ---------- WMI
    $wmi = $script:D['wmi']
    if ($wmi) {
        $cons = @()
        foreach ($c in @($wmi.konsumenci_cmd)) { if ($c -and -not ($c.Name -eq 'BVTConsumer' -and [string]$c.CommandLineTemplate -match 'KernCap\.vbs')) { $cons += ('CommandLine: {0} = {1} {2}' -f $c.Name, $c.ExecutablePath, $c.CommandLineTemplate) } }
        foreach ($c in @($wmi.konsumenci_skrypt)) { if ($c) { $cons += ('ActiveScript: {0} ({1}) {2} {3}' -f $c.Name, $c.ScriptingEngine, $c.ScriptFileName, $c.ScriptText) } }
        if ($cons.Count -gt 0) {
            $bind = @(@($wmi.powiazania) | Where-Object { $_ } | ForEach-Object { ('powiązanie: {0} -> {1}' -f $_.Filtr, $_.Konsument) })
            Add-Finding 'PODEJRZANE' 'wmi' 'Trwała subskrypcja WMI uruchamiająca polecenie' 'root\subscription' (@($cons) + $bind) 'Subskrypcje WMI pozwalają uruchamiać kod po cichu przy zdarzeniach systemowych. Używa ich trochę oprogramowania firmowego, ale to też ulubiona kryjówka malware.' 'Ustalimy, do czego należy. Usunięcie wymaga admina i robimy je dopiero po omówieniu.' $null $null $null
        }
        Add-Clean 'wmi' 'Subskrypcje WMI: brak podejrzanych konsumentów poleceń i skryptów.'
    }

    # ---------- sieć (przygotowanie: kto ma połączenia)
    $conns = @($script:D['siec_polaczenia'] | Where-Object { $_ })
    foreach ($c in $conns) {
        if ($c.stan -eq 'Established' -and $c.zdalny -notmatch '^(127\.|::1$|0\.0\.0\.0)') {
            if (-not $netByPid.ContainsKey($c.pid)) { $netByPid[$c.pid] = New-Object System.Collections.ArrayList }
            if ($netByPid[$c.pid].Count -lt 5) { [void]$netByPid[$c.pid].Add(('{0}:{1}' -f $c.zdalny, $c.zport)) }
        }
    }

    # ---------- procesy
    $procs = @($script:D['procesy'] | Where-Object { $_ -and $_.pid -ne $script:SelfPid })
    $unsignedRisky = @()
    foreach ($p in $procs) {
        Test-Wzorce ($p.nazwa + ' ' + $p.plik) 'proces' ('{0} (PID {1}) {2}' -f $p.nazwa, $p.pid, $p.plik) $p.plik
        if (-not $p.plik) { continue }
        $masq = Test-Masquerade $p.plik
        $sig = & $sigOf $p.plik
        $cls = Get-PathClass $p.plik
        $net = $netByPid[$p.pid]
        $inAuto = $autostartFiles.ContainsKey($p.plik.ToLowerInvariant())
        if ($masq) {
            Add-Finding 'PODEJRZANE' 'procesy' ('Proces podszywający się pod systemowy: ' + $p.nazwa) ('PID {0}' -f $p.pid) @((Describe-File $p.plik), ('linia poleceń: ' + $p.linia), ('połączenia: ' + (@($net) -join ', '))) ($masq + '. Prawdziwe pliki systemowe leżą w C:\Windows\System32.') 'Nie zamykaj go na razie (to może zaalarmować osobę, która to założyła, i utrudnić zebranie dowodów). Omówimy kolejność.' $null $null $p.plik
            continue
        }
        if ($cls -eq 'ryzykowna' -and $sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') {
            if ($net -or $inAuto) {
                $why = @('niepodpisany plik z nietypowego miejsca')
                if ($net) { $why += ('ma aktywne połączenia: ' + (@($net) -join ', ')) }
                if ($inAuto) { $why += 'startuje razem z systemem' }
                Add-Finding 'PODEJRZANE' 'procesy' ('Niepodpisany proces z połączeniami lub autostartem: ' + $p.nazwa) ('PID {0}' -f $p.pid) @((Describe-File $p.plik), ('linia poleceń: ' + $p.linia), ('uruchomiony: ' + $p.start)) (($why -join ', ') + '. Sam brak podpisu nie przesądza (np. małe darmowe programy), ale to typowy profil trojana.') 'Powiedz, czy znasz ten program. Jeśli nie, zabezpieczymy plik w kwarantannie i usuniemy jego autostart.' $null $null $p.plik
            } else {
                $unsignedRisky += ('{0} (PID {1}): {2}' -f $p.nazwa, $p.pid, $p.plik)
            }
        }
    }
    if ($unsignedRisky.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'procesy' 'Niepodpisane programy uruchomione z AppData, Temp lub Pobranych' 'lista poniżej' $null 'Nie mają połączeń sieciowych ani autostartu, więc to raczej przenośne programy albo instalatory. Warto tylko rzucić okiem.' 'Jeśli coś z listy jest Ci obce, napisz, sprawdzimy to dokładniej.' 'Czy znasz wszystkie programy z tej listy?' ($unsignedRisky | Select-Object -Unique) $null
    }
    Add-Clean 'procesy' ('Procesy: {0}. Brak plików podszywających się pod systemowe i brak niepodpisanych procesów z połączeniami z nietypowych miejsc.' -f $procs.Count)

    # ---------- sieć
    $portTools = @{ 5938 = 'TeamViewer'; 7070 = 'AnyDesk'; 6568 = 'AnyDesk'; 5900 = 'VNC'; 5901 = 'VNC'; 5902 = 'VNC'; 5800 = 'VNC (www)'; 5500 = 'VNC (nasłuch zwrotny)'; 3389 = 'Pulpit zdalny (RDP)'; 22 = 'SSH'; 5985 = 'WinRM'; 5986 = 'WinRM (HTTPS)'; 4899 = 'Radmin'; 5650 = 'Remote Utilities'; 21116 = 'RustDesk'; 21118 = 'RustDesk'; 8040 = 'ScreenConnect'; 6129 = 'DameWare' }
    $ratPorts = @{ 1604 = 'DarkComet'; 2404 = 'Remcos'; 4782 = 'Quasar'; 5552 = 'njRAT'; 6606 = 'AsyncRAT'; 7707 = 'AsyncRAT'; 8808 = 'AsyncRAT'; 54984 = 'NanoCore'; 3360 = 'NetWire' }
    $listenRemote = @()
    foreach ($c in $conns) {
        if ($c.stan -eq 'Listen' -and $portTools.ContainsKey($c.lport) -and $c.lokalny -notmatch '^(127\.|::1$)') {
            $listenRemote += ('port {0} ({1}) nasłuchuje na {2}, proces: {3} {4}' -f $c.lport, $portTools[$c.lport], $c.lokalny, $c.proces, $c.plik)
        }
        if ($c.stan -eq 'Established' -and $ratPorts.ContainsKey($c.zport)) {
            Add-Finding 'PODEJRZANE' 'sieć' ('Połączenie na port typowy dla RAT {0}' -f $ratPorts[$c.zport]) ('{0}:{1}' -f $c.zdalny, $c.zport) @(('proces: {0} (PID {1}) {2}' -f $c.proces, $c.pid, (Describe-File $c.plik))) 'Ten port jest domyślnym portem znanej rodziny trojanów. Sam numer portu niczego nie przesądza, ale warto to sprawdzić.' 'Sprawdzimy, czym jest ten proces, zanim cokolwiek zamkniemy.' $null $null $c.plik
        }
    }
    $listenRemote = @($listenRemote | Select-Object -Unique)
    if ($listenRemote.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'sieć' 'Otwarte porty narzędzi zdalnego dostępu' 'połączenia sieciowe' $listenRemote 'Ten komputer czeka na połączenia przez porty używane do zdalnego sterowania. Jeśli sam z tego korzystasz, wszystko gra.' 'Jeśli nie korzystasz, wyłączymy daną usługę (odwracalnie).' 'Czy łączysz się z tym komputerem zdalnie albo ktoś Ci w ten sposób pomaga?' $null $null
    }
    $estab = @($conns | Where-Object { $_.stan -eq 'Established' }).Count
    $lst = @($conns | Where-Object { $_.stan -eq 'Listen' }).Count
    Add-Clean 'sieć' ('Sieć: {0} aktywnych połączeń i {1} portów nasłuchujących, bez portów narzędzi zdalnych i bez połączeń na porty typowe dla RAT-ów.' -f $estab, $lst)

    # ---------- DNS, hosts, proxy, IOC
    $iocDomains = @{}
    $hf = Join-Path $script:IocDir 'hosts_full'
    if (Test-Path -LiteralPath $hf) { foreach ($l in [IO.File]::ReadAllLines($hf)) { $x = $l.Trim().ToLowerInvariant(); if ($x -and -not $x.StartsWith('#')) { $iocDomains[$x] = 'lista AssoEchap' } } }
    $iy = Join-Path $script:IocDir 'ioc.yaml'
    if (Test-Path -LiteralPath $iy) {
        $app = ''; $sec = ''
        foreach ($l in [IO.File]::ReadAllLines($iy)) {
            if ($l -match '^- name:\s*(.+)$') { $app = $Matches[1].Trim(); $sec = ''; continue }
            if ($l -match '^  (websites|distribution):\s*$') { $sec = 'strona'; continue }
            if ($l -match '^    domains:\s*$') { $sec = 'serwer C2'; continue }
            if ($l -match '^\s*[a-z_]+:') { $sec = ''; continue }
            if ($sec -and $l -match '^\s*-\s+(\S+)\s*$') {
                $dom = $Matches[1].Trim().ToLowerInvariant()
                if ($dom -notmatch '^\d+\.\d+\.\d+\.\d+$') { $iocDomains[$dom] = ('{0} ({1})' -f $app, $sec) }
            }
        }
    }
    $iocUsed = ($iocDomains.Count -gt 0)
    $tokens = '(mspy|flexispy|spyrix|refog|kidlogger|hoverwatch|spyera|webwatcher|pctattletale|wolfeye|sentrypc|ikeymonitor|clevguard|kidsguard|thetruthspy|spyzie|cocospy|spyic|xnspy|eyezy|umobix|spyhuman|snoopza|highster|spybubble|teramind|activtrak|kickidler|staffcop)'
    $dnsHits = @()
    foreach ($e in @($script:D['dns_cache'] | Where-Object { $_ })) {
        $n = ([string]$e.nazwa).ToLowerInvariant().TrimEnd('.')
        if (-not $n) { continue }
        $hit = $null
        if ($iocUsed) {
            $parts = $n.Split('.')
            for ($i = 0; $i -lt $parts.Count - 1; $i++) {
                $cand = ($parts[$i..($parts.Count - 1)]) -join '.'
                if ($iocDomains.ContainsKey($cand)) { $hit = $iocDomains[$cand]; break }
            }
        }
        if (-not $hit -and $n -match $tokens) { $hit = 'nazwa znanego producenta oprogramowania szpiegującego' }
        if ($hit) { $dnsHits += ('{0} ({1})' -f $n, $hit) }
    }
    $dnsHits = @($dnsHits | Select-Object -Unique)
    if ($dnsHits.Count -gt 0) {
        $kat = 'PODEJRZANE'
        if ($iocUsed -and ($dnsHits -match 'serwer C2|lista AssoEchap').Count -gt 0) { $kat = 'POTWIERDZONE' }
        Add-Finding $kat 'dns' 'Ten komputer łączył się niedawno z domenami oprogramowania szpiegującego' 'pamięć podręczna DNS' $dnsHits 'Domena jest na publicznej liście serwerów stalkerware albo nosi nazwę producenta takiego oprogramowania. Uwaga: jeśli niedawno czytałeś o tych programach w przeglądarce, wpis może być tylko śladem wizyty na stronie.' 'Powiedz, czy wchodziłeś na strony tych firm. Jeśli nie, szukamy programu, który się z nimi łączy (sprawdzimy połączenia na żywo).' 'Czy w ostatnich dniach odwiedzałeś strony tych firm?' $null $null
    }
    $hostsLines = @($script:D['hosts'] | Where-Object { $_ })
    $hostsBad = @(); $hostsOther = @()
    foreach ($l in $hostsLines) {
        $body = ($l -split '#')[0].Trim()
        $parts = @($body -split '\s+' | Where-Object { $_ })
        if ($parts.Count -lt 2) { continue }
        $ip = $parts[0]
        $names = ($parts[1..($parts.Count - 1)]) -join ' '
        if ($names -match '^(localhost|localhost\.localdomain|ip6-localhost)$') { continue }
        $isBlock = ($ip -match '^(0\.0\.0\.0|127\.0\.0\.1|::1?|::)$')
        if ($isBlock -and $names -match '(?i)windowsupdate|update\.microsoft|wdcp|smartscreen|definitionupdates|avast|avg\.com|eset|kaspersky|bitdefender|malwarebytes|norton|mcafee|virustotal|sophos|drweb|f-secure|trendmicro') { $hostsBad += ('{0} (blokuje stronę bezpieczeństwa lub aktualizacji)' -f $l) }
        elseif (-not $isBlock -and $names -match '(?i)(^|\.|\s)(google|microsoft|microsoftonline|live|outlook|office|facebook|apple|icloud|pkobp|ipko|mbank|ing|santander|pekao|bnpparibas|millennium|aliorbank|allegro|paypal|gmail|instagram|whatsapp|messenger|olx)\.(com|pl|net|eu)') { $hostsBad += ('{0} (przekierowuje popularną domenę na inny adres)' -f $l) }
        else { $hostsOther += $l }
        if ($iocUsed) { foreach ($nm in ($names -split ' ')) { if ($iocDomains.ContainsKey($nm.ToLowerInvariant())) { $hostsBad += ('{0} (domena z listy stalkerware: {1})' -f $l, $iocDomains[$nm.ToLowerInvariant()]) } } }
    }
    if ($hostsBad.Count -gt 0) {
        Add-Finding 'PODEJRZANE' 'hosts' 'Plik hosts zmienia działanie ważnych domen' ($script:Sys32 + '\drivers\etc\hosts') $hostsBad 'Malware często blokuje aktualizacje antywirusa albo przekierowuje banki i pocztę na fałszywe serwery przez plik hosts.' 'Zrobimy kopię pliku hosts i usuniemy tylko te linie.' $null $null $null
    }
    if ($hostsOther.Count -gt 0) {
        $opis = 'Własne wpisy w pliku hosts. Często to programy blokujące reklamy albo ustawienia programisty.'
        if ($hostsOther.Count -gt 100) { $opis = ('Plik hosts ma {0} własnych wpisów: to zwykle lista blokująca reklamy.' -f $hostsOther.Count) }
        Add-Finding 'DO_WYJASNIENIA' 'hosts' 'Własne wpisy w pliku hosts' ($script:Sys32 + '\drivers\etc\hosts') ($hostsOther | Select-Object -First 15) $opis 'Jeśli to nie Ty, usuniemy je po zrobieniu kopii.' 'Czy dodawałeś coś do pliku hosts albo używasz programu blokującego reklamy?' $null $null
    }
    $px = $script:D['proxy']
    $proxyOn = @()
    if ($px) {
        if ($px.uzytkownik_wlaczony -eq 1 -and $px.uzytkownik_serwer) { $proxyOn += ('proxy użytkownika: ' + $px.uzytkownik_serwer) }
        if ($px.uzytkownik_pac) { $proxyOn += ('skrypt konfiguracji proxy (PAC): ' + $px.uzytkownik_pac) }
        if ($px.maszyna_pac) { $proxyOn += ('skrypt PAC dla całego komputera: ' + $px.maszyna_pac) }
        if ($px.winhttp_ustawiony) { $proxyOn += ('proxy WinHTTP: ' + ($px.winhttp -replace '\s+', ' ')) }
        if ($px.env_http_proxy) { $proxyOn += ('zmienne HTTP_PROXY: ' + $px.env_http_proxy) }
    }

    # ---------- certyfikaty
    $knownCa = '(?i)microsoft|digicert|globalsign|sectigo|comodo|usertrust|aaa certificate services|entrust|go ?daddy|starfield|verisign|symantec|thawte|geotrust|quovadis|isrg|internet security research|baltimore|certum|unizeto|asseco|identrust|amazon|google trust|gts root|securetrust|trustwave|xramp|secure global|addtrust|network solutions|affirmtrust|actalis|buypass|certigna|dhimyotis|d-trust|t-telesec|telekom|swisssign|hellenic|harica|izenpe|netlock|oiste|wisekey|ssl\.com|twca|chunghwa|secom|security communication|emsign|e-szigno|microsec|telia|sonera|certainly|atos|accvraiz|autoridad de certificacion|firmaprofesional|staat der nederlanden|cybertrust|equifax|class 3 public primary|class 2 primary|no liability accepted|hotspot 2\.0|cfca|gdca|vtrus|trustasia|certinomis|e-tugra|szafir|krajowa izba|kir s\.a|camerfirma|chambersign|chambers of commerce|securesign|epki|ac raiz|globaltrust|e-commerce monitoring|disig|trustis|naver|bjca|sheca|unitrust|apple|tuntrust|sk id|certipost|visa|trustcor|federal common policy|anf |fnmt|ca disig|ipsca|halcom|post\.ch|swisscom|luxtrust|sigen|e-me|telefonica|government|root ca generation|kamu sm|tubitak'
    $avCa = '(?i)avast|avg|eset|kaspersky|bitdefender|norton|sophos|f-secure|trend micro|mcafee|malwarebytes|panda|emsisoft|webroot|g data|avira|comodo internet security|fortinet|zscaler|netskope'
    $mitmCa = '(?i)superfish|edellroot|dsdtestprovider|komodia|privdog|mitmproxy|fiddler|do_not_trust|charles proxy|portswigger|burp'
    $certs = @($script:D['certyfikaty'] | Where-Object { $_ })
    $certUnknown = @(); $certMitm = @(); $certAv = @()
    foreach ($c in $certs) {
        $txt = ('{0} {1} {2}' -f $c.podmiot, $c.wystawca, $c.nazwa)
        $line = ('{0} [{1}] odcisk {2}, ważny od {3}' -f $c.podmiot, $c.magazyn, $c.odcisk, $c.wazny_od)
        if ($txt -match $mitmCa) { $certMitm += $line }
        elseif ($txt -match $avCa) { $certAv += $line }
        elseif ($txt -notmatch $knownCa) { $certUnknown += $line }
        elseif ($c.magazyn -eq 'CurrentUser' -and $c.wazny_od -and ([datetime]$c.wazny_od) -gt (Get-Date).AddDays(-365)) { $certUnknown += ($line + ' (dodany tylko dla Twojego konta)') }
    }
    if ($certMitm.Count -gt 0) {
        Add-Finding 'PODEJRZANE' 'certyfikaty' 'Certyfikat narzędzia do podsłuchiwania ruchu HTTPS' 'Cert:\...\Root' $certMitm 'Taki certyfikat główny pozwala programowi odczytywać szyfrowany ruch (strony, poczta, banki). Programiści używają tego celowo, na zwykłym komputerze to poważny sygnał.' 'Jeśli to nie Twoje narzędzie programistyczne, usuniemy certyfikat (po zapisaniu kopii).' 'Czy używasz Fiddlera, Burpa, Charlesa albo mitmproxy?' $null $null
    }
    if ($certUnknown.Count -gt 0) {
        $kat = 'DO_WYJASNIENIA'
        $why = 'Certyfikaty główne spoza listy znanych urzędów certyfikacji. Często to certyfikaty producenta laptopa, firmy albo programu VPN.'
        if ($proxyOn.Count -gt 0) { $kat = 'PODEJRZANE'; $why = 'Nieznany certyfikat główny RAZEM z ustawionym proxy: to klasyczny układ do czytania ruchu HTTPS przez kogoś trzeciego.' }
        Add-Finding $kat 'certyfikaty' 'Nieznane certyfikaty główne' 'Cert:\LocalMachine\Root, Cert:\CurrentUser\Root' $certUnknown $why 'Sprawdzimy po nazwach, skąd się wzięły. Usuwamy tylko te, które na pewno nie są potrzebne.' 'Czy ten komputer jest służbowy albo używasz VPN lub programu firmowego?' $null $null
    }
    if ($certAv.Count -gt 0) { [void]$script:Clean.Add('Certyfikaty antywirusa do skanowania HTTPS (normalne): ' + (($certAv | ForEach-Object { ($_ -split ' \[')[0] }) -join '; ')) }
    Add-Clean 'certyfikaty' ('Certyfikaty główne: {0}, wszystkie od znanych urzędów certyfikacji.' -f $certs.Count)
    if ($proxyOn.Count -gt 0) {
        $kat = 'DO_WYJASNIENIA'
        if ($certUnknown.Count -gt 0 -or $certMitm.Count -gt 0) { $kat = 'PODEJRZANE' }
        Add-Finding $kat 'proxy' 'Ruch internetowy idzie przez proxy' 'Ustawienia internetowe / WinHTTP' $proxyOn 'Proxy przepuszcza Twój ruch przez inny serwer. W firmie to normalne, na prywatnym komputerze to sygnał, że ktoś może podglądać ruch.' 'Jeśli to nie Ty ani Twoja firma, wyłączymy proxy (zapiszemy stare ustawienia).' 'Czy ustawiałeś proxy albo komputer jest służbowy?' $null $null
    } else {
        [void]$script:Clean.Add('Proxy: wyłączone (ruch idzie bezpośrednio).')
    }
    $dnsStatic = @()
    foreach ($d in @($script:D['dns_serwery'] | Where-Object { $_ -and $_.statyczny })) {
        foreach ($ip in ($d.statyczny -split '[,\s]+' | Where-Object { $_ })) {
            if ($ip -match '^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.|fe80|fec0|fd|::1)') { continue }
            if ($ip -in @('8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1', '9.9.9.9', '149.112.112.112', '208.67.222.222', '208.67.220.220', '94.140.14.14', '94.140.15.15', '2001:4860:4860::8888', '2001:4860:4860::8844', '2606:4700:4700::1111', '2606:4700:4700::1001')) { continue }
            $dnsStatic += ('{0} (interfejs {1})' -f $ip, $d.interfejs)
        }
    }
    if ($dnsStatic.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'dns' 'Ręcznie ustawiony, nieznany serwer DNS' 'ustawienia karty sieciowej' $dnsStatic 'Serwer DNS decyduje, pod jaki adres trafiasz, wpisując nazwę strony. Ręcznie wpisany nieznany DNS może przekierowywać ruch.' 'Jeśli to nie Ty, przywrócimy automatyczny DNS.' 'Czy wpisywałeś ręcznie adres DNS?' $null $null
    }
    Add-Clean 'dns' ('Pamięć DNS: brak domen znanych producentów stalkerware{0}; serwery DNS automatyczne albo powszechnie znane.' -f $(if ($iocUsed) { (' i brak trafień na liście {0} domen AssoEchap' -f $iocDomains.Count) } else { '' }))
    Add-Clean 'hosts' 'Plik hosts: bez własnych wpisów.'

    # ---------- kamera, mikrofon, lokalizacja
    $cm = @($script:D['kamera_mikrofon'] | Where-Object { $_ -and $_.typ -ne 'globalne' })
    $capPl = @{ webcam = 'kamera'; microphone = 'mikrofon'; location = 'lokalizacja' }
    $recent = @()
    foreach ($c in $cm) {
        $label = $c.aplikacja
        if ($c.sciezka) { $label = $c.sciezka }
        Test-Wzorce ($c.aplikacja) ('dostęp: ' + $capPl[$c.uprawnienie]) $label $c.sciezka
        if ($c.sciezka) {
            $sig = & $sigOf $c.sciezka
            $cls = Get-PathClass $c.sciezka
            if ($cls -eq 'ryzykowna' -and $sig -and $sig.status -ne 'Valid') {
                Add-Finding 'PODEJRZANE' 'kamera' ('Nieznany program z nietypowego miejsca używał: ' + $capPl[$c.uprawnienie]) $c.sciezka @(('ostatnie użycie: {0} do {1}' -f $c.start, $c.stop), (Describe-File $c.sciezka)) ('Program z AppData, Temp lub Pobranych bez ważnego podpisu korzystał z: ' + $capPl[$c.uprawnienie] + '. Tak wygląda typowy RAT albo stalkerware.') 'Powiedz, czy to coś znajomego. Jeśli nie, to jedna z najważniejszych pozycji w raporcie.' $null $null $c.sciezka
            }
        }
        if ($c.uzywa_teraz) { $recent += ('{0}: {1} UŻYWA TERAZ (od {2})' -f $capPl[$c.uprawnienie], $label, $c.start) }
        elseif ($c.start -and ([datetime]$c.start) -gt $script:Since) { $recent += ('{0}: {1}, ostatnio {2}' -f $capPl[$c.uprawnienie], $label, $c.start) }
    }
    if ($recent.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'kamera' 'Programy, które w ostatnich 30 dniach używały kamery, mikrofonu lub lokalizacji' 'HKCU\...\CapabilityAccessManager\ConsentStore' $null 'To jedna z najlepszych wskazówek: Windows zapisuje, kto i kiedy włączał kamerę lub mikrofon. Zwykle to komunikatory i przeglądarki.' 'Przejrzyj daty. Jeśli coś używało kamery, kiedy nie siedziałeś przy komputerze, daj znać.' 'Czy każda z tych pozycji to Ty (rozmowa, nagranie, spotkanie)?' ($recent | Sort-Object) $null
    }
    Add-Clean 'kamera' 'Kamera, mikrofon i lokalizacja: w ostatnich 30 dniach nikt nie używał ich z nietypowych miejsc.'

    # ---------- programy
    $progs = @($script:D['programy'] | Where-Object { $_ })
    $newProgs = @()
    foreach ($p in $progs) {
        Test-Wzorce ($p.nazwa + ' ' + $p.wydawca) 'zainstalowany program' ('{0} {1} ({2})' -f $p.nazwa, $p.wersja, $p.wydawca) $null
        if ($p.zainstalowano -match '^\d{8}$') {
            try {
                $dt = [datetime]::ParseExact($p.zainstalowano, 'yyyyMMdd', $null)
                if ($dt -gt $script:Since -and -not $p.systemowy) { $newProgs += ('{0}: {1} {2} ({3})' -f $dt.ToString('yyyy-MM-dd'), $p.nazwa, $p.wersja, $p.wydawca) }
            } catch {}
        }
    }
    foreach ($a in @($script:D['aplikacje_store'] | Where-Object { $_ -and -not $_.framework })) {
        if ($a.nazwa -eq 'Microsoft.YourPhone') { continue }
        Test-Wzorce $a.nazwa 'aplikacja Store' $a.nazwa $null
    }
    if ($newProgs.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'programy' 'Programy zainstalowane w ostatnich 30 dniach' 'Panel sterowania > Programy' $null 'Nic tu nie musi być złego. To po prostu lista nowości: łatwo w niej wypatrzyć coś, czego nie instalowałeś.' 'Jeśli coś jest obce, napisz, sprawdzimy to.' 'Czy wszystkie te programy instalowałeś Ty?' ($newProgs | Sort-Object -Descending | Select-Object -First 40) $null
    }

    # ---------- rozszerzenia i polityki
    $exts = @($script:D['rozszerzenia'] | Where-Object { $_ })
    $riskyPerm = '^(<all_urls>|\*://\*/\*|https?://\*/\*|content_script:(<all_urls>|\*://\*/\*|https?://\*/\*)|webRequest|webRequestBlocking|history|cookies|debugger|nativeMessaging|proxy|clipboardRead|desktopCapture|tabCapture|management)$'
    $broad = @()
    foreach ($e in $exts) {
        Test-Wzorce $e.nazwa ('rozszerzenie ' + $e.przegladarka) ('{0} ({1})' -f $e.nazwa, $e.id) $null
        $rp = @(@($e.uprawnienia) | Where-Object { $_ -match $riskyPerm } | ForEach-Object { $_ -replace '^content_script:', 'skrypt na stronach ' } | Select-Object -Unique)
        if ($rp.Count -eq 0) { continue }
        if ($e.ze_sklepu -eq $false) {
            Add-Finding 'PODEJRZANE' 'rozszerzenia' ('Rozszerzenie spoza sklepu z szerokimi uprawnieniami: {0}' -f $e.nazwa) ('{0}, profil {1}, id {2}' -f $e.przegladarka, $e.profil, $e.id) @(('uprawnienia: ' + ($rp -join ', ')), ('folder: ' + $e.sciezka), ('pojawiło się: ' + $e.zainstalowano)) 'Rozszerzenie nie pochodzi ze sklepu przeglądarki, a może czytać strony, ciasteczka lub historię. Tak działają rozszerzenia szpiegujące i kradnące sesje.' 'Jeśli go nie znasz, usuniemy je w ustawieniach przeglądarki (po zapisaniu kopii folderu).' 'Czy instalowałeś to rozszerzenie ręcznie (np. jako programista)?' $null $null
        } else {
            $broad += ('{0}: {1} (uprawnienia: {2}; od {3})' -f $e.przegladarka, $e.nazwa, ($rp -join ', '), $e.zainstalowano)
        }
    }
    if ($broad.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'rozszerzenia' 'Rozszerzenia przeglądarek z szerokimi uprawnieniami' 'przeglądarki' $null 'Pochodzą ze sklepu, ale mogą czytać zawartość stron. Blokery reklam i menedżery haseł potrzebują tego naprawdę, inne niekoniecznie.' 'Usuń te, których nie kojarzysz (w przeglądarce: Rozszerzenia > Usuń).' 'Czy znasz wszystkie te rozszerzenia?' ($broad | Select-Object -Unique) $null
    }
    Add-Clean 'rozszerzenia' ('Rozszerzenia przeglądarek: {0}, bez szerokich uprawnień albo bez rozszerzeń spoza sklepu.' -f $exts.Count)
    $pol = @($script:D['polityki_przegladarek'] | Where-Object { $_ })
    $force = @($pol | Where-Object { $_.klucz -match '(?i)ExtensionInstallForcelist|ExtensionSettings' -or $_.nazwa -match '(?i)ExtensionInstallForcelist|ExtensionSettings' -or ($_.nazwa -eq 'policies.json' -and $_.wartosc -match '(?i)"Extensions"|ExtensionSettings') })
    $proxyPol = @($pol | Where-Object { $_.nazwa -match '(?i)^Proxy' })
    if ($force.Count -gt 0) {
        Add-Finding 'PODEJRZANE' 'polityki' 'Przeglądarka wymusza instalację rozszerzeń (polityka)' 'HKLM/HKCU\SOFTWARE\Policies' @($force | Select-Object -First 10 | ForEach-Object { ('{0}: {1} = {2}' -f $_.klucz, $_.nazwa, $_.wartosc) }) 'Na prywatnym komputerze polityka wymuszająca rozszerzenie to częsty ślad adware albo rozszerzenia szpiegującego, którego nie da się usunąć zwykłym sposobem. Przeglądarka pokazuje wtedy napis "Zarządzane przez Twoją organizację".' 'Jeśli komputer nie jest służbowy, usuniemy te klucze polityk po zrobieniu kopii rejestru.' 'Czy ten komputer jest lub był służbowy?' $null $null
    }
    if ($proxyPol.Count -gt 0) {
        Add-Finding 'PODEJRZANE' 'polityki' 'Polityka przeglądarki ustawia proxy' 'HKLM/HKCU\SOFTWARE\Policies' @($proxyPol | ForEach-Object { ('{0}: {1} = {2}' -f $_.klucz, $_.nazwa, $_.wartosc) }) 'Proxy wymuszone polityką przepuszcza cały ruch przeglądarki przez inny serwer.' 'Jeśli to nie firma, usuniemy po kopii rejestru.' $null $null $null
    }
    $otherPol = @($pol | Where-Object { $force -notcontains $_ -and $proxyPol -notcontains $_ })
    if ($otherPol.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'polityki' 'Przeglądarka ma ustawione polityki ("Zarządzane przez organizację")' 'HKLM/HKCU\SOFTWARE\Policies' @($otherPol | Select-Object -First 15 | ForEach-Object { ('{0} = {1} ({2})' -f $_.nazwa, (Limit-Text $_.wartosc 120), $_.przegladarka) }) 'Polityki zwykle ustawia firma, szkoła albo czasem program antywirusowy. Na prywatnym komputerze warto wiedzieć, skąd są.' 'Przejrzymy je razem.' 'Czy komputer jest służbowy, szkolny albo dostał go ktoś od firmy?' $null $null
    }
    $mdm = @($script:D['mdm'] | Where-Object { $_ -and $_.konto })
    if ($mdm.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'polityki' 'Windows jest zapisany do zdalnego zarządzania (MDM)' 'HKLM\SOFTWARE\Microsoft\Enrollments' @($mdm | ForEach-Object { ('dostawca: {0}, konto: {1}, stan: {2}' -f $_.dostawca, $_.konto, $_.stan) }) 'Zarządzanie MDM daje organizacji zdalną kontrolę nad ustawieniami komputera. Na sprzęcie firmowym to normalne, na prywatnym nie.' 'Jeśli to nie Twoja firma, odłączymy konto w Ustawienia > Konta > Dostęp do konta służbowego.' 'Czy znasz to konto i tę organizację?' $null $null
    }
    Add-Clean 'polityki' 'Polityki przeglądarek i MDM: brak (przeglądarka nie jest "zarządzana przez organizację").'

    # ---------- konta
    $users = @($script:D['konta'] | Where-Object { $_ })
    $admins = @($script:D['administratorzy'] | Where-Object { $_ })
    $extra = @()
    foreach ($u in $users) {
        if (-not $u.wlaczone) { continue }
        if ($u.sid -eq $script:UserSid) { continue }
        if ($u.sid -match '-(500|501|503|504)$') {
            if ($u.sid -match '-500$') { $extra += ('{0}: wbudowane konto Administrator jest WŁĄCZONE (domyślnie wyłączone)' -f $u.nazwa) }
            if ($u.sid -match '-501$') { $extra += ('{0}: konto Gość jest WŁĄCZONE' -f $u.nazwa) }
            continue
        }
        $extra += ('{0} (ostatnie logowanie: {1}, hasło zmienione: {2}, opis: {3})' -f $u.nazwa, $u.ostatnie_logowanie, $u.haslo_zmienione, $u.opis)
    }
    if ($extra.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'konta' 'Inne włączone konta na tym komputerze' 'Konta lokalne' $extra 'Każde konto to osobne drzwi do komputera. Konta domowników są w porządku, nieznane konto to sygnał.' 'Jeśli któregoś nie znasz, wyłączymy je (nie kasujemy od razu, żeby nie stracić dowodów).' 'Czy znasz wszystkie te konta i wiesz, kto z nich korzysta?' $null $null
    }
    $admExtra = @()
    foreach ($a in $admins) {
        if ($a.sid -and ($a.sid -eq $script:UserSid -or $a.sid -match '-500$')) { continue }
        if (-not $a.sid -and $a.nazwa -match ('\\' + [regex]::Escape($env:USERNAME) + '$')) { continue }
        if ($a.nazwa -match '\\(Administrator|Administrador|Administrateur)$') { continue }
        $admExtra += ('{0} ({1}, {2})' -f $a.nazwa, $a.typ, $a.zrodlo)
    }
    if ($admExtra.Count -gt 0) {
        Add-Finding 'DO_WYJASNIENIA' 'konta' 'Inne konta z uprawnieniami administratora' 'grupa Administratorzy' $admExtra 'Administrator może zainstalować wszystko, także oprogramowanie szpiegujące, i ukryć je przed Tobą.' 'Jeśli konto jest obce, odbierzemy mu uprawnienia admina.' 'Kto korzysta z tych kont?' $null $null
    }
    Add-Clean 'konta' ('Konta: {0} lokalnych, poza Twoim nie ma innych aktywnych kont ani dodatkowych administratorów.' -f $users.Count)

    # ---------- zdalny dostęp
    $zd = $script:D['zdalny_dostep']
    if ($zd) {
        $on = @()
        if ($zd.rdp_wylaczone -eq 0) { $on += ('Pulpit zdalny (RDP) jest WŁĄCZONY; usługa: ' + $zd.uslugi.TermService) }
        if ([string]$zd.uslugi.sshd -match '^Running') { $on += ('Serwer OpenSSH działa: ' + $zd.uslugi.sshd) }
        if ([string]$zd.uslugi.WinRM -match '^Running') { $on += ('Zdalne zarządzanie WinRM działa: ' + $zd.uslugi.WinRM) }
        if ([string]$zd.uslugi.RemoteRegistry -match '^Running') { $on += ('Rejestr zdalny działa: ' + $zd.uslugi.RemoteRegistry) }
        if ($on.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'zdalny' 'Włączony zdalny dostęp systemowy' 'Ustawienia > System > Pulpit zdalny, usługi' $on 'To wbudowane funkcje Windows, ale pozwalają komuś z zewnątrz zalogować się albo sterować komputerem.' 'Jeśli z tego nie korzystasz, wyłączymy (odwracalnie).' 'Czy łączysz się z tym komputerem zdalnie?' $null $null
        }
        $ra = 'wyłączona'
        if ($zd.pomoc_zdalna -eq 1) { $ra = 'dozwolona (to ustawienie domyślne Windows; jeśli nie używasz, można wyłączyć)' }
        Add-Clean 'zdalny' ('Zdalny dostęp systemowy: RDP, SSH, WinRM i Rejestr zdalny wyłączone. Pomoc zdalna: ' + $ra + '.')
    }

    # ---------- zapora
    $fw = $script:D['zapora']
    if ($fw) {
        $off = @(@($fw.profile) | Where-Object { $_ -and $_.wlaczona -eq 'False' } | ForEach-Object { $_.profil })
        if ($off.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'zapora' ('Zapora Windows wyłączona dla profilu: ' + ($off -join ', ')) 'Zabezpieczenia Windows > Zapora i ochrona sieci' $null 'Bez zapory każdy program może przyjmować połączenia z sieci. Czasem wyłącza ją inny antywirus (wtedy to normalne), czasem malware.' 'Jeśli nie masz innej zapory, włączymy ją z powrotem.' 'Czy masz antywirusa z własną zaporą albo sam ją wyłączałeś?' $null $null
        }
        foreach ($r in @(@($fw.reguly) | Where-Object { $_ })) {
            Test-Wzorce ($r.regula + ' ' + $r.program) 'reguła zapory' ('{0}: {1}' -f $r.regula, $r.program) $r.program
            if ($r.klasa -ne 'ryzykowna') { continue }
            $sig = & $sigOf $r.program
            if ($sig -and $sig.status -ne 'Valid' -and $sig.status -ne 'BrakPliku') {
                Add-Finding 'PODEJRZANE' 'zapora' ('Zapora wpuszcza połączenia do niepodpisanego programu: ' + $r.regula) 'Zapora Windows > reguły przychodzące' @(('program: ' + (Describe-File $r.program)), ('profil: {0}; grupa: {1}' -f $r.profil, $r.grupa)) 'Program z nietypowego miejsca, bez podpisu, ma otwartą furtkę w zaporze. Trojany zdalnego dostępu dodają sobie takie reguły, żeby dało się z nimi połączyć.' 'Sprawdzimy program. Jeśli jest obcy, wyłączymy regułę (da się ją włączyć z powrotem).' 'Czy znasz ten program?' $null $r.program
            }
        }
        Add-Clean 'zapora' ('Zapora: włączona, {0} reguł przychodzących dla programów, żadna nie wpuszcza niepodpisanych plików z nietypowych miejsc.' -f @($fw.reguly).Count)
    }

    # ---------- porównanie z poprzednim audytem (ten sam tryb: zwykły albo admin)
    if ($script:PrevDir) {
        $prevName = Split-Path -Leaf $script:PrevDir
        $zm = @()
        $zm += @(Get-NewItems 'autostart' { param($o) '{0}|{1}' -f $o.nazwa, $o.polecenie } { param($o) 'autostart: {0} = {1}' -f $o.nazwa, $o.polecenie })
        $zm += @(Get-NewItems 'uslugi' { param($o) '{0}|{1}' -f $o.nazwa, $o.plik } { param($o) 'usługa: {0} ({1})' -f $o.wyswietlana, $o.plik } $null -SkipIfEmpty)
        $zm += @(Get-NewItems 'zadania' { param($o) $o.sciezka + $o.nazwa } { param($o) 'zadanie: {0}{1}' -f $o.sciezka, $o.nazwa } $null -SkipIfEmpty)
        $zm += @(Get-NewItems 'programy' { param($o) '{0}|{1}' -f $o.nazwa, $o.wydawca } { param($o) 'program: {0} ({1})' -f $o.nazwa, $o.wydawca } $null -SkipIfEmpty)
        $zm += @(Get-NewItems 'rozszerzenia' { param($o) '{0}|{1}' -f $o.przegladarka, $o.id } { param($o) 'rozszerzenie {0}: {1}' -f $o.przegladarka, $o.nazwa })
        $zm += @(Get-NewItems 'certyfikaty' { param($o) $o.odcisk } { param($o) 'certyfikat główny: {0}' -f $o.podmiot } $null -SkipIfEmpty)
        $zm += @(Get-NewItems 'administratorzy' { param($o) $o.nazwa } { param($o) 'administrator: {0}' -f $o.nazwa } $null -SkipIfEmpty)
        $zm += @(Get-NewItems 'konta' { param($o) $o.nazwa } { param($o) 'aktywne konto: {0}' -f $o.nazwa } { $_.wlaczone } -SkipIfEmpty)
        $zm = @($zm | Where-Object { $_ })
        if ($zm.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'zmiany' ('Co doszło od poprzedniego audytu ({0}): {1} pozycji' -f $prevName, $zm.Count) $script:PrevDir $null 'Lista nowych wpisów w autostarcie, usługach, zadaniach, programach, rozszerzeniach, certyfikatach i kontach. Po aktualizacjach zawsze coś dochodzi, ale jeśli po sprzątaniu wróciło coś usuniętego, zobaczysz to właśnie tutaj.' 'Przejrzyj listę. Jeśli coś jest obce albo wróciło po usunięciu, daj znać.' 'Czy wszystkie te nowości to Twoje instalacje lub aktualizacje?' ($zm | Select-Object -First 60) $null
        } else {
            [void]$script:Clean.Add(('Od poprzedniego audytu ({0}) nic nowego nie doszło w autostarcie, usługach, zadaniach, programach, rozszerzeniach, certyfikatach ani kontach.' -f $prevName))
        }
    }

    # ---------- Defender
    $df = $script:D['defender']
    if ($df) {
        $av = @($df.antywirusy | Where-Object { $_ })
        $otherAv = @($av | Where-Object { $_.nazwa -notmatch '(?i)windows defender|microsoft defender' -and $_.wlaczony })
        if (-not $df.stan -and @($av | Where-Object { $_.wlaczony }).Count -eq 0) {
            Add-Finding 'DO_WYJASNIENIA' 'defender' 'Nie widać działającej ochrony antywirusowej' 'Zabezpieczenia Windows' $null 'Nie udało się odczytać stanu Defendera, a Windows nie zgłasza innego włączonego antywirusa.' 'Otwórz Zabezpieczenia Windows > Ochrona przed wirusami i zagrożeniami i sprawdź, co tam widać.' 'Czy masz zainstalowany inny antywirus?' $null $null
        }
        if ($df.stan) {
            $s = $df.stan
            if (-not $s.ochrona_czasu_rzeczywistego -and $otherAv.Count -eq 0) {
                Add-Finding 'PODEJRZANE' 'defender' 'Ochrona w czasie rzeczywistym jest wyłączona' 'Zabezpieczenia Windows' @(('antywirus: {0}, ochrona RT: {1}, tryb: {2}' -f $s.antywirus, $s.ochrona_czasu_rzeczywistego, $s.tryb)) 'Komputer nie ma działającej ochrony antywirusowej. Malware często wyłącza Defendera zaraz po wejściu.' 'Jeśli tego nie wyłączałeś, włączymy ochronę i zrobimy pełny skan.' 'Czy sam wyłączałeś ochronę w czasie rzeczywistym?' $null $null
            }
            if ($s.wiek_sygnatur_dni -gt 7 -and $otherAv.Count -eq 0) {
                Add-Finding 'DO_WYJASNIENIA' 'defender' ('Sygnatury Defendera mają {0} dni' -f $s.wiek_sygnatur_dni) 'Zabezpieczenia Windows' @(('ostatnia aktualizacja: ' + $s.sygnatury_z_dnia)) 'Nieaktualne sygnatury nie rozpoznają nowszych zagrożeń. Czasem to tylko brak internetu, czasem malware blokuje aktualizacje.' 'Zaktualizujemy sygnatury (Zabezpieczenia Windows > Ochrona przed wirusami > Aktualizacje).' $null $null $null
            }
            if ($s.ochrona_przed_manipulacja -eq $false -and $otherAv.Count -eq 0) {
                Add-Finding 'DO_WYJASNIENIA' 'defender' 'Ochrona przed naruszeniami (Tamper Protection) wyłączona' 'Zabezpieczenia Windows' $null 'Bez niej programy mogą po cichu zmieniać ustawienia Defendera.' 'Warto ją włączyć: Zabezpieczenia Windows > Ochrona przed wirusami > Zarządzaj ustawieniami.' $null $null $null
            }
        }
        foreach ($d in @($df.wykrycia | Where-Object { $_ })) {
            $name = [string]$d.zagrozenie
            $serious = $name -match '(?i)^(Backdoor|MonitoringTool|Spyware|PWS|Keylogger|HackTool|Trojan|TrojanSpy|Ransom|Exploit|Worm|VirTool|Behavior)|rat\b|remcos|njrat|bladabindi|asyncrat|nanocore|quasar|darkcomet|netwire|agenttesla|formbook|redline|lokibot|xworm|dcrat'
            $remote = $name -match '(?i)^RemoteAccess'
            $files = @($d.pliki -split ' \| ' | Where-Object { $_ })
            $still = @($files | Where-Object { ($_ -replace '^file:_', '') -match '^[a-zA-Z]:\\' -and (Test-Path -LiteralPath ($_ -replace '^file:_', '')) })
            $ev = @(('wykryto: {0}; akcja udana: {1}; aktywne: {2}; było uruchomione: {3}' -f $d.wykryto, $d.akcja_udana, $d.aktywne, $d.uruchomione), ('pliki: ' + (Limit-Text $d.pliki 400)), ('proces: {0}; użytkownik: {1}' -f $d.proces, $d.uzytkownik))
            if ($remote) {
                Add-Finding 'DO_WYJASNIENIA' 'defender' ('Defender oznaczył narzędzie zdalnego dostępu: ' + $name) 'historia ochrony Defendera' $ev 'Defender oznacza tak legalne narzędzia zdalne (np. AnyDesk), bo bywają nadużywane.' 'Powiedz, czy go używasz.' 'Czy instalowałeś to narzędzie?' $null $null
            } elseif ($serious -and ($still.Count -gt 0 -or $d.aktywne)) {
                Add-Finding 'POTWIERDZONE' 'defender' ('Wykrycie Defendera, które nadal jest na dysku lub aktywne: ' + $name) 'historia ochrony Defendera' ($ev + @($still | ForEach-Object { 'nadal istnieje: ' + $_ })) 'Defender rozpoznał zagrożenie, a plik dalej jest albo zagrożenie jest oznaczone jako aktywne.' 'Najpierw zabezpieczymy dowody i zmienimy hasła z innego urządzenia, potem usuniemy (Defender lub ręcznie z kwarantanną).' $null $null $null
            } elseif ($serious) {
                Add-Finding 'POTWIERDZONE' 'defender' ('Wykrycie Defendera w historii (już usunięte): ' + $name) 'historia ochrony Defendera' $ev 'Zagrożenie zostało usunięte, ale było na komputerze. Jeśli to trojan lub program szpiegujący, mógł zdążyć wysłać hasła.' 'Sprawdzimy, czy nic po nim nie zostało. Hasła zmień z innego, czystego urządzenia.' $null $null $null
            } else {
                [void]$script:Clean.Add(('Defender w przeszłości usunął: {0} ({1}). To niechciany program lub adware, nie narzędzie szpiegujące.' -f $name, $d.wykryto))
            }
        }
        $ex = $df.wykluczenia
        $exList = @()
        if ($ex) {
            foreach ($x in @($ex.sciezki)) { if ($x -and $x -notmatch '^N/A') { $exList += ('folder/plik: ' + $x) } }
            foreach ($x in @($ex.procesy)) { if ($x -and $x -notmatch '^N/A') { $exList += ('proces: ' + $x) } }
            foreach ($x in @($ex.rozszerzenia)) { if ($x -and $x -notmatch '^N/A') { $exList += ('rozszerzenie: ' + $x) } }
        }
        foreach ($p in @($df.polityki | Where-Object { $_ -and $_.klucz -match '\\Exclusions\\' })) { $exList += ('polityka: {0} ({1})' -f $p.nazwa, $p.klucz) }
        if ($exList.Count -gt 0) {
            $kat = 'DO_WYJASNIENIA'
            if (($exList -join ' ') -match '(?i)appdata|\\temp|programdata|users\\public|downloads|^folder/plik: [a-z]:\\?$|rozszerzenie: \.?(exe|dll|ps1|vbs|js)$|powershell|wscript|cscript|mshta|rundll32') { $kat = 'PODEJRZANE' }
            Add-Finding $kat 'defender' 'Wykluczenia w Defenderze' 'Zabezpieczenia Windows > Wykluczenia' $exList 'Wykluczone miejsca nie są skanowane. Malware często dodaje sobie wykluczenie, żeby antywirus go nie widział.' 'Jeśli nie dodawałeś ich sam (np. dla gry albo programu), usuniemy je.' 'Czy dodawałeś te wykluczenia?' $null $null
        }
        $dpol = @($df.polityki | Where-Object { $_ -and $_.nazwa -match '(?i)^Disable(AntiSpyware|AntiVirus|RealtimeMonitoring|BehaviorMonitoring|IOAVProtection|OnAccessProtection)$' -and $_.wartosc -eq '1' })
        if ($dpol.Count -gt 0) {
            Add-Finding 'PODEJRZANE' 'defender' 'Defender wyłączony przez politykę w rejestrze' 'HKLM\SOFTWARE\Policies\Microsoft\Windows Defender' @($dpol | ForEach-Object { ('{0} = {1}' -f $_.nazwa, $_.wartosc) }) 'Na domowym komputerze nikt nie powinien wyłączać Defendera polityką. To częsty ślad malware albo "optymalizatorów".' 'Usuniemy te wartości po kopii rejestru.' $null $null $null
        }
        $avTxt = (@($av | ForEach-Object { ('{0} ({1})' -f $_.nazwa, $(if ($_.wlaczony) { 'włączony' } else { 'wyłączony' })) }) -join ', ')
        Add-Clean 'defender' ('Ochrona antywirusowa działa (' + $avTxt + '), sygnatury aktualne, brak groźnych wykryć i wykluczeń.')
    }

    # ---------- dziennik zdarzeń
    $ev = $script:D['dziennik']
    if ($ev) {
        foreach ($s in @($ev.nowe_uslugi | Where-Object { $_ })) {
            Test-Wzorce ($s.usluga + ' ' + $s.plik) 'nowa usługa (dziennik)' ('{0}: {1} ({2})' -f $s.czas, $s.usluga, $s.plik) $null
            $p = Resolve-ExePath $s.plik
            if ((Get-PathClass $p) -eq 'ryzykowna' -or (Get-CmdFlags $s.plik).silne.Count -gt 0) {
                Add-Finding 'PODEJRZANE' 'dziennik' ('Nowa usługa z nietypowego miejsca: ' + $s.usluga) 'dziennik System, zdarzenie 7045' @(('{0}: {1}, konto: {2}' -f $s.czas, $s.plik, $s.konto)) 'W ostatnich 30 dniach zainstalowano usługę uruchamianą z AppData, Temp lub skryptu. Tak instalują się trojany.' 'Sprawdzimy, czy usługa nadal istnieje i do czego należy.' $null $null $p
            }
        }
        $clr = @(@($ev.czyszczenie_system) + @($ev.czyszczenie_security) | Where-Object { $_ })
        if ($clr.Count -gt 0) {
            Add-Finding 'PODEJRZANE' 'dziennik' 'Ktoś wyczyścił dziennik zdarzeń' 'dziennik System 104 / Security 1102' @($clr | ForEach-Object { ('{0}: {1}' -f $_.czas, $_.opis) }) 'Czyszczenie dzienników to typowe zacieranie śladów. Zdarza się też przy "programach do sprzątania".' 'Powiedz, czy używasz programów czyszczących (np. CCleaner).' 'Czy czyściłeś dzienniki lub używasz programu, który to robi?' $null $null
        }
        $rdp = @($ev.logowania_rdp | Where-Object { $_ })
        if ($rdp.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'dziennik' ('Logowania przez Pulpit zdalny w ostatnich 30 dniach: {0}' -f $rdp.Count) 'dziennik Security, zdarzenie 4624 typ 10' @($rdp | Select-Object -First 15 | ForEach-Object { ('{0}: konto {1} z adresu {2} ({3})' -f $_.czas, $_.konto, $_.adres, $_.stacja) }) 'Ktoś logował się do tego komputera zdalnie.' 'Jeśli to nie Ty, to bardzo ważne: wyłączymy RDP i zmienimy hasło konta.' 'Czy to Twoje logowania?' $null $null
        }
        $nk = @($ev.nowe_konta | Where-Object { $_ })
        if ($nk.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'dziennik' 'Nowe konta utworzone w ostatnich 30 dniach' 'dziennik Security, zdarzenie 4720' @($nk | ForEach-Object { ('{0}: konto {1}, utworzył {2}' -f $_.czas, $_.konto, $_.utworzyl) }) 'Nowe konto mogło zostać dodane jako furtka.' 'Jeśli to nie Ty, wyłączymy je.' 'Czy zakładałeś nowe konto?' $null $null
        }
        $exAdd = @($ev.defender | Where-Object { $_ -and $_.id -eq 5007 -and $_.opis -match '(?i)Exclusions' })
        if ($exAdd.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'dziennik' 'Zmiany wykluczeń Defendera w ostatnich 30 dniach' 'dziennik Defendera, zdarzenie 5007' @($exAdd | Select-Object -First 5 | ForEach-Object { ('{0}: {1}' -f $_.czas, (Limit-Text ($_.opis -replace '\s+', ' ') 250)) }) 'Ktoś lub coś zmieniał listę wykluczeń antywirusa.' 'Porównamy z obecną listą wykluczeń.' 'Czy zmieniałeś wykluczenia w Defenderze?' $null $null
        }
        $rtOff = @($ev.defender | Where-Object { $_ -and $_.id -eq 5001 })
        if ($rtOff.Count -gt 0) {
            Add-Finding 'DO_WYJASNIENIA' 'dziennik' ('Ochrona w czasie rzeczywistym była wyłączana ({0} razy)' -f $rtOff.Count) 'dziennik Defendera, zdarzenie 5001' @($rtOff | Select-Object -First 5 | ForEach-Object { $_.czas }) 'Wyłączenie ochrony bywa ręczne (instalacja gry), ale też jest pierwszym krokiem malware.' $null 'Czy wyłączałeś ochronę w tych terminach?' $null $null
        }
        Add-Clean 'dziennik' 'Dziennik zdarzeń (30 dni): bez podejrzanych nowych usług, czyszczenia dzienników, logowań RDP i nowych kont.'
    }

    # ---------- telefon
    $tel = $script:D['telefon']
    if ($tel) {
        $pl = $tel.lacze_z_telefonem
        $ypDirShow = Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.YourPhone_8wekyb3d8bbwe'
        $devs = @($pl.urzadzenia | Where-Object { $_ -and $_.bazy })
        if ($devs.Count -gt 0) {
            $det = @($devs | ForEach-Object { ('urządzenie {0}: bazy {1}, ostatnia zmiana {2}' -f $_.id, $_.bazy, $_.ostatnia_zmiana) })
            Add-Phone 'Łącze z telefonem (Phone Link)' ('SPAROWANE, {0} urządzenie(a)' -f $devs.Count) ($det -join '; ') 'Każdy, kto ma dostęp do tego komputera, widzi SMS-y, zdjęcia, powiadomienia i połączenia z telefonu.'
            Add-Finding 'DO_WYJASNIENIA' 'telefon' 'Telefon jest sparowany przez Łącze z telefonem' $ypDirShow $det 'Łącze z telefonem kopiuje na komputer wiadomości, zdjęcia i powiadomienia. Jeśli ktoś inny ma dostęp do tego komputera, ma też wgląd w telefon.' 'Jeśli tego nie używasz: na telefonie Ustawienia > Połączone urządzenia > Link to Windows, odłącz komputer; na komputerze w aplikacji Łącze z telefonem usuń urządzenie.' 'Czy to Ty sparowałeś telefon z tym komputerem i czy to Twój telefon?' $null $null
        } elseif ($pl.zainstalowane) {
            Add-Phone 'Łącze z telefonem (Phone Link)' 'zainstalowane, nie widać sparowanego telefonu' '' 'brak'
        } else {
            Add-Phone 'Łącze z telefonem (Phone Link)' 'nie zainstalowane' '' 'brak'
        }
        $ip = $tel.iphone
        if ($null -eq $ip.zaufane_urzadzenia -and $ip.lockdown_istnieje) {
            Add-Phone 'iPhone: zaufane urządzenia (Lockdown)' 'nie sprawdzono (wymaga admina)' 'C:\ProgramData\Apple\Lockdown' '?'
        } elseif (@($ip.zaufane_urzadzenia | Where-Object { $_ }).Count -gt 0) {
            $tr = @($ip.zaufane_urzadzenia | Where-Object { $_ } | ForEach-Object { ('{0} ({1})' -f $_.plik, $_.zmieniono) })
            Add-Phone 'iPhone: zaufane urządzenia (Lockdown)' ('{0} rekord(y) parowania' -f $tr.Count) ($tr -join '; ') 'Każdy rekord to iPhone lub iPad, który kliknął "Ufaj temu komputerowi". Ten komputer może robić z niego kopie bez pytania.'
            Add-Finding 'DO_WYJASNIENIA' 'telefon' 'iPhone lub iPad ufa temu komputerowi' 'C:\ProgramData\Apple\Lockdown' $tr 'Zaufany komputer może robić pełną kopię telefonu (wiadomości, zdjęcia, historia) bez dodatkowego pytania.' 'Jeśli to nie Twój iPhone albo nie robisz kopii: na iPhonie Ustawienia > Ogólne > Przenieś lub wyzeruj > Wyzeruj > Wyzeruj ustawienia lokalizacji i prywatności.' 'Czy podłączałeś swojego iPhone do tego komputera?' $null $null
        } elseif ($ip.lockdown_istnieje) {
            Add-Phone 'iPhone: zaufane urządzenia (Lockdown)' 'brak rekordów' '' 'brak'
        } else {
            Add-Phone 'iPhone: zaufane urządzenia (Lockdown)' 'brak (iTunes / Urządzenia Apple nie były używane)' '' 'brak'
        }
        $bk = @($ip.kopie | Where-Object { $_ })
        if ($bk.Count -gt 0) {
            $rows = @($bk | ForEach-Object { ('{0} ({1}, iOS {2}), ostatnia kopia {3}, zaszyfrowana: {4}' -f $_.urzadzenie, $_.model, $_.ios, $_.ostatnia_kopia, $_.zaszyfrowana) })
            $unenc = @($bk | Where-Object { $_.zaszyfrowana -eq 'NIE' })
            $risk = 'Kopie są zaszyfrowane.'
            if ($unenc.Count -gt 0) { $risk = 'NIEZASZYFROWANA kopia to wiadomości, zdjęcia i historia dostępne dla każdego, kto ma ten komputer.' }
            Add-Phone 'iPhone: kopie zapasowe na dysku' ('{0} kopii, niezaszyfrowanych: {1}' -f $bk.Count, $unenc.Count) ($rows -join '; ') $risk
            $kat = 'DO_WYJASNIENIA'
            Add-Finding $kat 'telefon' ('Kopie zapasowe iPhone na dysku ({0}, niezaszyfrowanych: {1})' -f $bk.Count, $unenc.Count) (@($bk | ForEach-Object { $_.folder }) -join '; ') $rows 'Kopia iPhone zawiera prawie wszystko z telefonu. Niezaszyfrowaną może przeczytać każdy, kto ma dostęp do komputera, np. programem typu iMazing.' 'Jeśli kopie są Twoje, włącz szyfrowanie kopii (Urządzenia Apple / iTunes > Szyfruj kopię lokalną) i usuń stare niezaszyfrowane. Jeśli nie są Twoje: to ważny trop, zachowaj je jako dowód.' 'Czy to kopie Twojego telefonu i czy sam je robiłeś?' $null $null
        } else {
            Add-Phone 'iPhone: kopie zapasowe na dysku' 'brak' '' 'brak'
        }
        $an = $tel.android
        $anDet = @()
        if ($an.adbkey) { $anDet += ('klucz debugowania ADB istnieje (utworzony {0}, zmieniony {1})' -f $an.adbkey.utworzono, $an.adbkey.zmieniono) }
        if (@($an.adb | Where-Object { $_ }).Count -gt 0) { $anDet += ('narzędzie adb: ' + (@($an.adb) -join ', ')) }
        if ($an.parowanie_bezprzewodowe) { $anDet += 'zapamiętane parowanie bezprzewodowego debugowania' }
        if (@($an.scrcpy | Where-Object { $_ }).Count -gt 0) { $anDet += ('scrcpy (podgląd i sterowanie ekranem telefonu): ' + (@($an.scrcpy) -join ', ')) }
        if ($anDet.Count -gt 0) {
            Add-Phone 'Android: debugowanie USB (ADB)' 'ślady użycia' ($anDet -join '; ') 'Ten komputer był autoryzowany do debugowania jakiegoś telefonu z Androidem: przez ADB da się instalować aplikacje i wyciągać dane.'
            Add-Finding 'DO_WYJASNIENIA' 'telefon' 'Ten komputer był używany do debugowania telefonu z Androidem' (Join-Path $env:USERPROFILE '.android') $anDet 'Przez ADB można zainstalować na telefonie aplikację (także stalkerware) bez sklepu i bez ikony.' 'Na telefonie: Opcje programisty > Unieważnij autoryzacje debugowania USB, potem wyłącz Debugowanie USB.' 'Czy Ty używałeś ADB, scrcpy albo programu do Androida?' $null $null
        } else {
            Add-Phone 'Android: debugowanie USB (ADB)' 'brak śladów' '' 'brak'
        }
        $btPhones = @($tel.bluetooth | Where-Object { $_ -and $_.nazwa -match '(?i)iphone|ipad|galaxy|samsung|\bsm-|xiaomi|redmi|poco|pixel|huawei|honor|oneplus|motorola|moto |oppo|realme|vivo|nokia|xperia|phone|telefon' })
        if ($btPhones.Count -gt 0) {
            Add-Phone 'Bluetooth: sparowane telefony' ('{0}' -f $btPhones.Count) ((@($btPhones | ForEach-Object { $_.nazwa }) -join ', ')) 'Sparowanie przez Bluetooth samo w sobie daje niewiele, ale jest potrzebne np. do Łącza z telefonem.'
        } else {
            Add-Phone 'Bluetooth: sparowane telefony' 'brak' '' 'brak'
        }
    }

    # ---------- trafienia w listy nazw
    foreach ($k in @($script:Hits.Keys)) {
        $h = $script:Hits[$k]
        $w = $h.w
        $kat = $w.kat
        $upg = $null
        foreach ($p in $h.pliki) {
            $s = & $sigOf $p
            if (-not $s) { $s = Get-Sig $p }
            if ((Get-PathClass $p) -eq 'ryzykowna' -and $s -and $s.status -ne 'Valid' -and $s.status -ne 'BrakPliku') { $upg = $p }
        }
        if ($kat -eq 'DO_WYJASNIENIA' -and $upg) { $kat = 'PODEJRZANE' }
        $grupa = $script:GrupaOpis[$w.grupa]
        $why = ''; $dalej = ''; $pyt = $null
        switch ($w.grupa) {
            'stalkerware' {
                $why = 'To znany program do potajemnego monitorowania (zapis klawiszy, zrzuty ekranu, podgląd wiadomości). Sama obecność nie mówi, kto go zainstalował.'
                $dalej = 'NIE odinstalowuj od razu: to może zaalarmować osobę, która go założyła. Najpierw zabezpiecz dowody (ten folder), zmień hasła z innego, czystego urządzenia, dopiero potem usuniemy go deinstalatorem i posprzątamy resztki.'
            }
            'monitoring' {
                $why = 'Legalny program do monitorowania pracowników albo kontroli rodzicielskiej. Na prywatnym komputerze dorosłej osoby, bez jej wiedzy, działa jak stalkerware.'
                $dalej = 'Jeśli to komputer służbowy albo sam to ustawiłeś, zostaw. Jeśli nie, potraktujemy to jak stalkerware (najpierw dowody i hasła).'
                $pyt = 'Czy ten program zainstalowała Twoja firma, Ty sam, albo czy to kontrola rodzicielska, o której wiesz?'
            }
            'rat' {
                $why = 'Nazwa znanej rodziny trojanów zdalnego dostępu: pozwalają przejąć komputer, kamerę i mikrofon, kraść hasła.'
                $dalej = 'Nie korzystaj z bankowości na tym komputerze do czasu wyczyszczenia. Hasła zmień z innego urządzenia. Usuniemy z kwarantanną, a potem rozważymy czystą instalację systemu.'
            }
            'zdalny' {
                $why = 'Legalne narzędzie do zdalnego sterowania komputerem. Groźne tylko wtedy, gdy go nie instalowałeś albo ktoś obcy zna dane dostępu.'
                $dalej = 'Jeśli go nie używasz, odinstalujemy je. Jeśli używasz, sprawdź w nim listę zaufanych urządzeń i nienadzorowany dostęp.'
                $pyt = ('Czy używasz {0} i wiesz, kto ma do niego dostęp?' -f $w.nazwa)
            }
            'telefon' {
                $why = 'Program, który potrafi czytać dane z telefonu (wiadomości, zdjęcia, kopie). Popularny i legalny, ale daje dostęp każdemu, kto ma ten komputer.'
                $dalej = 'Jeśli to Twoje narzędzie, zostaw. Jeśli nie, odinstalujemy i sprawdzimy, czy nie ma kopii telefonu na dysku.'
                $pyt = ('Czy instalowałeś {0}?' -f $w.nazwa)
            }
            'forensic' {
                $why = 'Profesjonalne narzędzie śledcze do wyciągania danych z telefonów i chmury (np. kopii iCloud po podaniu hasła). Na prywatnym komputerze to rzadkość.'
                $dalej = 'Jeśli nie pracujesz w tej branży, to ważny trop: zabezpiecz dowody i zmień hasło Apple ID / Google z innego urządzenia.'
                $pyt = 'Czy pracujesz w informatyce śledczej albo wiesz, skąd się tu wziął?'
            }
        }
        if ($upg) { $why += (' Do tego plik leży w nietypowym miejscu bez ważnego podpisu: ' + $upg) }
        $files = @($h.pliki | ForEach-Object { Describe-File $_ })
        Add-Finding $kat ('lista:' + $w.grupa) ('{0}: {1}' -f $grupa, $w.nazwa) (($h.pliki | Select-Object -First 3) -join '; ') (@($h.dowody) + $files) $why $dalej $pyt $null ($h.pliki | Select-Object -First 1)
        if ($w.grupa -in @('telefon', 'forensic')) { Add-Phone ('Program: ' + $w.nazwa) 'zainstalowany lub uruchomiony' (@($h.dowody | Select-Object -First 2) -join '; ') 'Może czytać dane z telefonu podłączonego do tego komputera.' }
    }
} catch {
    Write-Host ('Błąd analizy: {0}' -f $_.Exception.Message) -ForegroundColor Red
    [void]$script:Status.Add([pscustomobject]@{ test = 'analiza'; opis = 'Analiza wyników'; wynik = 'BŁĄD'; komunikat = ($_.Exception.Message + ' / ' + $_.InvocationInfo.PositionMessage); czas_s = 0; wymaga_admina = $false; zakonczono = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') })
    Save-Raw '_status' @($script:Status)
}

Save-Raw '_znaleziska' @($script:F)

# ============================================================ raport

$sys = $script:D['system']
$komp = $env:COMPUTERNAME
if ($sys) { $komp = $sys.komputer }
$dzien = (Get-Date).ToString('yyyy-MM-dd HH:mm')
$nP = @($script:F | Where-Object { $_.kat -eq 'POTWIERDZONE' }).Count
$nS = @($script:F | Where-Object { $_.kat -eq 'PODEJRZANE' }).Count
$nW = @($script:F | Where-Object { $_.kat -eq 'DO_WYJASNIENIA' }).Count
$skipped = @($script:Status | Where-Object { $_.wynik -ne 'OK' })
$phoneActive = @($script:Phone | Where-Object { $_.ryzyko -and $_.ryzyko -ne 'brak' -and $_.ryzyko -ne '?' -and $_.kanal -notlike 'Bluetooth*' })

if ($nP -gt 0) {
    $werdykt = ('Są potwierdzone ślady: {0} pozycja(e) to znane oprogramowanie szpiegujące, trojan albo wykrycie Defendera. Nie usuwaj niczego w pośpiechu, najpierw przeczytaj plan działania.' -f $nP)
    $pew = '0.85 (pewność, że coś jest na rzeczy): opiera się na rozpoznaniu konkretnego programu lub wykryciu Defendera. Nie wiadomo jeszcze, kto i kiedy to zainstalował.'
} elseif ($nS -gt 0) {
    $werdykt = ('Nie ma nic potwierdzonego, ale jest {0} podejrzana(e) pozycja(e), które trzeba obejrzeć. Często okazują się zwykłymi programami, dlatego nic nie usuwamy przed rozmową.' -f $nS)
    $pew = '0.5: zależy od Twoich odpowiedzi i od dokładniejszego sprawdzenia podejrzanych plików.'
} else {
    $werdykt = 'Nie znalazłem śladów inwigilacji, które da się wykryć tymi metodami.'
    if ($script:IsAdmin) { $pew = '0.8 (pewność, że czysto): pełny audyt jako administrator. Zależy jeszcze od odpowiedzi na pytania z sekcji DO WYJAŚNIENIA.' }
    else { $pew = '0.65 (pewność, że czysto): audyt bez uprawnień administratora, część testów pominięta. Uruchom wersję admin, żeby podnieść pewność.' }
}
if ($phoneActive.Count -gt 0) { $werdykt += (' Z tego komputera jest {0} kanał(y) dostępu do telefonu, opisane w sekcji Telefon.' -f $phoneActive.Count) }
else { $werdykt += ' Nie widać, żeby coś na tym komputerze miało dostęp do telefonu.' }
if ($nW -gt 0) { $werdykt += (' Do tego {0} pozycja(e) DO WYJAŚNIENIA: to zwykle legalne rzeczy, ale tylko Ty wiesz, czy są Twoje.' -f $nW) }

$limits = 'Granice tego audytu: dobrze wykrywa komercyjne stalkerware, keyloggery, narzędzia zdalne, typowe RAT-y i kanały dostępu do telefonu. Nie wykryje z pewnością zaawansowanego malware działającego w jądrze systemu lub firmware ani rządowego oprogramowania szpiegującego na telefonie. "Nic nie znaleziono" znaczy "nic, co da się wykryć tymi metodami", a nie gwarancję. Ocena jest automatyczna (reguły), więc PODEJRZANE i DO WYJAŚNIENIA najlepiej omówić, zanim cokolwiek zostanie zmienione.'

$plan = New-Object System.Collections.ArrayList
if ($nP -gt 0 -or $nS -gt 0) {
    [void]$plan.Add('Jeśli podejrzewasz konkretną osobę (partner, ex, rodzina, pracodawca), pamiętaj: usunięcie programu może ją zaalarmować. Najpierw zabezpiecz dowody (skopiuj cały ten folder audytu na pendrive), potem z INNEGO, czystego urządzenia zmień hasła do poczty, Apple ID lub konta Google, banku i komunikatorów i włącz weryfikację dwuetapową. Dopiero potem usuwamy.')
    [void]$plan.Add('W razie zagrożenia: 112. Przemoc lub nękanie: Niebieska Linia 800 120 002 (całodobowo, bezpłatnie). Incydent komputerowy: zgłoszenie do CERT Polska przez incydent.cert.pl.')
}
if ($nP -gt 0) { [void]$plan.Add('Do czasu wyczyszczenia nie loguj się na tym komputerze do banku ani poczty.') }
if ($nW -gt 0) { [void]$plan.Add('Odpowiedz na pytania z sekcji DO WYJAŚNIENIA. Większość okaże się Twoimi programami i spadnie z listy.') }
if (-not $script:IsAdmin) { [void]$plan.Add('Uruchom pełny audyt jako administrator (plik uruchom-audyt-admin.bat): dojdą subskrypcje WMI, wykluczenia Defendera, logowania RDP, nowe konta i zaufane iPhone''y.') }
if (-not $iocUsed) { [void]$plan.Add('Opcjonalnie: uruchom ponownie z pobraniem listy domen stalkerware (odpowiedz "t" na pytanie na początku), żeby porównać ją z pamięcią DNS.') }
[void]$plan.Add('Naprawa dopiero po omówieniu, pozycja po pozycji: najpierw punkt przywracania systemu i kopia kluczy rejestru (folder kopia-rejestru), pliki trafiają do kwarantanny (folder kwarantanna), a nie od razu do kosza. Na tym etapie nic nie zostało zmienione.')
if ($phoneActive.Count -gt 0) { [void]$plan.Add('Telefon: odepnij Łącze z telefonem i nieznane komputery; na iPhonie Ustawienia > Ogólne > Przenieś lub wyzeruj > Wyzeruj > Wyzeruj ustawienia lokalizacji i prywatności (usuwa zaufane komputery); na Androidzie wyłącz debugowanie USB i unieważnij autoryzacje; stare niezaszyfrowane kopie iPhone usuń albo włącz szyfrowanie.') }
[void]$plan.Add('Drugie zdanie skanera, gdy będziesz gotowy: skan offline Microsoft Defender (Zabezpieczenia Windows > Ochrona przed wirusami > Opcje skanowania > Skanowanie offline). Uwaga: restartuje komputer.')

# Porządki: na razie tylko pomiar
$perf = @()
$wy = $script:D['wydajnosc']
if ($wy) {
    foreach ($d in @($wy.dyski | Where-Object { $_ })) {
        $proc = 0
        if ($d.rozmiar_gb -gt 0) { $proc = [math]::Round(100 * $d.wolne_gb / $d.rozmiar_gb, 0) }
        $uw = ''
        if ($proc -lt 15) { $uw = ' MAŁO MIEJSCA: to realnie spowalnia system.' }
        $perf += ('Dysk {0}: wolne {1} GB z {2} GB ({3}%).{4}' -f $d.dysk, $d.wolne_gb, $d.rozmiar_gb, $proc, $uw)
    }
    foreach ($d in @($wy.dyski_fizyczne | Where-Object { $_ })) {
        $uw = ''
        if ($d.zdrowie -and $d.zdrowie -ne 'Healthy') { $uw = ' UWAGA: dysk zgłasza problem ze zdrowiem. Żadne sprzątanie tego nie naprawi, dysk trzeba będzie wymienić (najpierw kopia danych!).' }
        $perf += ('Dysk fizyczny {0} ({1}, {2} GB): zdrowie {3}, stan {4}.{5}' -f $d.nazwa, $d.typ, $d.rozmiar_gb, $d.zdrowie, $d.stan, $uw)
    }
    foreach ($d in @($wy.smart | Where-Object { $_ -and $_.status -and $_.status -ne 'OK' })) { $perf += ('SMART {0}: {1}. Dysk może umierać, zrób kopię danych.' -f $d.model, $d.status) }
    foreach ($r in @($wy.niezawodnosc | Where-Object { $_ })) { $perf += ('Licznik niezawodności dysku: temperatura {0}, zużycie {1}%, błędy odczytu {2}, zapisu {3}, godziny pracy {4}.' -f $r.temperatura, $r.zuzycie_proc, $r.bledy_odczytu, $r.bledy_zapisu, $r.godziny_pracy) }
    $perf += ('Pamięć RAM: wolne {0} GB z {1} GB.' -f $wy.ram_wolne_gb, $wy.ram_razem_gb)
    if ($wy.ostatnia_aktualizacja) { $perf += ('Ostatnia zainstalowana aktualizacja Windows: {0} ({1}).' -f $wy.ostatnia_aktualizacja, $wy.ostatnia_aktualizacja_kb) }
    $junk = @($wy.foldery | Where-Object { $_ -and $_.nazwa -match 'tymczasowe|Windows Update|Windows\.old|Pamięć podręczna|Miniatury|Kosz' -and $_.bajty -gt 0 } | Sort-Object bajty -Descending)
    $junkSum = [int64]0
    foreach ($j in $junk) { $junkSum += [int64]$j.bajty }
    $perf += ('Do bezpiecznego posprzątania (po Twojej zgodzie, każde osobno): razem około {0}.' -f (Format-Size $junkSum))
    foreach ($j in $junk) { $perf += ('    {0}: {1}' -f $j.nazwa, $j.rozmiar) }
    $big = @($wy.foldery | Where-Object { $_ -and $_.nazwa -notmatch 'tymczasowe|Windows Update|Windows\.old|Pamięć podręczna|Miniatury|Kosz' } | Sort-Object bajty -Descending)
    $perf += 'Największe foldery użytkownika (tych nie ruszamy bez pytania):'
    foreach ($j in $big) { $perf += ('    {0}: {1}' -f $j.nazwa, $j.rozmiar) }
    $asOn = @($script:D['autostart'] | Where-Object { $_ -and -not $_.wylaczony })
    $perf += ('Programy startujące z systemem (włączone): {0}. Ciężkie pozycje można wyłączyć w Menedżerze zadań, karta Uruchamianie (odwracalnie).' -f $asOn.Count)
    $orph = @($script:D['autostart'] | Where-Object { $_ -and $_.plik -and (& $sigOf $_.plik) -and (& $sigOf $_.plik).status -eq 'BrakPliku' })
    foreach ($o in $orph) { $perf += ('    Martwy wpis autostartu (plik nie istnieje): {0} = {1}' -f $o.nazwa, $o.polecenie) }
    $perf += ('Najbardziej obciążające procesy (czas procesora od startu): ' + ((@($wy.top_cpu) | Select-Object -First 5 | ForEach-Object { ('{0} {1} s / {2} MB' -f $_.proces, $_.cpu_s, $_.ram_mb) }) -join ', '))
    $perf += ('Najwięcej pamięci: ' + ((@($wy.top_ram) | Select-Object -First 5 | ForEach-Object { ('{0} {1} MB' -f $_.proces, $_.ram_mb) }) -join ', '))
    $bt = @($wy.start_systemu | Where-Object { $_ -and $_.start_s -gt 0 })
    if ($bt.Count -gt 0) {
        $avg = [math]::Round((($bt | Measure-Object start_s -Average).Average), 0)
        $uw = ''
        if ($avg -gt 90) { $uw = ' To długo: winne są zwykle programy w autostarcie albo wolny dysk.' }
        $perf += ('Start systemu (ostatnie {0} uruchomienia): średnio {1} s do pulpitu.{2}' -f $bt.Count, $avg, $uw)
    }
    foreach ($s in @($wy.spowalniajace_start | Where-Object { $_ -and $_.opoznienie_s -gt 0 })) { $perf += ('    Spowalnia start o {0} s: {1} ({2})' -f $s.opoznienie_s, $s.program, $s.plik) }
    $perf += 'Naprawy systemu (sfc /scannow, DISM, chkdsk) i sprzątanie zrobimy po sekcji usuwania zagrożeń, każdą po pokazaniu, co zrobi. Nie używamy "czyścicieli rejestru".'
}

$notChecked = @()
foreach ($s in $skipped) { $notChecked += ('{0}: {1} {2}' -f $s.opis, $s.wynik, $s.komunikat) }
foreach ($s in @($script:Status | Where-Object { $_.wynik -eq 'OK' -and $_.komunikat })) { $notChecked += ('{0}: częściowo, {1}' -f $s.opis, $s.komunikat) }
if (-not $iocUsed) { $notChecked += 'Porównanie z publiczną listą domen stalkerware: nie pobrano listy (bez zgody nie łączę się z internetem).' }
$notChecked += 'Historia przeglądarki: celowo nie przeglądana (zbyt głęboka ingerencja jak na ten audyt).'
$notChecked += 'Sam telefon: komputer pokazuje tylko kanały dostępu. Telefon sprawdzimy osobno, jeśli zechcesz i go podłączysz.'
if ($sys -and $sys.uzytkownik_pulpitu -and $sys.uzytkownik -and ($sys.uzytkownik_pulpitu -ne $sys.uzytkownik)) { $notChecked += ('Uwaga: audyt działał jako {0}, a zalogowany jest {1}. Ustawienia kamery, rozszerzenia i autostart użytkownika dotyczą konta {0}.' -f $sys.uzytkownik, $sys.uzytkownik_pulpitu) }

# Najważniejsze teraz: maksymalnie 3 konkretne kroki na górze raportu
$top = @()
foreach ($f in @($script:F | Where-Object { $_.kat -eq 'POTWIERDZONE' } | Select-Object -First 2)) { $top += ('Zabezpiecz dowody i zmień hasła z innego urządzenia, dopiero potem usuwamy: ' + $f.co) }
foreach ($f in @($script:F | Where-Object { $_.kat -eq 'PODEJRZANE' })) { if ($top.Count -ge 3) { break }; $top += ('Obejrzyjmy razem: ' + $f.co) }
foreach ($p in $phoneActive) { if ($top.Count -ge 3) { break }; $top += ('Telefon: {0} ({1}). Upewnij się, że to Twoje.' -f $p.kanal, $p.stan) }
if ($top.Count -lt 3 -and $nW -gt 0) { $top += ('Odpowiedz na {0} pytania z sekcji DO WYJAŚNIENIA.' -f $nW) }
if ($top.Count -lt 3 -and -not $script:IsAdmin) { $top += 'Uruchom pełny audyt jako administrator (uruchom-audyt-admin.bat).' }
if ($top.Count -eq 0) { $top += 'Nic pilnego. Uruchom audyt ponownie za kilka tygodni: raport pokaże, co doszło od dziś.' }

# ---------- Markdown
function Format-MdText([string]$t) { if (-not $t) { return '' }; return ($t -replace '`', "'") }

$md = New-Object System.Text.StringBuilder
[void]$md.AppendLine(('# Audyt inwigilacji: {0}, {1}' -f $komp, $dzien))
[void]$md.AppendLine('')
$sysLine = ''
if ($sys) { $sysLine = ('{0} ({1}, kompilacja {2}), konto: {3}, administrator: {4}' -f $sys.system, $sys.architektura, $sys.kompilacja, $sys.uzytkownik, $(if ($script:IsAdmin) { 'tak' } else { 'nie' })) }
[void]$md.AppendLine(('_{0}. Raport wygenerowany automatycznie przez audyt.ps1, surowe dane w folderze raw._' -f $sysLine))
[void]$md.AppendLine('')
[void]$md.AppendLine('## Werdykt')
[void]$md.AppendLine('')
[void]$md.AppendLine($werdykt)
[void]$md.AppendLine('')
[void]$md.AppendLine(('**Poziom pewności:** {0}' -f $pew))
[void]$md.AppendLine('')
[void]$md.AppendLine(('**POTWIERDZONE: {0} | PODEJRZANE: {1} | DO WYJAŚNIENIA: {2}**' -f $nP, $nS, $nW))
[void]$md.AppendLine('')
[void]$md.AppendLine('**Najważniejsze teraz:**')
[void]$md.AppendLine('')
$i = 0
foreach ($t in $top) { $i++; [void]$md.AppendLine(('{0}. {1}' -f $i, (Format-MdText $t))) }
[void]$md.AppendLine('')

$secs = @(
    @{ k = 'POTWIERDZONE'; t = 'POTWIERDZONE' },
    @{ k = 'PODEJRZANE'; t = 'PODEJRZANE' },
    @{ k = 'DO_WYJASNIENIA'; t = 'DO WYJAŚNIENIA (pytania do Ciebie)' }
)
foreach ($sec in $secs) {
    [void]$md.AppendLine('## ' + $sec.t)
    [void]$md.AppendLine('')
    $items = @($script:F | Where-Object { $_.kat -eq $sec.k })
    if ($items.Count -eq 0) { [void]$md.AppendLine('brak'); [void]$md.AppendLine(''); continue }
    $i = 0
    foreach ($f in $items) {
        $i++
        [void]$md.AppendLine(('### {0}. {1}' -f $i, (Format-MdText $f.co)))
        [void]$md.AppendLine('')
        if ($f.pytanie) { [void]$md.AppendLine(('**Pytanie:** {0}' -f (Format-MdText $f.pytanie))); [void]$md.AppendLine('') }
        if ($f.gdzie) { [void]$md.AppendLine(('* **Gdzie:** `{0}`' -f (Format-MdText $f.gdzie))) }
        foreach ($d in @($f.dowod)) { if ($d) { [void]$md.AppendLine(('* **Dowód:** `{0}`' -f (Format-MdText $d))) } }
        if ($f.dlaczego) { [void]$md.AppendLine(('* **Dlaczego ta kategoria:** {0}' -f (Format-MdText $f.dlaczego))) }
        if ($f.dalej) { [void]$md.AppendLine(('* **Co dalej:** {0}' -f (Format-MdText $f.dalej))) }
        if (@($f.tabela).Count -gt 0) {
            [void]$md.AppendLine('')
            foreach ($r in @($f.tabela)) { if ($r) { [void]$md.AppendLine(('    {0}' -f (Format-MdText $r))) } }
        }
        [void]$md.AppendLine('')
    }
}

[void]$md.AppendLine('## Telefon: co ma do niego dostęp z tego komputera')
[void]$md.AppendLine('')
[void]$md.AppendLine('| Kanał | Stan | Szczegóły | Co to znaczy |')
[void]$md.AppendLine('|---|---|---|---|')
foreach ($p in $script:Phone) { [void]$md.AppendLine(('| {0} | {1} | {2} | {3} |' -f (Format-MdText $p.kanal), (Format-MdText $p.stan), ((Format-MdText $p.szczegoly) -replace '\|', '/'), (Format-MdText $p.ryzyko))) }
[void]$md.AppendLine('')
[void]$md.AppendLine('## Czego nie sprawdziłem i dlaczego')
[void]$md.AppendLine('')
foreach ($n in $notChecked) { [void]$md.AppendLine('* ' + (Format-MdText $n)) }
[void]$md.AppendLine('')
[void]$md.AppendLine($limits)
[void]$md.AppendLine('')
[void]$md.AppendLine('## Plan działania')
[void]$md.AppendLine('')
$i = 0
foreach ($p in $plan) { $i++; [void]$md.AppendLine(('{0}. {1}' -f $i, (Format-MdText $p))) }
[void]$md.AppendLine('')
[void]$md.AppendLine('## Porządki i wydajność (wypełniane po sekcji 7)')
[void]$md.AppendLine('')
[void]$md.AppendLine('Na razie tylko pomiar, nic nie zostało usunięte ani zmienione.')
[void]$md.AppendLine('')
foreach ($p in $perf) {
    if ($p.StartsWith('    ')) { [void]$md.AppendLine('    * ' + (Format-MdText $p.Trim())) } else { [void]$md.AppendLine('* ' + (Format-MdText $p)) }
}
[void]$md.AppendLine('')
[void]$md.AppendLine('## Sprawdzone, bez uwag')
[void]$md.AppendLine('')
if ($script:Clean.Count -eq 0) { [void]$md.AppendLine('brak') }
foreach ($c in $script:Clean) { [void]$md.AppendLine('* ' + (Format-MdText $c)) }
[void]$md.AppendLine('')
$mdPath = Join-Path $script:OutDir 'RAPORT.md'
[IO.File]::WriteAllText($mdPath, $md.ToString(), $script:Utf8)

# ---------- HTML (jeden plik, bez zewnętrznych zasobów)
function Format-HtmlText([string]$t) { if (-not $t) { return '' }; return [System.Net.WebUtility]::HtmlEncode($t) }

$css = @'
body{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1d2433;line-height:1.5;background:#fafbfc}
h1{font-size:1.6em;margin-bottom:4px}h2{margin-top:32px;border-bottom:2px solid #e3e7ee;padding-bottom:4px}
.meta{color:#5b6475;font-size:.9em}.verdict{background:#fff;border:1px solid #d9dee8;border-radius:8px;padding:14px 18px}
.card{background:#fff;border:1px solid #d9dee8;border-left:6px solid #999;border-radius:6px;padding:10px 14px;margin:12px 0}
.k-POTWIERDZONE{border-left-color:#c62828}.k-PODEJRZANE{border-left-color:#ef8f00}.k-DO_WYJASNIENIA{border-left-color:#1e6fd9}
.card h3{margin:2px 0 8px;font-size:1.05em}.q{background:#eef4ff;padding:6px 10px;border-radius:4px;margin-bottom:6px}
code{background:#f1f3f6;padding:1px 4px;border-radius:3px;font-size:.88em;word-break:break-all}
table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #d9dee8;padding:6px 8px;text-align:left;vertical-align:top;font-size:.92em}
th{background:#f1f3f6}.counts span{display:inline-block;margin-right:14px;font-weight:600}.c1{color:#c62828}.c2{color:#ef8f00}.c3{color:#1e6fd9}
ul.tab{font-family:Consolas,monospace;font-size:.85em;background:#f7f8fa;padding:8px 8px 8px 28px;border-radius:4px}
.top{background:#fff8e6;border:1px solid #f0d79a;border-radius:6px;padding:8px 14px;margin-top:10px}.top ol{margin:6px 0}
@media print{body{background:#fff;max-width:none}.card,.verdict,.top{break-inside:avoid}}
'@
$h = New-Object System.Text.StringBuilder
[void]$h.AppendLine('<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>Audyt inwigilacji: ' + (Format-HtmlText $komp) + '</title><style>' + $css + '</style></head><body>')
[void]$h.AppendLine('<h1>Audyt inwigilacji: ' + (Format-HtmlText $komp) + ', ' + (Format-HtmlText $dzien) + '</h1>')
[void]$h.AppendLine('<div class="meta">' + (Format-HtmlText $sysLine) + '. Raport automatyczny, surowe dane w folderze raw.</div>')
[void]$h.AppendLine('<h2>Werdykt</h2><div class="verdict"><p>' + (Format-HtmlText $werdykt) + '</p><p><b>Poziom pewności:</b> ' + (Format-HtmlText $pew) + '</p>')
[void]$h.AppendLine(('<div class="counts"><span class="c1">POTWIERDZONE: {0}</span><span class="c2">PODEJRZANE: {1}</span><span class="c3">DO WYJAŚNIENIA: {2}</span></div>' -f $nP, $nS, $nW))
[void]$h.AppendLine('<div class="top"><b>Najważniejsze teraz:</b><ol>')
foreach ($t in $top) { [void]$h.AppendLine('<li>' + (Format-HtmlText $t) + '</li>') }
[void]$h.AppendLine('</ol></div></div>')
foreach ($sec in $secs) {
    [void]$h.AppendLine('<h2>' + (Format-HtmlText $sec.t) + '</h2>')
    $items = @($script:F | Where-Object { $_.kat -eq $sec.k })
    if ($items.Count -eq 0) { [void]$h.AppendLine('<p>brak</p>'); continue }
    $i = 0
    foreach ($f in $items) {
        $i++
        [void]$h.AppendLine('<div class="card k-' + $sec.k + '"><h3>' + $i + '. ' + (Format-HtmlText $f.co) + '</h3>')
        if ($f.pytanie) { [void]$h.AppendLine('<div class="q"><b>Pytanie:</b> ' + (Format-HtmlText $f.pytanie) + '</div>') }
        [void]$h.AppendLine('<ul>')
        if ($f.gdzie) { [void]$h.AppendLine('<li><b>Gdzie:</b> <code>' + (Format-HtmlText $f.gdzie) + '</code></li>') }
        foreach ($d in @($f.dowod)) { if ($d) { [void]$h.AppendLine('<li><b>Dowód:</b> <code>' + (Format-HtmlText $d) + '</code></li>') } }
        if ($f.dlaczego) { [void]$h.AppendLine('<li><b>Dlaczego ta kategoria:</b> ' + (Format-HtmlText $f.dlaczego) + '</li>') }
        if ($f.dalej) { [void]$h.AppendLine('<li><b>Co dalej:</b> ' + (Format-HtmlText $f.dalej) + '</li>') }
        [void]$h.AppendLine('</ul>')
        if (@($f.tabela).Count -gt 0) {
            [void]$h.AppendLine('<ul class="tab">')
            foreach ($r in @($f.tabela)) { if ($r) { [void]$h.AppendLine('<li>' + (Format-HtmlText $r) + '</li>') } }
            [void]$h.AppendLine('</ul>')
        }
        [void]$h.AppendLine('</div>')
    }
}
[void]$h.AppendLine('<h2>Telefon: co ma do niego dostęp z tego komputera</h2><table><tr><th>Kanał</th><th>Stan</th><th>Szczegóły</th><th>Co to znaczy</th></tr>')
foreach ($p in $script:Phone) { [void]$h.AppendLine('<tr><td>' + (Format-HtmlText $p.kanal) + '</td><td>' + (Format-HtmlText $p.stan) + '</td><td>' + (Format-HtmlText $p.szczegoly) + '</td><td>' + (Format-HtmlText $p.ryzyko) + '</td></tr>') }
[void]$h.AppendLine('</table>')
[void]$h.AppendLine('<h2>Czego nie sprawdziłem i dlaczego</h2><ul>')
foreach ($n in $notChecked) { [void]$h.AppendLine('<li>' + (Format-HtmlText $n) + '</li>') }
[void]$h.AppendLine('</ul><p>' + (Format-HtmlText $limits) + '</p>')
[void]$h.AppendLine('<h2>Plan działania</h2><ol>')
foreach ($p in $plan) { [void]$h.AppendLine('<li>' + (Format-HtmlText $p) + '</li>') }
[void]$h.AppendLine('</ol>')
[void]$h.AppendLine('<h2>Porządki i wydajność (wypełniane po sekcji 7)</h2><p>Na razie tylko pomiar, nic nie zostało usunięte ani zmienione.</p><ul>')
foreach ($p in $perf) {
    if ($p.StartsWith('    ')) { [void]$h.AppendLine('<li style="margin-left:24px;list-style:circle">' + (Format-HtmlText $p.Trim()) + '</li>') } else { [void]$h.AppendLine('<li>' + (Format-HtmlText $p) + '</li>') }
}
[void]$h.AppendLine('</ul>')
[void]$h.AppendLine('<h2>Sprawdzone, bez uwag</h2><ul>')
if ($script:Clean.Count -eq 0) { [void]$h.AppendLine('<li>brak</li>') }
foreach ($c in $script:Clean) { [void]$h.AppendLine('<li>' + (Format-HtmlText $c) + '</li>') }
[void]$h.AppendLine('</ul></body></html>')
$htmlPath = Join-Path $script:OutDir 'raport.html'
[IO.File]::WriteAllText($htmlPath, $h.ToString(), $script:Utf8)

# Paczka dowodów: sumy SHA256 każdego pliku i jedno archiwum, które łatwo skopiować na pendrive.
# Suma samego archiwum pozwala później wykazać, że nikt nic w nim nie zmienił.
$zipPath = Join-Path $script:OutDir 'dowody.zip'
$zipHash = ''
try {
    $manifest = Join-Path $script:OutDir 'dowody-sha256.txt'
    $lines = @(('# Audyt {0}, {1}, wygenerowano {2}' -f $komp, $script:UserName, $dzien))
    foreach ($f in Get-ChildItem -LiteralPath $script:OutDir -Recurse -File | Where-Object { $_.FullName -ne $manifest -and $_.Extension -ne '.zip' }) {
        $lines += ('{0}  {1}' -f (Get-Sha256 $f.FullName), $f.FullName.Substring($script:OutDir.Length + 1))
    }
    [IO.File]::WriteAllLines($manifest, $lines, $script:Utf8)
    Compress-Archive -Path $script:RawDir, $mdPath, $htmlPath, $manifest -DestinationPath $zipPath -Force -ErrorAction Stop
    $zipHash = Get-Sha256 $zipPath
    [IO.File]::WriteAllText(($zipPath + '.sha256'), ('{0}  dowody.zip' -f $zipHash), $script:Utf8)
} catch {
    Write-Host ('Nie udało się spakować dowodów: {0}' -f $_.Exception.Message) -ForegroundColor Yellow
}

# ============================================================ podsumowanie

Write-Host ''
Write-Host 'Gotowe. Niczego nie zmieniłem.' -ForegroundColor Cyan
Write-Host ('  POTWIERDZONE:   {0}' -f $nP) -ForegroundColor $(if ($nP -gt 0) { 'Red' } else { 'Green' })
Write-Host ('  PODEJRZANE:     {0}' -f $nS) -ForegroundColor $(if ($nS -gt 0) { 'Yellow' } else { 'Green' })
Write-Host ('  DO WYJAŚNIENIA: {0}' -f $nW)
Write-Host ('  Pominięte testy: {0}' -f $skipped.Count)
foreach ($f in @($script:F | Where-Object { $_.kat -eq 'POTWIERDZONE' -or $_.kat -eq 'PODEJRZANE' } | Select-Object -First 8)) {
    $kol = 'Yellow'
    if ($f.kat -eq 'POTWIERDZONE') { $kol = 'Red' }
    Write-Host ('    [{0}] {1}' -f $f.kat, $f.co) -ForegroundColor $kol
}
Write-Host ''
Write-Host 'Najważniejsze teraz:' -ForegroundColor Cyan
$i = 0
foreach ($t in $top) { $i++; Write-Host ('  {0}. {1}' -f $i, $t) }
Write-Host ''
Write-Host ('Raport: {0}' -f $htmlPath)
Write-Host ('        {0}' -f $mdPath)
Write-Host ('Surowe dane (dowody): {0}' -f $script:RawDir)
if ($zipHash) { Write-Host ('Paczka dowodów: {0} (SHA256 {1})' -f $zipPath, $zipHash) }
if ($script:PrevDir) { Write-Host ('Porównano z poprzednim audytem: {0}' -f $script:PrevDir) }
if (-not $script:IsAdmin) { Write-Host 'Następny krok: uruchom uruchom-audyt-admin.bat, żeby zrobić pełny audyt.' -ForegroundColor Yellow }
if (-not $NieOtwieraj) { try { Invoke-Item -LiteralPath $htmlPath } catch {} }
