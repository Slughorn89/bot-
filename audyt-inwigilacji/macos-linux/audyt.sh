#!/bin/bash
# Audyt inwigilacji dla macOS i Linuksa. Faza czytania: niczego nie usuwa i nie zmienia.
# Użycie: bash audyt.sh [-o FOLDER] [--ioc] [--bez-pytan]
#   najpierw bez sudo, potem pełny audyt: sudo bash audyt.sh
# Zgodny z bash 3.2 (macOS): bez tablic asocjacyjnych i bez mapfile.

OUT=""
IOC=0
ASK=1
while [ $# -gt 0 ]; do
    case "$1" in
        -o|--out) OUT="$2"; shift 2 ;;
        --ioc) IOC=1; shift ;;
        --bez-pytan) ASK=0; shift ;;
        -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
        *) echo "Nieznana opcja: $1"; exit 1 ;;
    esac
done

OS=$(uname -s)
IS_ROOT=0
[ "$(id -u)" = "0" ] && IS_ROOT=1
REAL_USER=${SUDO_USER:-$(id -un)}
UHOME="$HOME"
if [ -n "${SUDO_USER:-}" ]; then
    if [ "$OS" = "Darwin" ]; then
        UHOME=$(dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
    else
        UHOME=$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)
    fi
    [ -n "$UHOME" ] || UHOME="$HOME"
fi

STAMP=$(date +%Y-%m-%d_%H%M)
if [ -z "$OUT" ]; then
    OUT="$UHOME/audyt-inwigilacji/$STAMP"
    [ "$IS_ROOT" = 1 ] && OUT="${OUT}_sudo"
fi
RAW="$OUT/raw"
mkdir -p "$RAW" "$OUT/skrypty" "$OUT/kwarantanna" "$OUT/kopia-rejestru" || { echo "Nie mogę utworzyć $OUT"; exit 1; }
cp "$0" "$OUT/skrypty/" 2>/dev/null

# Poprzedni audyt w tym samym trybie (bez sudo / z sudo), żeby pokazać, co doszło od tamtej pory
PREV=""
while IFS= read -r d; do
    [ "$d" = "$OUT" ] && continue
    [ -f "$d/raw/_status.json" ] || continue
    case "$d" in *_sudo) m=1 ;; *) m=0 ;; esac
    [ "$m" = "$IS_ROOT" ] || continue
    PREV="$d"; break
done < <(ls -1d "$(dirname "$OUT")"/*/ 2>/dev/null | sed 's|/$||' | LC_ALL=C sort -r)

STATUS_TMP="$RAW/.status.tmp"
FIND="$RAW/_znaleziska.tsv"
CLEAN="$RAW/_czysto.txt"
PHONE="$RAW/_telefon.tsv"
NOTES="$RAW/.note"
: > "$STATUS_TMP"; : > "$FIND"; : > "$CLEAN"; : > "$PHONE"
SEP=$(printf '\037')
FS=$(printf '\036')
TAB=$(printf '\t')

# ============================================================ pomocnicze

have() { command -v "$1" >/dev/null 2>&1; }
# du z limitem czasu (ogromne foldery nie zawieszą audytu)
dsize() { if have timeout; then timeout 60 du -sh "$@" 2>/dev/null; else du -sh "$@" 2>/dev/null; fi; }
note() { printf '%s; ' "$*" >> "$NOTES"; }
json_esc() { printf '%s' "$1" | tr '\n\t\r' '   ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
one_line() { printf '%s' "$1" | tr '\t\r' '  ' | tr '\n' "$SEP" | sed "s/$SEP\$//"; }
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

mtime() {
    if [ "$OS" = "Darwin" ]; then stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$1" 2>/dev/null
    else stat -c '%y' "$1" 2>/dev/null | cut -c1-16; fi
}

# kat obszar co gdzie dowod(wiele linii) dlaczego dalej [pytanie]
add_finding() {
    printf "%s$FS%s$FS%s$FS%s$FS%s$FS%s$FS%s$FS%s\n" "$1" "$2" "$(one_line "$3")" "$(one_line "$4")" "$(one_line "$5")" "$(one_line "$6")" "$(one_line "$7")" "$(one_line "${8:-}")" >> "$FIND"
}
add_clean() {
    # dodaje tylko, jeśli obszar nie ma znalezisk
    if ! cut -d"$FS" -f2 "$FIND" | grep -qx "$1"; then echo "$2" >> "$CLEAN"; fi
}
add_phone() { printf "%s$FS%s$FS%s$FS%s\n" "$1" "$2" "$(one_line "$3")" "$4" >> "$PHONE"; }

# klasa ścieżki: system / aplikacje / ryzykowna / inna
path_class() {
    case "$1" in
        /tmp/*|/private/tmp/*|/var/tmp/*|/private/var/tmp/*|/dev/shm/*|/Users/Shared/*|"$UHOME"/Downloads/*|"$UHOME"/Desktop/*|"$UHOME"/Library/Application\ Support/*|"$UHOME"/.local/share/Trash/*|"$UHOME"/.cache/*) echo ryzykowna ;;
        /System/*|/usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|/opt/homebrew/*|/snap/*|/nix/*) echo system ;;
        /Applications/*|"$UHOME"/Applications/*|/Library/*|/opt/*) echo aplikacje ;;
        "") echo brak ;;
        *) echo inna ;;
    esac
}

# Podpis (macOS: codesign) lub przynależność do pakietu (Linux: dpkg/rpm). Wynik: ok|brak|nieistnieje + opis
sig_check() {
    p="$1"
    [ -e "$p" ] || { echo "nieistnieje${TAB}plik nie istnieje"; return; }
    if [ "$OS" = "Darwin" ]; then
        out=$(codesign -dv --verbose=2 "$p" 2>&1)
        if printf '%s' "$out" | grep -q '^Authority='; then
            auth=$(printf '%s' "$out" | grep '^Authority=' | head -1 | cut -d= -f2-)
            if codesign --verify "$p" >/dev/null 2>&1; then echo "ok${TAB}podpisany: $auth"
            else echo "brak${TAB}podpis NIEPOPRAWNY ($auth)"; fi
        elif printf '%s' "$out" | grep -q 'Signature=adhoc'; then
            echo "brak${TAB}podpis ad-hoc (bez wydawcy)"
        else
            echo "brak${TAB}BRAK podpisu"
        fi
    else
        pk=""
        if have dpkg; then pk=$(dpkg -S "$p" 2>/dev/null | head -1 | cut -d: -f1)
        elif have rpm; then pk=$(rpm -qf "$p" 2>/dev/null | grep -v 'not owned' | head -1)
        elif have pacman; then pk=$(pacman -Qoq "$p" 2>/dev/null | head -1); fi
        if [ -n "$pk" ]; then echo "ok${TAB}z pakietu: $pk"
        else echo "brak${TAB}spoza menedżera pakietów"; fi
    fi
}

N=0
run_test() {
    name="$1"; opis="$2"; need="$3"; fn="$4"
    N=$((N + 1))
    printf '  [%2d] %s...' "$N" "$opis"
    t0=$(date +%s)
    : > "$NOTES"
    wynik="OK"; msg=""
    if [ "$need" = "root" ] && [ "$IS_ROOT" != 1 ]; then
        wynik="POMINIĘTO: brak uprawnień"
    else
        ( "$fn" ) > "$RAW/$name.txt" 2> "$RAW/$name.err"
        rc=$?
        if [ $rc -ne 0 ]; then wynik="BŁĄD"; msg="kod $rc: $(head -c 200 "$RAW/$name.err" | tr '\n' ' ')"; fi
        [ -s "$RAW/$name.err" ] || rm -f "$RAW/$name.err"
    fi
    if [ -z "$msg" ] && [ -s "$NOTES" ]; then msg=$(cat "$NOTES"); fi
    t1=$(date +%s)
    printf '{"test":"%s","opis":"%s","wynik":"%s","komunikat":"%s","czas_s":%s,"wymaga_roota":%s,"zakonczono":"%s"}\n' \
        "$name" "$(json_esc "$opis")" "$wynik" "$(json_esc "$msg")" "$((t1 - t0))" "$([ "$need" = root ] && echo true || echo false)" "$(date '+%Y-%m-%d %H:%M:%S')" >> "$STATUS_TMP"
    printf ' %s (%s s)\n' "$wynik" "$((t1 - t0))"
}

# Odczyt manifestu rozszerzenia: nazwa<TAB>uprawnienia<TAB>update_url
manifest_info() {
    f="$1"
    if have jq; then
        jq -r '[(.name // ""), ([(.permissions // [])[], (.host_permissions // [])[], ((.content_scripts // [])[] | (.matches // [])[])] | map(select(type == "string")) | unique | join(",")), (.update_url // "")] | @tsv' "$f" 2>/dev/null
    elif [ "$OS" != "Darwin" ] && have python3; then
        python3 -I -c 'import json,sys
m=json.load(open(sys.argv[1],encoding="utf-8-sig"))
p=[x for x in (m.get("permissions") or [])+(m.get("host_permissions") or []) if isinstance(x,str)]
for cs in m.get("content_scripts") or []:
    p+=[x for x in cs.get("matches") or [] if isinstance(x,str)]
print("\t".join([str(m.get("name","")),",".join(sorted(set(p))),str(m.get("update_url",""))]))' "$f" 2>/dev/null
    elif [ "$OS" = "Darwin" ]; then
        nm=$(plutil -extract name raw -o - "$f" 2>/dev/null)
        pr=$(plutil -extract permissions json -o - "$f" 2>/dev/null | tr -d '[]"' )
        up=$(plutil -extract update_url raw -o - "$f" 2>/dev/null)
        printf '%s\t%s\t%s\n' "$nm" "$pr" "$up"
    else
        nm=$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$f" | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')
        printf '%s\t?\t%s\n' "$nm" "$(grep -o 'clients2.google.com' "$f" | head -1)"
    fi
}

# ============================================================ testy

t_system() {
    echo "komputer: $(hostname)"
    echo "uzytkownik: $REAL_USER (uruchomione jako: $(id -un), root: $IS_ROOT)"
    echo "system: $(uname -srm)"
    if [ "$OS" = "Darwin" ]; then
        sw_vers
        echo "--- SIP"; csrutil status 2>&1
        echo "--- FileVault"; fdesetup status 2>&1
        echo "--- Gatekeeper"; spctl --status 2>&1
    elif [ -r /etc/os-release ]; then
        cat /etc/os-release
    fi
    echo "--- uptime"; uptime
    return 0
}

t_autostart() {
    tsv="$RAW/autostart.tsv"; : > "$tsv"
    if [ "$OS" = "Darwin" ]; then
        for d in "$UHOME/Library/LaunchAgents" /Library/LaunchAgents /Library/LaunchDaemons; do
            [ -d "$d" ] || continue
            for f in "$d"/*.plist; do
                [ -e "$f" ] || continue
                label=$(/usr/libexec/PlistBuddy -c 'Print :Label' "$f" 2>/dev/null)
                prog=$(/usr/libexec/PlistBuddy -c 'Print :Program' "$f" 2>/dev/null)
                [ -n "$prog" ] || prog=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$f" 2>/dev/null)
                args=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments' "$f" 2>/dev/null | sed '1d;$d' | sed 's/^[[:space:]]*//' | tr '\n' ' ')
                echo "=== $f"
                echo "Label: $label"; echo "Program: $prog"; echo "Argumenty: $args"
                /usr/libexec/PlistBuddy -c 'Print :RunAtLoad' "$f" 2>/dev/null | sed 's/^/RunAtLoad: /'
                printf '%s\t%s\t%s\t%s\n' "launchd" "$f" "$prog" "$label $args" >> "$tsv"
            done
        done
        echo "=== Elementy logowania i działające w tle (sfltool)"
        if [ "$IS_ROOT" = 1 ]; then sfltool dumpbtm 2>&1 | head -400
        else echo "wymaga sudo"; note 'elementy logowania (sfltool dumpbtm) wymagają sudo'; fi
    else
        echo "=== systemd: włączone jednostki"
        have systemctl && systemctl list-unit-files --state=enabled --no-pager 2>/dev/null
        for d in /etc/systemd/system "$UHOME/.config/systemd/user"; do
            [ -d "$d" ] || continue
            for f in $(find "$d" -maxdepth 2 -name '*.service' -type f 2>/dev/null); do
                ex=$(grep -m1 '^ExecStart=' "$f" | sed 's/^ExecStart=[-@+!:]*//')
                echo "--- $f: $ex"
                printf '%s\t%s\t%s\t%s\n' "systemd" "$f" "$(echo "$ex" | awk '{print $1}')" "$ex" >> "$tsv"
            done
        done
        for d in "$UHOME/.config/autostart" /etc/xdg/autostart; do
            [ -d "$d" ] || continue
            for f in "$d"/*.desktop; do
                [ -e "$f" ] || continue
                ex=$(grep -m1 '^Exec=' "$f" | sed 's/^Exec=//')
                echo "--- $f: $ex"
                printf '%s\t%s\t%s\t%s\n' "autostart" "$f" "$(echo "$ex" | awk '{print $1}')" "$ex" >> "$tsv"
            done
        done
        echo "=== /etc/ld.so.preload"
        [ -s /etc/ld.so.preload ] && cat /etc/ld.so.preload
        echo "=== /etc/rc.local"
        [ -f /etc/rc.local ] && grep -v '^[[:space:]]*#' /etc/rc.local | grep -v '^[[:space:]]*$'
    fi
    echo "=== crontab użytkownika"
    if [ -n "${SUDO_USER:-}" ]; then crontab -l -u "$SUDO_USER" 2>/dev/null; else crontab -l 2>/dev/null; fi | grep -v '^#' | while IFS= read -r l; do
        [ -n "$l" ] || continue
        echo "$l"; printf '%s\t%s\t%s\t%s\n' "cron" "crontab" "" "$l" >> "$tsv"
    done
    echo "=== cron systemowy"
    for f in /etc/crontab /etc/cron.d/*; do [ -f "$f" ] && { echo "--- $f"; grep -v '^[[:space:]]*#' "$f" | grep -v '^[[:space:]]*$'; }; done
    [ -d /etc/periodic ] && ls -la /etc/periodic/* 2>/dev/null
    echo "=== pliki startowe powłoki"
    for f in "$UHOME/.zshrc" "$UHOME/.zprofile" "$UHOME/.zshenv" "$UHOME/.bash_profile" "$UHOME/.bashrc" "$UHOME/.profile" "$UHOME/.zlogin"; do
        [ -f "$f" ] || continue
        grep -nE 'curl|wget|base64|/dev/tcp|nc -|ncat|socat|osascript|python[0-9.]* -c|perl -e|nohup|bash -i' "$f" 2>/dev/null | sed "s|^|$f:|"
    done
    return 0
}

t_mdm() {
    if [ "$OS" != "Darwin" ]; then echo "nie dotyczy (Linux)"; return 0; fi
    echo "=== profiles status -type enrollment"; profiles status -type enrollment 2>&1
    echo "=== profiles list"; profiles list 2>&1
    if [ "$IS_ROOT" = 1 ]; then echo "=== profiles show -type configuration"; profiles show -type configuration 2>&1 | head -300
    else note 'pełna lista profili konfiguracji wymaga sudo'; fi
    echo "=== Managed Preferences"; ls -la "/Library/Managed Preferences" 2>/dev/null
    return 0
}

t_tcc() {
    if [ "$OS" != "Darwin" ]; then echo "nie dotyczy (Linux)"; return 0; fi
    tsv="$RAW/tcc.tsv"; : > "$tsv"
    q="select service, client, auth_value, last_modified from access where service in ('kTCCServiceAccessibility','kTCCServiceListenEvent','kTCCServiceScreenCapture','kTCCServiceSystemPolicyAllFiles','kTCCServiceCamera','kTCCServiceMicrophone','kTCCServicePostEvent','kTCCServiceEndpointSecurityClient');"
    for db in "$UHOME/Library/Application Support/com.apple.TCC/TCC.db" "/Library/Application Support/com.apple.TCC/TCC.db"; do
        echo "=== $db"
        out=$(sqlite3 -separator "$TAB" "$db" "$q" 2>&1)
        if printf '%s' "$out" | grep -qiE 'authorization denied|unable to open|not permitted'; then
            echo "brak dostępu: $out"
            note "TCC ($db) wymaga Pełnego dostępu do dysku dla Terminala"
        else
            echo "$out"
            printf '%s\n' "$out" | grep -v '^$' >> "$tsv"
        fi
    done
    return 0
}

t_rozszerzenia_sys() {
    if [ "$OS" = "Darwin" ]; then
        echo "=== systemextensionsctl list"; systemextensionsctl list 2>&1
        echo "=== rozszerzenia jądra spoza Apple"
        if have kmutil; then kmutil showloaded --list-only 2>/dev/null | grep -v 'com\.apple\.'
        else kextstat 2>/dev/null | grep -v 'com\.apple\.'; fi
    else
        echo "=== lsmod"; lsmod 2>/dev/null
    fi
    return 0
}

t_przegladarki() {
    tsv="$RAW/rozszerzenia.tsv"; : > "$tsv"
    if [ "$OS" = "Darwin" ]; then
        AS="$UHOME/Library/Application Support"
        roots="Chrome|$AS/Google/Chrome
Edge|$AS/Microsoft Edge
Brave|$AS/BraveSoftware/Brave-Browser
Vivaldi|$AS/Vivaldi
Opera|$AS/com.operasoftware.Opera
Chromium|$AS/Chromium"
        ffroot="$AS/Firefox/Profiles"
    else
        C="$UHOME/.config"
        roots="Chrome|$C/google-chrome
Chromium|$C/chromium
Edge|$C/microsoft-edge
Brave|$C/BraveSoftware/Brave-Browser
Vivaldi|$C/vivaldi
Opera|$C/opera"
        ffroot="$UHOME/.mozilla/firefox"
    fi
    echo "$roots" | while IFS='|' read -r b root; do
        [ -d "$root" ] || continue
        find "$root" -maxdepth 5 -path '*/Extensions/*/*/manifest.json' -type f 2>/dev/null | while IFS= read -r mf; do
            vdir=$(dirname "$mf"); id=$(basename "$(dirname "$vdir")")
            prof=$(basename "$(dirname "$(dirname "$(dirname "$vdir")")")")
            info=$(manifest_info "$mf")
            nm=$(printf '%s' "$info" | cut -f1); pr=$(printf '%s' "$info" | cut -f2); up=$(printf '%s' "$info" | cut -f3)
            case "$nm" in __MSG_*) nm="$id ($nm)" ;; esac
            store="nie"; printf '%s' "$up" | grep -qE 'clients2\.google\.com|edge\.microsoft\.com|opera\.com' && store="tak"
            printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$b" "$prof" "$id" "$nm" "$pr" "$store" >> "$tsv"
        done
    done
    if [ -d "$ffroot" ]; then
        find "$ffroot" -maxdepth 2 -name extensions.json -type f 2>/dev/null | while IFS= read -r ej; do
            if have jq; then
                jq -r '.addons[] | select(.type == "extension") | select(.location != "app-builtin" and .location != "app-system-defaults" and .location != "app-system-addons") | ["Firefox", .location, .id, (.defaultLocale.name // ""), (((.userPermissions.permissions // []) + (.userPermissions.origins // [])) | join(",")), (if .location == "app-profile" then "tak" else "nie" end)] | @tsv' "$ej" 2>/dev/null >> "$tsv"
            elif [ "$OS" != "Darwin" ] && have python3; then
                python3 -I -c 'import json,sys
for a in json.load(open(sys.argv[1])).get("addons",[]):
    if a.get("type")!="extension" or a.get("location") in ("app-builtin","app-system-defaults","app-system-addons"): continue
    up=a.get("userPermissions") or {}
    print("\t".join(["Firefox",a.get("location",""),a.get("id",""),(a.get("defaultLocale") or {}).get("name",""),",".join((up.get("permissions") or [])+(up.get("origins") or [])),"tak" if a.get("location")=="app-profile" else "nie"]))' "$ej" 2>/dev/null >> "$tsv"
            else
                note 'rozszerzenia Firefoksa: brak jq/python3 do odczytu'
            fi
        done
    fi
    cat "$tsv"
    if [ "$OS" = "Darwin" ]; then echo "=== Safari"; pluginkit -mAvvv -p com.apple.Safari.web-extension 2>/dev/null | grep -E '^\s*(\+|-|!)?\s*[a-zA-Z0-9]|Path' | head -100; fi
    echo "=== polityki przeglądarek"
    if [ "$OS" = "Darwin" ]; then
        for p in "/Library/Managed Preferences"/*.plist "/Library/Managed Preferences/$REAL_USER"/*.plist; do
            [ -f "$p" ] || continue
            echo "--- $p"; plutil -p "$p" 2>/dev/null | head -50
        done
        for dom in com.google.Chrome com.microsoft.Edge com.brave.Browser; do
            v=$(defaults read "$dom" ExtensionInstallForcelist 2>/dev/null)
            [ -n "$v" ] && echo "--- $dom ExtensionInstallForcelist: $v"
        done
    else
        for d in /etc/opt/chrome/policies /etc/chromium/policies /etc/chromium-browser/policies /etc/opt/edge/policies /etc/brave/policies /usr/lib/firefox/distribution /etc/firefox/policies; do
            [ -d "$d" ] || continue
            find "$d" -name '*.json' -type f 2>/dev/null | while IFS= read -r f; do echo "--- $f"; head -c 3000 "$f"; echo; done
        done
    fi
    return 0
}

t_procesy() {
    tsv="$RAW/procesy.tsv"; : > "$tsv"
    if [ "$OS" = "Darwin" ]; then
        ps axo pid=,ppid=,user=,comm= 2>/dev/null | while read -r pid ppid user comm; do printf '%s\t%s\t%s\t%s\n' "$pid" "$ppid" "$user" "$comm" >> "$tsv"; done
    else
        ps -eo pid=,ppid=,user=,comm= 2>/dev/null | while read -r pid ppid user comm; do
            exe=$(readlink "/proc/$pid/exe" 2>/dev/null)
            [ -n "$exe" ] || exe="$comm"
            printf '%s\t%s\t%s\t%s\n' "$pid" "$ppid" "$user" "$exe" >> "$tsv"
        done
        [ "$IS_ROOT" = 1 ] || note 'bez sudo nie widać ścieżek procesów innych użytkowników'
    fi
    ps axo pid,ppid,user,args 2>/dev/null
    return 0
}

t_siec() {
    if [ "$OS" = "Darwin" ]; then
        echo "=== połączenia i porty (lsof)"; lsof -nP -iTCP -sTCP:ESTABLISHED,LISTEN 2>/dev/null
        echo "=== porty nasłuchujące (netstat)"; netstat -anv -p tcp 2>/dev/null | grep -i listen
    else
        if have ss; then ss -tunap 2>/dev/null; else netstat -tunap 2>/dev/null; fi
    fi
    [ "$IS_ROOT" = 1 ] || note 'bez sudo widać procesy tylko Twojego konta'
    return 0
}

t_dns_proxy() {
    echo "=== /etc/hosts (bez komentarzy)"
    grep -v '^[[:space:]]*#' /etc/hosts | grep -v '^[[:space:]]*$'
    echo "=== zmienne proxy"; env | grep -i '_proxy=' | sed 's/:[^:@]*@/:***@/'
    if [ "$OS" = "Darwin" ]; then
        echo "=== scutil --proxy"; scutil --proxy 2>&1
        echo "=== scutil --dns (serwery)"; scutil --dns 2>/dev/null | grep -E 'nameserver\[' | sort -u
    else
        echo "=== resolv.conf"; grep -v '^#' /etc/resolv.conf 2>/dev/null
        have resolvectl && { echo "=== resolvectl dns"; resolvectl dns 2>/dev/null; }
        have gsettings && { echo "=== proxy GNOME"; gsettings get org.gnome.system.proxy mode 2>/dev/null; gsettings get org.gnome.system.proxy autoconfig-url 2>/dev/null; }
        [ -f /etc/environment ] && { echo "=== /etc/environment"; grep -i proxy /etc/environment; }
    fi
    return 0
}

t_certyfikaty() {
    if [ "$OS" = "Darwin" ]; then
        echo "=== zaufane przez administratora"; security dump-trust-settings -d 2>&1 | head -200
        echo "=== zaufane przez użytkownika"; security dump-trust-settings 2>&1 | head -200
    else
        for d in /usr/local/share/ca-certificates /etc/pki/ca-trust/source/anchors /etc/ca-certificates/trust-source/anchors; do
            [ -d "$d" ] || continue
            echo "=== $d"
            find "$d" -type f 2>/dev/null | while IFS= read -r f; do
                if have openssl; then echo "$f: $(openssl x509 -noout -subject -startdate -in "$f" 2>/dev/null | tr '\n' ' ')"; else echo "$f"; fi
            done
        done
    fi
    return 0
}

t_udostepnianie() {
    if [ "$OS" = "Darwin" ]; then
        echo "=== porty zdalnego dostępu (22 SSH, 5900 Udostępnianie ekranu, 3283 Zdalne zarządzanie)"
        netstat -anv -p tcp 2>/dev/null | grep -i listen | grep -E '\.(22|5900|3283|5938|7070) '
        echo "=== procesy"; ps axo comm= 2>/dev/null | grep -E 'ARDAgent|screensharingd|AppleVNCServer' | sort -u | sed 's/^/proces: /'
        if [ "$IS_ROOT" = 1 ]; then echo "=== Zdalne logowanie"; systemsetup -getremotelogin 2>&1; fi
        launchctl print-disabled system 2>/dev/null | grep -E 'ssh|screensharing' | head | sed 's/^/launchctl: /'
    else
        for s in ssh sshd xrdp vncserver x11vnc tigervnc teamviewerd anydesk rustdesk; do
            st=$(systemctl is-active "$s" 2>/dev/null)
            [ "$st" = "active" ] && echo "usługa $s: aktywna"
        done
        if have ss; then ss -tln 2>/dev/null | grep -E ':(22|3389|5900|5901|5938|7070|21118) '; fi
    fi
    return 0
}

t_konta() {
    if [ "$OS" = "Darwin" ]; then
        echo "=== konta (UID >= 500)"; dscl . -list /Users UniqueID 2>/dev/null | awk '$2 >= 500'
        echo "=== grupa admin"; dscl . -read /Groups/admin GroupMembership 2>/dev/null
    else
        echo "=== konta z UID 0"; awk -F: '$3 == 0 {print $1}' /etc/passwd
        echo "=== konta z powłoką logowania"; awk -F: '$3 >= 1000 && $7 !~ /(nologin|false)$/ {print $1, $3, $7}' /etc/passwd
        echo "=== grupy sudo/wheel/admin"; getent group sudo wheel admin 2>/dev/null
    fi
    echo "=== klucze SSH, którymi można się zalogować"
    for f in "$UHOME/.ssh/authorized_keys" /root/.ssh/authorized_keys /var/root/.ssh/authorized_keys; do
        [ -r "$f" ] || continue
        echo "--- $f: $(grep -cvE '^[[:space:]]*(#|$)' "$f") kluczy"
        awk '!/^[[:space:]]*(#|$)/ {print "    " $1 " ... " $NF}' "$f"
    done
    echo "=== ostatnie logowania"; last 2>/dev/null | head -20
    return 0
}

t_telefon() {
    tsv="$RAW/telefon_dane.tsv"; : > "$tsv"
    if [ "$OS" = "Darwin" ]; then
        echo "=== /var/db/lockdown (zaufane iPhone'y)"
        if [ "$IS_ROOT" = 1 ]; then
            for f in /var/db/lockdown/*.plist; do
                [ -e "$f" ] || continue
                b=$(basename "$f"); [ "$b" = "SystemConfiguration.plist" ] && continue
                echo "$b $(mtime "$f")"; printf 'lockdown\t%s\t%s\n' "$b" "$(mtime "$f")" >> "$tsv"
            done
        else echo "wymaga sudo"; note "rekordy parowania iPhone (/var/db/lockdown) wymagają sudo"; fi
        bdir="$UHOME/Library/Application Support/MobileSync/Backup"
        echo "=== kopie iPhone: $bdir"
        if [ -d "$bdir" ]; then
            if ! ls "$bdir" >/dev/null 2>&1; then echo "brak dostępu"; note 'kopie iPhone wymagają Pełnego dostępu do dysku dla Terminala'; fi
            for b in "$bdir"/*/; do
                [ -d "$b" ] || continue
                nm=$(/usr/libexec/PlistBuddy -c 'Print :"Device Name"' "$b/Info.plist" 2>/dev/null)
                dt=$(/usr/libexec/PlistBuddy -c 'Print :"Last Backup Date"' "$b/Info.plist" 2>/dev/null)
                enc="nieznane"
                if [ -f "$b/Manifest.db" ]; then
                    if [ "$(head -c 15 "$b/Manifest.db" 2>/dev/null)" = "SQLite format 3" ]; then enc="NIE"; else enc="tak"; fi
                fi
                echo "$b | $nm | $dt | zaszyfrowana: $enc"
                printf 'kopia\t%s\t%s | %s | zaszyfrowana: %s\n' "$b" "$nm" "$dt" "$enc" >> "$tsv"
            done
        fi
        echo "=== Bluetooth"
        system_profiler SPBluetoothDataType 2>/dev/null | grep -E '^\s{10}[^ ].*:$' | sed 's/:$//' | sed 's/^[[:space:]]*//' | sort -u | while IFS= read -r d; do
            echo "$d"; printf 'bt\t%s\t\n' "$d" >> "$tsv"
        done
    else
        for d in "$UHOME/.config/kdeconnect" "$UHOME/.config/gsconnect"; do
            [ -d "$d" ] || continue
            echo "=== $d"; ls -la "$d"
            n=$(find "$d" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
            printf 'kdeconnect\t%s\t%s urządzeń\n' "$d" "$n" >> "$tsv"
        done
        if have gsettings; then
            gd=$(gsettings get org.gnome.Shell.Extensions.GSConnect devices 2>/dev/null)
            [ -n "$gd" ] && [ "$gd" != "@as []" ] && { echo "GSConnect: $gd"; printf 'kdeconnect\tGSConnect\t%s\n' "$gd" >> "$tsv"; }
        fi
        if have bluetoothctl; then
            echo "=== Bluetooth (sparowane)"
            if have timeout; then bt=$(timeout 5 bluetoothctl devices Paired 2>/dev/null); else bt=""; fi
            echo "$bt"
            printf '%s\n' "$bt" | grep '^Device' | cut -d' ' -f3- | while IFS= read -r d; do printf 'bt\t%s\t\n' "$d" >> "$tsv"; done
        fi
    fi
    echo "=== Android (ADB)"
    if [ -f "$UHOME/.android/adbkey" ]; then echo "adbkey: $(mtime "$UHOME/.android/adbkey")"; printf 'adbkey\t%s\t%s\n' "$UHOME/.android/adbkey" "$(mtime "$UHOME/.android/adbkey")" >> "$tsv"; fi
    [ -f "$UHOME/.android/adb_known_hosts.pb" ] && { echo "parowanie bezprzewodowe: tak"; printf 'adbwifi\t%s\t\n' "$UHOME/.android/adb_known_hosts.pb" >> "$tsv"; }
    have adb && { echo "adb: $(command -v adb)"; printf 'adb\t%s\t\n' "$(command -v adb)" >> "$tsv"; }
    have scrcpy && { echo "scrcpy: $(command -v scrcpy)"; printf 'scrcpy\t%s\t\n' "$(command -v scrcpy)" >> "$tsv"; }
    return 0
}

t_programy() {
    if [ "$OS" = "Darwin" ]; then
        for d in /Applications "$UHOME/Applications" /Applications/Utilities; do
            [ -d "$d" ] && ls -1 "$d" 2>/dev/null | sed "s|^|$d/|"
        done
        have brew && brew list --cask 2>/dev/null | sed 's/^/brew cask: /'
    else
        have dpkg-query && dpkg-query -W -f='${Package} ${Version}\n' 2>/dev/null
        have rpm && rpm -qa 2>/dev/null
        have pacman && pacman -Q 2>/dev/null
        have flatpak && flatpak list --app --columns=application 2>/dev/null | sed 's/^/flatpak: /'
        have snap && snap list 2>/dev/null | awk 'NR > 1 {print "snap: " $1}'
        ls -1 /opt 2>/dev/null | sed 's|^|/opt/|'
    fi
    return 0
}

t_podpisy() {
    tsv="$RAW/podpisy.tsv"; : > "$tsv"
    {
        cut -f3 "$RAW/autostart.tsv" 2>/dev/null
        cut -f4 "$RAW/procesy.tsv" 2>/dev/null | while IFS= read -r p; do
            c=$(path_class "$p"); [ "$c" = system ] || echo "$p"
        done
    } | grep '^/' | sort -u | while IFS= read -r p; do
        r=$(sig_check "$p")
        printf '%s\t%s\n' "$p" "$r" >> "$tsv"
    done
    cat "$tsv"
    return 0
}

t_wydajnosc() {
    echo "=== miejsce na dysku"; df -h 2>/dev/null | grep -vE '^(tmpfs|devfs|map |overlay|udev)'
    echo "=== foldery do sprzątania (rozmiar)"
    for d in "$UHOME/Library/Caches" "$UHOME/.Trash" "$UHOME/.cache" "$UHOME/.local/share/Trash" /var/cache/apt/archives /var/log/journal; do
        [ -d "$d" ] && echo "$(dsize "$d" | cut -f1)	$d"
    done
    if [ "$OS" = "Darwin" ]; then
        echo "=== największe foldery: sprawdź Ustawienia systemowe > Ogólne > Pamięć masowa (du po Dokumentach wywołałby pytania o zgodę)"
    else
        echo "=== największe foldery w katalogu domowym"
        dsize "$UHOME"/* "$UHOME"/.[!.]* | sort -h 2>/dev/null | tail -10
    fi
    echo "=== procesy obciążające CPU"
    if [ "$OS" = "Darwin" ]; then ps -Ao pcpu,pmem,comm -r 2>/dev/null | head -11
    else ps -eo pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -11; fi
    echo "=== pamięć"
    if [ "$OS" = "Darwin" ]; then vm_stat 2>/dev/null | head -8; else free -h 2>/dev/null; fi
    echo "=== zdrowie dysku"
    if [ "$OS" = "Darwin" ]; then diskutil info / 2>/dev/null | grep -iE 'SMART|Solid State|Device / Media Name'
    elif [ "$IS_ROOT" = 1 ] && have smartctl; then
        for dev in $(lsblk -dno NAME,TYPE 2>/dev/null | awk '$2 == "disk" {print "/dev/" $1}'); do echo "--- $dev"; smartctl -H "$dev" 2>&1 | tail -3; done
    else echo "SMART: wymaga sudo i pakietu smartmontools"; fi
    return 0
}

t_ioc() {
    mkdir -p "$OUT/ioc"
    base="https://raw.githubusercontent.com/AssoEchap/stalkerware-indicators/master"
    curl -fsSL "$base/generated/hosts_full" -o "$OUT/ioc/hosts_full" || return 1
    curl -fsSL "$base/ioc.yaml" -o "$OUT/ioc/ioc.yaml" || return 1
    wc -l "$OUT/ioc/hosts_full"
    return 0
}

# ============================================================ start

echo ""
echo "Audyt inwigilacji: faza czytania ($OS)"
echo "Sprawdzam autostart, profile MDM, uprawnienia prywatności, rozszerzenia, procesy, sieć,"
echo "certyfikaty, udostępnianie, konta i dostęp do telefonu."
echo "Na tym etapie NICZEGO nie usuwam ani nie zmieniam. Dane zostają na tym komputerze."
echo "Folder audytu: $OUT"
if [ "$IS_ROOT" = 1 ]; then echo "Tryb: sudo (pełny audyt)"; else echo "Tryb: zwykły użytkownik. Potem uruchom: sudo bash audyt.sh"; fi
echo ""
if [ "$IOC" = 0 ] && [ "$ASK" = 1 ] && [ -t 0 ]; then
    echo "Mogę pobrać z GitHuba publiczną listę wskaźników stalkerware (AssoEchap/stalkerware-indicators)."
    echo "To tylko pobranie, niczego stąd nie wysyłam."
    printf 'Pobrać listę? [t/N] '
    read -r odp
    case "$odp" in t|T|tak|y|Y|yes) IOC=1 ;; esac
    echo ""
fi

run_test system "Informacje o systemie" any t_system
run_test autostart "Autostart (launchd / systemd, cron, pliki powłoki)" any t_autostart
run_test mdm "Profile i zarządzanie MDM" any t_mdm
run_test tcc "Uprawnienia prywatności (TCC)" any t_tcc
run_test rozszerzenia_systemowe "Rozszerzenia systemowe i jądra" any t_rozszerzenia_sys
run_test przegladarki "Rozszerzenia i polityki przeglądarek" any t_przegladarki
run_test procesy "Działające procesy" any t_procesy
run_test siec "Połączenia sieciowe i porty" any t_siec
run_test dns_proxy "DNS, plik hosts, proxy" any t_dns_proxy
run_test certyfikaty "Zaufane certyfikaty" any t_certyfikaty
run_test udostepnianie "Udostępnianie i zdalny dostęp" any t_udostepnianie
run_test konta "Konta i klucze SSH" any t_konta
run_test telefon "Kanały dostępu do telefonu" any t_telefon
run_test programy "Zainstalowane programy" any t_programy
[ "$IOC" = 1 ] && run_test ioc "Pobieranie listy wskaźników stalkerware" any t_ioc
run_test podpisy "Podpisy plików z autostartu i procesów" any t_podpisy
run_test wydajnosc "Dysk, miejsce i obciążenie (tylko pomiar)" any t_wydajnosc

{ echo '['; sed '$!s/$/,/' "$STATUS_TMP"; echo ']'; } > "$RAW/_status.json"
rm -f "$NOTES"

# ============================================================ analiza

echo ""
echo "Analizuję wyniki..."

sig_of() { grep -F "$1$TAB" "$RAW/podpisy.tsv" 2>/dev/null | head -1 | cut -f2,3; }

# wzorce: kategoria|grupa|nazwa|regex ERE (bez \b, bo BSD grep)
WZORCE='POTWIERDZONE|stalkerware|mSpy|(^|[^a-z])mspy
POTWIERDZONE|stalkerware|FlexiSPY|flexi ?spy
POTWIERDZONE|stalkerware|Spyrix|spyrix
POTWIERDZONE|stalkerware|Refog|(^|[^a-z])refog
POTWIERDZONE|stalkerware|Kidlogger|kid ?logger
POTWIERDZONE|stalkerware|Hoverwatch|hoverwatch
POTWIERDZONE|stalkerware|Spyera|spyera
POTWIERDZONE|stalkerware|WebWatcher|web ?watcher
POTWIERDZONE|stalkerware|pcTattletale|tattletale
POTWIERDZONE|stalkerware|Realtime-Spy|realtime-?spy
POTWIERDZONE|stalkerware|Spytech / SpyAgent|spytech|spy ?agent
POTWIERDZONE|stalkerware|Elite Keylogger|elite ?keylogger
POTWIERDZONE|stalkerware|Aobo Keylogger|aobo
POTWIERDZONE|stalkerware|Refog / KGB Spy|kgb ?spy
POTWIERDZONE|stalkerware|iKeyMonitor|ikeymonitor
POTWIERDZONE|stalkerware|KidsGuard (ClevGuard)|kidsguard|clevguard
PODEJRZANE|stalkerware|Keylogger (nazwa ogólna)|keylogger|logkeys
DO_WYJASNIENIA|monitoring|Teramind|teramind
DO_WYJASNIENIA|monitoring|ActivTrak|activtrak
DO_WYJASNIENIA|monitoring|Veriato|veriato|spector ?360
DO_WYJASNIENIA|monitoring|InterGuard|interguard
DO_WYJASNIENIA|monitoring|Controlio|controlio
DO_WYJASNIENIA|monitoring|Kickidler|kickidler
DO_WYJASNIENIA|monitoring|StaffCop|staffcop
DO_WYJASNIENIA|monitoring|FamiSafe|famisafe
DO_WYJASNIENIA|monitoring|Qustodio|qustodio
DO_WYJASNIENIA|monitoring|Norton Family|norton ?family
DO_WYJASNIENIA|monitoring|Kaspersky Safe Kids|safe ?kids
POTWIERDZONE|rat|RAT (znana rodzina)|njrat|darkcomet|remcos|asyncrat|nanocore|netwire|venomrat|xworm|quasar ?rat|coldroot|crossrat|oceanlotus|fruitfly
DO_WYJASNIENIA|zdalny|TeamViewer|teamviewer
DO_WYJASNIENIA|zdalny|AnyDesk|anydesk
DO_WYJASNIENIA|zdalny|RustDesk|rustdesk
DO_WYJASNIENIA|zdalny|Pulpit zdalny Chrome|chrome remote desktop|chromoting|remoting_host
DO_WYJASNIENIA|zdalny|ScreenConnect (ConnectWise)|screenconnect|connectwise
DO_WYJASNIENIA|zdalny|Splashtop|splashtop
DO_WYJASNIENIA|zdalny|LogMeIn / GoTo|logmein|gotoassist|gotomypc|goto ?resolve
DO_WYJASNIENIA|zdalny|VNC|realvnc|tigervnc|tightvnc|x11vnc|vncserver
DO_WYJASNIENIA|zdalny|xrdp|xrdp
DO_WYJASNIENIA|zdalny|Zoho Assist|zoho ?assist
DO_WYJASNIENIA|zdalny|DWService|dwservice|dwagent
DO_WYJASNIENIA|zdalny|MeshAgent|meshagent|meshcentral
DO_WYJASNIENIA|zdalny|Atera|(^|[^a-z])atera
DO_WYJASNIENIA|zdalny|NinjaOne|ninjaone|ninjarmm
DO_WYJASNIENIA|zdalny|Parsec|(^|[^a-z])parsec
DO_WYJASNIENIA|zdalny|ngrok|(^|[^a-z])ngrok
DO_WYJASNIENIA|telefon|AirDroid|airdroid
DO_WYJASNIENIA|telefon|KDE Connect / GSConnect|kdeconnect|kde connect|gsconnect
DO_WYJASNIENIA|telefon|scrcpy|scrcpy
DO_WYJASNIENIA|telefon|Vysor|vysor
DO_WYJASNIENIA|telefon|Dr.Fone (Wondershare)|dr\.? ?fone|drfone|mobiletrans
DO_WYJASNIENIA|telefon|Tenorshare (iCareFone, UltData)|tenorshare|icarefone|ultdata
DO_WYJASNIENIA|telefon|iMazing|imazing
DO_WYJASNIENIA|telefon|3uTools|3utools
DO_WYJASNIENIA|telefon|iMobie (AnyTrans, PhoneRescue)|anytrans|phonerescue|imobie
DO_WYJASNIENIA|telefon|iMyFone|imyfone
DO_WYJASNIENIA|telefon|FonePaw / FoneLab|fonepaw|fonelab|aiseesoft
DO_WYJASNIENIA|telefon|Syncios / CopyTrans|syncios|copytrans
DO_WYJASNIENIA|telefon|MOBILedit|mobiledit
DO_WYJASNIENIA|forensic|Narzędzie śledcze (Elcomsoft, Cellebrite, Oxygen, Magnet)|elcomsoft|cellebrite|oxygen ?forensic|magnet ?(axiom|acquire)'

# Korpus nazw do porównania (bez własnego procesu audytu)
CORPUS="$RAW/.korpus.txt"
{
    awk -F'\t' '{print "autostart: " $2 " " $3 " " $4}' "$RAW/autostart.tsv" 2>/dev/null
    awk -F'\t' '{print "proces: " $4 " (PID " $1 ")"}' "$RAW/procesy.tsv" 2>/dev/null
    sed 's/^/program: /' "$RAW/programy.txt" 2>/dev/null
    awk -F'\t' '{print "rozszerzenie " $1 ": " $4}' "$RAW/rozszerzenia.tsv" 2>/dev/null
    grep -v '^===' "$RAW/rozszerzenia_systemowe.txt" 2>/dev/null | sed 's/^/rozszerzenie systemowe: /'
    grep -v '^===' "$RAW/tcc.txt" 2>/dev/null | sed 's/^/uprawnienie TCC: /'
} | grep -v 'audyt\.sh' > "$CORPUS"

grupa_opis() {
    case "$1" in
        stalkerware) echo "Stalkerware lub keylogger" ;;
        monitoring) echo "Program do monitorowania (firmowy lub rodzicielski)" ;;
        rat) echo "Trojan zdalnego dostępu (RAT)" ;;
        zdalny) echo "Narzędzie zdalnego dostępu" ;;
        telefon) echo "Program z dostępem do telefonu" ;;
        forensic) echo "Narzędzie śledcze do telefonów" ;;
    esac
}

echo "$WZORCE" | while IFS='|' read -r kat grupa nazwa rx; do
    [ -n "$rx" ] || continue
    hits=$(grep -iE "$rx" "$CORPUS" 2>/dev/null | sort -u | head -10)
    [ -n "$hits" ] || continue
    k="$kat"
    if [ "$kat" = "DO_WYJASNIENIA" ] && printf '%s' "$hits" | grep -qE '/tmp/|/private/tmp/|/dev/shm/|/Users/Shared/'; then k="PODEJRZANE"; fi
    case "$grupa" in
        stalkerware) why="Znany program do potajemnego monitorowania. Sama obecność nie mówi, kto go zainstalował."
            dalej="NIE odinstalowuj od razu: to może zaalarmować osobę, która go założyła. Najpierw zabezpiecz dowody (ten folder) i zmień hasła z innego, czystego urządzenia." ; q="" ;;
        monitoring) why="Legalny program do monitorowania pracowników lub dzieci. Na prywatnym komputerze dorosłej osoby bez jej wiedzy działa jak stalkerware."
            dalej="Jeśli to sprzęt służbowy albo sam to ustawiłeś, zostaw. Jeśli nie, traktujemy jak stalkerware." ; q="Czy wiesz, kto to zainstalował?" ;;
        rat) why="Nazwa znanej rodziny trojanów zdalnego dostępu."
            dalej="Nie loguj się tu do banku. Hasła zmień z innego urządzenia. Usuniemy z kwarantanną, potem rozważymy czystą instalację." ; q="" ;;
        zdalny) why="Legalne narzędzie do zdalnego sterowania. Groźne tylko wtedy, gdy go nie instalowałeś."
            dalej="Jeśli go nie używasz, odinstalujemy. Jeśli używasz, sprawdź w nim listę zaufanych urządzeń." ; q="Czy używasz $nazwa?" ;;
        telefon) why="Program, który potrafi czytać dane z telefonu. Daje dostęp każdemu, kto ma ten komputer."
            dalej="Jeśli to Twoje narzędzie, zostaw. Jeśli nie, odinstalujemy." ; q="Czy instalowałeś $nazwa?" ;;
        forensic) why="Profesjonalne narzędzie do wyciągania danych z telefonów i chmury. Na prywatnym komputerze to rzadkość."
            dalej="Jeśli nie pracujesz w tej branży, zabezpiecz dowody i zmień hasło Apple ID / Google z innego urządzenia." ; q="Czy wiesz, skąd się tu wziął?" ;;
    esac
    add_finding "$k" "lista:$grupa" "$(grupa_opis "$grupa"): $nazwa" "" "$hits" "$why" "$dalej" "$q"
    case "$grupa" in telefon|forensic) add_phone "Program: $nazwa" "zainstalowany lub uruchomiony" "$(printf '%s' "$hits" | head -2)" "Może czytać dane z podłączonego telefonu." ;; esac
done

# autostart: pliki z nietypowych miejsc bez podpisu / spoza pakietów
if [ -s "$RAW/autostart.tsv" ]; then
    while IFS="$FS" read -r src plik prog rest; do
        if printf '%s %s' "$prog" "$rest" | grep -qiE '(curl|wget)[^|]*\|[[:space:]]*(ba|z)?sh|base64 (-d|--decode)|/dev/tcp/|osascript -e|python[0-9.]* -c'; then
            add_finding PODEJRZANE autostart "Autostart pobiera albo wykonuje ukryty kod" "$plik" "$prog $rest" "Polecenie pobiera skrypt z sieci i od razu go uruchamia albo dekoduje ukryty kod." "Omówimy przed zmianą." ""
        fi
        [ -n "$prog" ] || continue
        cls=$(path_class "$prog")
        s=$(sig_of "$prog"); st=$(printf '%s' "$s" | cut -f1); opis=$(printf '%s' "$s" | cut -f2)
        if [ "$cls" = "ryzykowna" ] && [ "$st" = "brak" ]; then
            add_finding PODEJRZANE autostart "Autostart uruchamia niepodpisany plik z nietypowego miejsca" "$plik" "program: $prog ($opis)
$rest" "Plik startuje z systemem, leży w folderze tymczasowym, pobranych albo Application Support i nie ma ważnego podpisu. Tak wygląda typowy trojan na macOS i Linuksie." "Nie usuwaj jeszcze. Sprawdzimy, do czego należy; potem plik do kwarantanny, wpis autostartu wyłączymy." "Czy znasz program $prog?"
        fi
    done < <(tr '\t' "$FS" < "$RAW/autostart.tsv")
fi
rcs=$(sed -n '/^=== pliki startowe powłoki/,$p' "$RAW/autostart.txt" 2>/dev/null | grep -v '^===' | grep -iE '(curl|wget)[^|]*\|[[:space:]]*(ba|z)?sh|base64 (-d|--decode)|/dev/tcp/|nc -e|osascript|python[0-9.]* -c.*socket|bash -i')
[ -n "$rcs" ] && add_finding PODEJRZANE autostart "Podejrzane polecenia w plikach startowych powłoki" "~/.zshrc, ~/.bashrc itp." "$rcs" "Przy każdym otwarciu terminala uruchamia się polecenie, które pobiera kod z sieci albo otwiera połączenie zwrotne." "Zrobimy kopię pliku i usuniemy tylko te linie." "Czy dopisywałeś te linie sam (np. instalator narzędzia)?"
if [ -s /etc/ld.so.preload ] 2>/dev/null; then
    add_finding PODEJRZANE autostart "Plik /etc/ld.so.preload wstrzykuje bibliotekę do każdego programu" "/etc/ld.so.preload" "$(cat /etc/ld.so.preload)" "To klasyczna technika rootkitów na Linuksie." "Sprawdzimy, do czego należy biblioteka." ""
fi
add_clean autostart "Autostart: $(grep -c '' "$RAW/autostart.tsv" 2>/dev/null) wpisów, bez niepodpisanych plików z nietypowych miejsc i bez pobierania kodu z sieci."

# procesy z /tmp, /dev/shm itp.
if [ -s "$RAW/procesy.tsv" ]; then
    susp=$(awk -F'\t' '$4 ~ /^(\/tmp\/|\/private\/tmp\/|\/var\/tmp\/|\/dev\/shm\/|\/Users\/Shared\/)/ {print $4 " (PID " $1 ", użytkownik " $3 ")"}' "$RAW/procesy.tsv" | head -10)
    [ -n "$susp" ] && add_finding PODEJRZANE procesy "Procesy uruchomione z folderów tymczasowych" "lista poniżej" "$susp" "Normalne programy nie działają z /tmp ani /dev/shm. To ulubione miejsce malware na Linuksie i macOS." "Nie zamykaj ich na razie. Sprawdzimy pliki i połączenia." "Czy uruchamiałeś coś ręcznie z folderu tymczasowego?"
    del=$(awk -F'\t' '$4 ~ /\(deleted\)$/ {print $4 " (PID " $1 ")"}' "$RAW/procesy.tsv" | head -10)
    [ -n "$del" ] && add_finding DO_WYJASNIENIA procesy "Procesy, których plik został usunięty z dysku" "lista poniżej" "$del" "Często to tylko programy sprzed aktualizacji systemu (wtedy wystarczy restart), ale malware też tak się ukrywa." "Po restarcie sprawdzimy, czy wróciły." ""
fi
add_clean procesy "Procesy: $(grep -c '' "$RAW/procesy.tsv" 2>/dev/null), żaden nie działa z folderów tymczasowych."

# MDM i profile (macOS)
if [ "$OS" = "Darwin" ]; then
    enr=$(grep -iE 'MDM enrollment: Yes|Enrolled via DEP: Yes' "$RAW/mdm.txt" 2>/dev/null)
    prof=$(sed -n '/^=== profiles list/,/^===/p' "$RAW/mdm.txt" 2>/dev/null | grep -iE 'profileIdentifier|attribute: name' | head -10)
    [ -n "$enr" ] && add_finding DO_WYJASNIENIA mdm "Mac jest zapisany do zdalnego zarządzania (MDM)" "profiles status -type enrollment" "$enr" "Profil MDM daje organizacji zdalną kontrolę nad Makiem (ustawienia, aplikacje, certyfikaty, czasem ruch sieciowy). Na sprzęcie firmowym normalne, na prywatnym Macu to poważny sygnał." "Jeśli to nie Twoja firma, usuniemy profil w Ustawieniach systemowych > Ogólne > Urządzenia zarządzane (po zapisaniu szczegółów)." "Czy ten Mac jest lub był służbowy?"
    [ -n "$prof" ] && add_finding DO_WYJASNIENIA mdm "Zainstalowane profile konfiguracji" "Ustawienia systemowe > Ogólne > Urządzenia zarządzane" "$prof" "Profil może ustawić proxy, VPN, certyfikat główny albo zablokować ustawienia." "Przejrzymy, co zawiera." "Czy instalowałeś te profile (np. dla pracy, szkoły, VPN)?"
    add_clean mdm "Profile i MDM: Mac nie jest zarządzany zdalnie, brak profili konfiguracji."
    if [ -s "$RAW/tcc.tsv" ]; then
        tc=$(awk -F'\t' '$3 == 2 && $1 ~ /Accessibility|ListenEvent|ScreenCapture|PostEvent|SystemPolicyAllFiles|Camera|Microphone/ {print $1 ": " $2}' "$RAW/tcc.tsv" | sed 's/kTCCService//' | sort -u)
        [ -n "$tc" ] && add_finding DO_WYJASNIENIA tcc "Programy z dostępem do klawiatury, ekranu, kamery, mikrofonu lub całego dysku" "Ustawienia systemowe > Prywatność i ochrona" "$tc" "ListenEvent (Monitorowanie wprowadzania) i Accessibility pozwalają czytać wszystko, co piszesz; ScreenCapture nagrywa ekran. Zwykle to komunikatory, menedżery okien i narzędzia, które znasz." "Odbierz uprawnienia programom, których nie kojarzysz." "Czy znasz wszystkie te programy?"
    fi
fi

# proxy, certyfikaty
px=""
if [ "$OS" = "Darwin" ]; then
    px=$(grep -E '(HTTPEnable|HTTPSEnable|SOCKSEnable|ProxyAutoConfigEnable) : 1' -A0 "$RAW/dns_proxy.txt" 2>/dev/null)
    [ -n "$px" ] && px="$px
$(grep -E '(HTTPProxy|HTTPSProxy|SOCKSProxy|ProxyAutoConfigURLString) :' "$RAW/dns_proxy.txt")"
else
    px=$(grep -iE "^(http|https|all|socks)_proxy=|'manual'|'auto'" "$RAW/dns_proxy.txt" 2>/dev/null)
fi
cert=""
if [ "$OS" = "Darwin" ]; then
    cert=$(grep -E '^Cert [0-9]+:' "$RAW/certyfikaty.txt" 2>/dev/null)
else
    cert=$(sed -n '/^=== /,$p' "$RAW/certyfikaty.txt" 2>/dev/null | grep -v '^===')
fi
if [ -n "$cert" ]; then
    k=DO_WYJASNIENIA; why="Dodane ręcznie zaufane certyfikaty. Często to firma, VPN albo narzędzie programistyczne."
    [ -n "$px" ] && { k=PODEJRZANE; why="Dodany certyfikat RAZEM z ustawionym proxy: klasyczny układ do czytania ruchu HTTPS przez kogoś trzeciego."; }
    add_finding "$k" certyfikaty "Dodane zaufane certyfikaty główne" "pęk kluczy / magazyn certyfikatów" "$cert" "$why" "Usuniemy te, których nie potrzebujesz (po zapisaniu kopii)." "Czy dodawałeś certyfikat (praca, VPN, Charles, mitmproxy)?"
fi
[ -n "$px" ] && add_finding DO_WYJASNIENIA proxy "Ruch idzie przez proxy" "ustawienia sieci" "$px" "Proxy przepuszcza ruch przez inny serwer. W firmie normalne, na prywatnym komputerze to sygnał." "Jeśli to nie Ty, wyłączymy (zapiszemy stare ustawienia)." "Czy ustawiałeś proxy?"
add_clean certyfikaty "Certyfikaty: brak ręcznie dodanych zaufanych certyfikatów."
add_clean proxy "Proxy: wyłączone."

# hosts
hb=$(sed -n '/^=== \/etc\/hosts/,/^===/p' "$RAW/dns_proxy.txt" | grep -v '^===' | grep -vE '^(127\.0\.0\.1|::1|255\.255\.255\.255|fe80::1%lo0)[[:space:]]+(localhost|broadcasthost|ip6-|localhost\.localdomain)' | grep -vE '^(127\.0\.1\.1|ff0[0-2]::|fe00::)' | grep -vE "^127\.[0-9.]+[[:space:]]+($(hostname -s 2>/dev/null)|$(hostname 2>/dev/null))([[:space:]]|\$)" | head -15)
if [ -n "$hb" ]; then
    k=DO_WYJASNIENIA
    printf '%s' "$hb" | grep -qiE '(google|apple|icloud|microsoft|facebook|bank|mbank|pkobp|ing|paypal)\.(com|pl)' && k=PODEJRZANE
    if [ -s "$OUT/ioc/hosts_full" ]; then
        for d in $(printf '%s\n' "$hb" | awk '{for(i=2;i<=NF;i++) print $i}'); do grep -qxF "$(lower "$d")" "$OUT/ioc/hosts_full" && k=POTWIERDZONE; done
    fi
    add_finding "$k" hosts "Własne wpisy w pliku hosts" "/etc/hosts" "$hb" "Plik hosts może przekierowywać strony. Często to blokery reklam albo ustawienia programisty." "Jeśli to nie Ty, usuniemy te linie po zrobieniu kopii." "Czy dodawałeś coś do /etc/hosts?"
fi
add_clean hosts "Plik hosts: bez własnych wpisów."

# udostępnianie i konta
sh=$(grep -vE '^===' "$RAW/udostepnianie.txt" 2>/dev/null | grep -E 'LISTEN|aktywna|^proces: |Remote Login: On|^launchctl: .*=> (enabled|false)' | head -10)
[ -n "$sh" ] && add_finding DO_WYJASNIENIA zdalny "Włączony zdalny dostęp (SSH, Udostępnianie ekranu, VNC lub RDP)" "Ustawienia systemowe > Ogólne > Udostępnianie" "$sh" "Pozwala komuś zalogować się albo podglądać ekran przez sieć." "Jeśli nie używasz, wyłączymy (odwracalnie)." "Czy łączysz się z tym komputerem zdalnie?"
add_clean zdalny "Zdalny dostęp: SSH, Udostępnianie ekranu i VNC wyłączone."
if [ "$OS" != "Darwin" ]; then
    u0=$(sed -n '/^=== konta z UID 0/,/^===/p' "$RAW/konta.txt" | grep -v '^===' | grep -vx root)
    [ -n "$u0" ] && add_finding PODEJRZANE konta "Dodatkowe konto z uprawnieniami roota (UID 0)" "/etc/passwd" "$u0" "Tylko root powinien mieć UID 0. Dodatkowe takie konto to furtka." "Zablokujemy konto po zapisaniu kopii /etc/passwd." ""
fi
keys=$(grep -E '^--- .*authorized_keys' "$RAW/konta.txt" 2>/dev/null)
[ -n "$keys" ] && add_finding DO_WYJASNIENIA konta "Klucze SSH pozwalające zalogować się bez hasła" "~/.ssh/authorized_keys" "$(grep -A20 'authorized_keys' "$RAW/konta.txt" | grep -E '^(---|    )' | head -15)" "Każdy klucz to osoba lub komputer, który może się tu zalogować." "Usuń klucze, których nie rozpoznajesz." "Czy wiesz, do kogo należą te klucze?"
add_clean konta "Konta: brak dodatkowych kont roota i kluczy SSH."

# rozszerzenia
if [ -s "$RAW/rozszerzenia.tsv" ]; then
    br=$(awk -F'\t' '$5 ~ /<all_urls>|\*:\/\/\*\/\*|https?:\/\/\*\/\*|webRequest|history|cookies|debugger|nativeMessaging|proxy|clipboardRead|desktopCapture/ {print $1 ": " $4 " (" substr($5, 1, 120) ")" (($6 == "nie") ? " SPOZA SKLEPU" : "")}' "$RAW/rozszerzenia.tsv" | sort -u)
    side=$(printf '%s\n' "$br" | grep 'SPOZA SKLEPU')
    rest=$(printf '%s\n' "$br" | grep -v 'SPOZA SKLEPU' | grep -v '^$')
    [ -n "$side" ] && add_finding PODEJRZANE rozszerzenia "Rozszerzenia spoza sklepu z szerokimi uprawnieniami" "przeglądarki" "$side" "Nie pochodzą ze sklepu, a mogą czytać strony, ciasteczka albo historię." "Jeśli ich nie znasz, usuniemy je (po zapisaniu kopii folderu)." "Czy instalowałeś je ręcznie?"
    [ -n "$rest" ] && add_finding DO_WYJASNIENIA rozszerzenia "Rozszerzenia z szerokimi uprawnieniami" "przeglądarki" "$rest" "Pochodzą ze sklepu, ale mogą czytać zawartość stron. Blokery reklam i menedżery haseł potrzebują tego naprawdę." "Usuń te, których nie kojarzysz." "Czy znasz wszystkie te rozszerzenia?"
fi
force=$(grep -iE 'ExtensionInstallForcelist|ExtensionSettings|"Extensions"' "$RAW/przegladarki.txt" 2>/dev/null | head -5)
[ -n "$force" ] && add_finding PODEJRZANE polityki "Przeglądarka wymusza instalację rozszerzeń (polityka)" "polityki przeglądarki" "$force" "Na prywatnym komputerze to częsty ślad adware albo rozszerzenia szpiegującego." "Usuniemy politykę po zrobieniu kopii." "Czy komputer jest służbowy?"
add_clean rozszerzenia "Rozszerzenia przeglądarek: $(grep -c '' "$RAW/rozszerzenia.tsv" 2>/dev/null), bez szerokich uprawnień."

# telefon
T="$RAW/telefon_dane.tsv"
lk=$(awk -F'\t' '$1 == "lockdown" {print $2 " (" $3 ")"}' "$T" 2>/dev/null)
if [ -n "$lk" ]; then
    add_phone "iPhone: zaufane urządzenia" "$(printf '%s\n' "$lk" | grep -c '') rekord(y)" "$lk" "Ten komputer może robić kopię iPhone'a bez pytania."
    add_finding DO_WYJASNIENIA telefon "iPhone lub iPad ufa temu komputerowi" "/var/db/lockdown" "$lk" "Zaufany komputer może zrobić pełną kopię telefonu." "Jeśli to nie Twój iPhone: Ustawienia > Ogólne > Przenieś lub wyzeruj > Wyzeruj > Wyzeruj ustawienia lokalizacji i prywatności." "Czy podłączałeś swojego iPhone do tego komputera?"
elif [ "$OS" = "Darwin" ]; then
    if [ "$IS_ROOT" = 1 ]; then add_phone "iPhone: zaufane urządzenia" "brak" "" "brak"; else add_phone "iPhone: zaufane urządzenia" "nie sprawdzono (wymaga sudo)" "/var/db/lockdown" "?"; fi
fi
bk=$(awk -F'\t' '$1 == "kopia" {print $3}' "$T" 2>/dev/null)
if [ -n "$bk" ]; then
    un=$(printf '%s\n' "$bk" | grep -c 'zaszyfrowana: NIE')
    add_phone "iPhone: kopie na dysku" "$(printf '%s\n' "$bk" | grep -c ''), niezaszyfrowanych: $un" "$bk" "Niezaszyfrowana kopia to wiadomości i zdjęcia dla każdego, kto ma ten komputer."
    add_finding DO_WYJASNIENIA telefon "Kopie zapasowe iPhone na dysku (niezaszyfrowanych: $un)" "~/Library/Application Support/MobileSync/Backup" "$bk" "Kopia zawiera prawie wszystko z telefonu." "Jeśli są Twoje, włącz szyfrowanie kopii w Finderze i usuń stare niezaszyfrowane. Jeśli nie są Twoje, zachowaj je jako dowód." "Czy to kopie Twojego telefonu?"
elif [ "$OS" = "Darwin" ]; then add_phone "iPhone: kopie na dysku" "brak" "" "brak"; fi
ad=$(awk -F'\t' '$1 == "adbkey" || $1 == "adbwifi" || $1 == "adb" || $1 == "scrcpy" {print $1 ": " $2 " " $3}' "$T" 2>/dev/null)
if [ -n "$ad" ]; then
    add_phone "Android: debugowanie (ADB)" "ślady użycia" "$ad" "Przez ADB da się instalować aplikacje i wyciągać dane z telefonu."
    add_finding DO_WYJASNIENIA telefon "Ten komputer był używany do debugowania telefonu z Androidem" "~/.android" "$ad" "Przez ADB można zainstalować na telefonie aplikację bez sklepu i bez ikony." "Na telefonie: Opcje programisty > Unieważnij autoryzacje debugowania USB, potem wyłącz Debugowanie USB." "Czy Ty używałeś ADB albo scrcpy?"
else add_phone "Android: debugowanie (ADB)" "brak śladów" "" "brak"; fi
kc=$(awk -F'\t' '$1 == "kdeconnect" {print $2 ": " $3}' "$T" 2>/dev/null)
if [ -n "$kc" ]; then
    add_phone "KDE Connect / GSConnect" "skonfigurowane" "$kc" "Sparowany telefon może wysyłać SMS-y, powiadomienia i pliki na ten komputer."
    add_finding DO_WYJASNIENIA telefon "KDE Connect lub GSConnect ma sparowane urządzenia" "$kc" "$kc" "Każdy z dostępem do komputera widzi powiadomienia i SMS-y z telefonu." "Jeśli nie używasz, odparuj telefon w ustawieniach KDE Connect." "Czy to Twój telefon?"
elif [ "$OS" != "Darwin" ]; then add_phone "KDE Connect / GSConnect" "brak" "" "brak"; fi
btp=$(awk -F'\t' '$1 == "bt" {print $2}' "$T" 2>/dev/null | grep -iE 'iphone|ipad|galaxy|samsung|xiaomi|redmi|pixel|huawei|honor|oneplus|motorola|oppo|realme|nokia|xperia|phone|telefon' | tr '\n' ',' | sed 's/,$//')
[ -n "$btp" ] && add_phone "Bluetooth: sparowane telefony" "sparowane" "$btp" "Samo sparowanie daje niewiele."

# ---------- porównanie z poprzednim audytem
if [ -n "$PREV" ]; then
    ZM="$RAW/.zmiany.txt"; : > "$ZM"
    for f in autostart.tsv programy.txt rozszerzenia.tsv konta.txt; do
        [ -f "$PREV/raw/$f" ] && [ -f "$RAW/$f" ] || continue
        # pusta lista programów oznacza nieudany test, a nie brak programów
        [ "$f" = "programy.txt" ] && [ ! -s "$PREV/raw/$f" ] && continue
        case "$f" in
            programy.txt) flt() { awk '{print $1}' "$1"; } ;;
            konta.txt) flt() { grep '^    ' "$1"; } ;;
            *) flt() { cat "$1"; } ;;
        esac
        flt "$PREV/raw/$f" | LC_ALL=C sort -u > "$RAW/.prev.tmp"
        flt "$RAW/$f" | LC_ALL=C sort -u | LC_ALL=C comm -13 "$RAW/.prev.tmp" - | tr '\t' ' ' | sed "s|^ *|${f%.*}: |" | head -30 >> "$ZM"
    done
    rm -f "$RAW/.prev.tmp"
    if [ -s "$ZM" ]; then
        add_finding DO_WYJASNIENIA zmiany "Co doszło od poprzedniego audytu ($(basename "$PREV")): $(grep -c '' "$ZM") pozycji" "$PREV" "$(head -40 "$ZM")" "Nowe wpisy w autostarcie, programach, rozszerzeniach i kluczach SSH. Po aktualizacjach zawsze coś dochodzi, ale jeśli po sprzątaniu wróciło coś usuniętego, zobaczysz to tutaj." "Przejrzyj listę. Jeśli coś jest obce albo wróciło po usunięciu, daj znać." "Czy wszystkie te nowości to Twoje instalacje lub aktualizacje?"
    else
        echo "Od poprzedniego audytu ($(basename "$PREV")) nic nowego nie doszło w autostarcie, programach, rozszerzeniach ani kluczach SSH." >> "$CLEAN"
    fi
    rm -f "$ZM"
fi

# ============================================================ raport

HOSTN=$(hostname)
DZIEN=$(date '+%Y-%m-%d %H:%M')
nP=$(cut -d"$FS" -f1 "$FIND" | grep -cx POTWIERDZONE)
nS=$(cut -d"$FS" -f1 "$FIND" | grep -cx PODEJRZANE)
nW=$(cut -d"$FS" -f1 "$FIND" | grep -cx DO_WYJASNIENIA)
nPh=$(awk -F"$FS" '$4 != "brak" && $4 != "?" && $1 !~ /^Bluetooth/' "$PHONE" | grep -c '')

# Najważniejsze teraz: maksymalnie 3 konkretne kroki
TOP="$RAW/.top.txt"
{
    awk -F"$FS" '$1 == "POTWIERDZONE" {print "Zabezpiecz dowody i zmień hasła z innego urządzenia, dopiero potem usuwamy: " $3}' "$FIND" | head -2
    awk -F"$FS" '$1 == "PODEJRZANE" {print "Obejrzyjmy razem: " $3}' "$FIND"
    awk -F"$FS" '$4 != "brak" && $4 != "?" && $1 !~ /^Bluetooth/ {print "Telefon: " $1 " (" $2 "). Upewnij się, że to Twoje."}' "$PHONE"
    [ "$nW" -gt 0 ] && echo "Odpowiedz na $nW pytania z sekcji DO WYJAŚNIENIA."
    [ "$IS_ROOT" = 1 ] || echo "Uruchom pełny audyt: sudo bash audyt.sh"
} | head -3 > "$TOP"
[ -s "$TOP" ] || echo "Nic pilnego. Uruchom audyt ponownie za kilka tygodni: raport pokaże, co doszło od dziś." > "$TOP"

if [ "$nP" -gt 0 ]; then
    WERDYKT="Są potwierdzone ślady: $nP pozycja(e) to znane oprogramowanie szpiegujące albo trojan. Nie usuwaj niczego w pośpiechu, najpierw przeczytaj plan działania."
    PEW="0.85 (pewność, że coś jest na rzeczy): rozpoznany konkretny program. Nie wiadomo jeszcze, kto i kiedy go zainstalował."
elif [ "$nS" -gt 0 ]; then
    WERDYKT="Nie ma nic potwierdzonego, ale jest $nS podejrzana(e) pozycja(e) do obejrzenia. Często okazują się zwykłymi programami, dlatego nic nie usuwamy przed rozmową."
    PEW="0.5: zależy od Twoich odpowiedzi i dokładniejszego sprawdzenia plików."
else
    WERDYKT="Nie znalazłem śladów inwigilacji, które da się wykryć tymi metodami."
    if [ "$IS_ROOT" = 1 ]; then PEW="0.75 (pewność, że czysto): pełny audyt z sudo. Zależy jeszcze od odpowiedzi na pytania DO WYJAŚNIENIA."
    else PEW="0.6 (pewność, że czysto): audyt bez sudo, część testów pominięta. Uruchom: sudo bash audyt.sh"; fi
fi
if [ "$nPh" -gt 0 ]; then WERDYKT="$WERDYKT Z tego komputera jest $nPh kanał(y) dostępu do telefonu, opisane w sekcji Telefon."
else WERDYKT="$WERDYKT Nie widać, żeby coś na tym komputerze miało dostęp do telefonu."; fi
[ "$nW" -gt 0 ] && WERDYKT="$WERDYKT Do tego $nW pozycja(e) DO WYJAŚNIENIA: zwykle legalne rzeczy, ale tylko Ty wiesz, czy są Twoje."

LIMITS='Granice tego audytu: dobrze wykrywa komercyjne stalkerware, keyloggery, narzędzia zdalne, typowe trojany i kanały dostępu do telefonu. Nie wykryje z pewnością zaawansowanego malware w jądrze systemu lub firmware ani rządowego oprogramowania szpiegującego na telefonie. "Nic nie znaleziono" znaczy "nic, co da się wykryć tymi metodami", a nie gwarancję. Ocena jest automatyczna, więc PODEJRZANE i DO WYJAŚNIENIA najlepiej omówić, zanim cokolwiek zostanie zmienione.'

PLAN="$RAW/.plan.txt"; : > "$PLAN"
if [ "$nP" -gt 0 ] || [ "$nS" -gt 0 ]; then
    echo "Jeśli podejrzewasz konkretną osobę (partner, ex, rodzina, pracodawca), pamiętaj: usunięcie programu może ją zaalarmować. Najpierw zabezpiecz dowody (skopiuj cały folder audytu), potem z INNEGO, czystego urządzenia zmień hasła do poczty, Apple ID lub konta Google, banku i komunikatorów i włącz weryfikację dwuetapową. Dopiero potem usuwamy." >> "$PLAN"
    echo "W razie zagrożenia: 112. Przemoc lub nękanie: Niebieska Linia 800 120 002 (całodobowo, bezpłatnie). Incydent komputerowy: incydent.cert.pl (CERT Polska)." >> "$PLAN"
fi
[ "$nW" -gt 0 ] && echo "Odpowiedz na pytania z sekcji DO WYJAŚNIENIA. Większość okaże się Twoimi programami." >> "$PLAN"
[ "$IS_ROOT" = 1 ] || echo "Uruchom pełny audyt: sudo bash audyt.sh (dojdą zaufane iPhone'y, elementy logowania, profile, wszystkie procesy i połączenia)." >> "$PLAN"
[ "$OS" = "Darwin" ] && grep -q 'Pełnego dostępu do dysku' "$RAW/_status.json" && echo "Daj Terminalowi Pełny dostęp do dysku (Ustawienia systemowe > Prywatność i ochrona > Pełny dostęp do dysku) i uruchom ponownie, albo przejrzyj sam sekcje Dostępność, Monitorowanie wprowadzania, Nagrywanie ekranu, Kamera i Mikrofon i podaj listę programów." >> "$PLAN"
echo "Naprawa dopiero po omówieniu, pozycja po pozycji: najpierw kopia (Time Machine na macOS), pliki trafiają do folderu kwarantanna, a nie od razu do kosza. Na tym etapie nic nie zostało zmienione." >> "$PLAN"
[ "$nPh" -gt 0 ] && echo "Telefon: odepnij nieznane komputery; na iPhonie Ustawienia > Ogólne > Przenieś lub wyzeruj > Wyzeruj > Wyzeruj ustawienia lokalizacji i prywatności; na Androidzie wyłącz debugowanie USB i unieważnij autoryzacje; stare niezaszyfrowane kopie iPhone usuń albo włącz szyfrowanie." >> "$PLAN"
[ "$OS" = "Darwin" ] && echo "Drugie zdanie: darmowe KnockKnock i BlockBlock od Objective-See (pokazują wszystko, co startuje z systemem). Instalujemy tylko za Twoją zgodą." >> "$PLAN"

NOTCHK="$RAW/.niesprawdzone.txt"; : > "$NOTCHK"
sed -n 's/.*"opis":"\([^"]*\)","wynik":"\([^"]*\)","komunikat":"\([^"]*\)".*/\1|\2|\3/p' "$RAW/_status.json" | while IFS='|' read -r o w k; do
    if [ "$w" != "OK" ]; then echo "$o: $w $k" >> "$NOTCHK"
    elif [ -n "$k" ]; then echo "$o: częściowo, $k" >> "$NOTCHK"; fi
done
[ -s "$OUT/ioc/hosts_full" ] || echo "Lista wskaźników stalkerware: nie pobrano (bez zgody nie łączę się z internetem)." >> "$NOTCHK"
echo "Pamięć DNS: na macOS i Linuksie nie da się jej wiarygodnie odczytać bez głębszej ingerencji, więc nie porównuję jej z listą domen." >> "$NOTCHK"
echo "Historia przeglądarki: celowo nie przeglądana." >> "$NOTCHK"
echo "Sam telefon: komputer pokazuje tylko kanały dostępu. Telefon sprawdzimy osobno, jeśli zechcesz." >> "$NOTCHK"

PERF=$(sed -n '/^=== miejsce na dysku/,$p' "$RAW/wydajnosc.txt" 2>/dev/null)

md_items() { # kategoria
    i=0
    awk -F"$FS" -v k="$1" '$1 == k' "$FIND" | while IFS="$FS" read -r kat obs co gdzie dowod dlaczego dalej pyt; do
        i=$((i + 1))
        echo "### $i. $co"; echo ""
        [ -n "$pyt" ] && { echo "**Pytanie:** $pyt"; echo ""; }
        [ -n "$gdzie" ] && echo "* **Gdzie:** \`$(printf '%s' "$gdzie" | tr '`' "'")\`"
        { printf '%s' "$dowod" | tr "$SEP" '\n'; echo; } | while IFS= read -r d; do [ -n "$d" ] && echo "* **Dowód:** \`$(printf '%s' "$d" | tr '`' "'")\`"; done
        echo "* **Dlaczego ta kategoria:** $dlaczego"
        echo "* **Co dalej:** $dalej"
        echo ""
    done
    awk -F"$FS" -v k="$1" '$1 == k' "$FIND" | grep -q . || { echo "brak"; echo ""; }
}

{
    echo "# Audyt inwigilacji: $HOSTN, $DZIEN"; echo ""
    echo "_$OS, konto: $REAL_USER, sudo: $([ "$IS_ROOT" = 1 ] && echo tak || echo nie). Raport automatyczny z audyt.sh, surowe dane w folderze raw._"; echo ""
    echo "## Werdykt"; echo ""; echo "$WERDYKT"; echo ""; echo "**Poziom pewności:** $PEW"; echo ""
    echo "**POTWIERDZONE: $nP | PODEJRZANE: $nS | DO WYJAŚNIENIA: $nW**"; echo ""
    echo "**Najważniejsze teraz:**"; echo ""; awk '{print NR ". " $0}' "$TOP"; echo ""
    echo "## POTWIERDZONE"; echo ""; md_items POTWIERDZONE
    echo "## PODEJRZANE"; echo ""; md_items PODEJRZANE
    echo "## DO WYJAŚNIENIA (pytania do Ciebie)"; echo ""; md_items DO_WYJASNIENIA
    echo "## Telefon: co ma do niego dostęp z tego komputera"; echo ""
    echo "| Kanał | Stan | Szczegóły | Co to znaczy |"; echo "|---|---|---|---|"
    while IFS="$FS" read -r a b c d; do echo "| $a | $b | $(printf '%s' "$c" | tr "$SEP|" '; ') | $d |"; done < "$PHONE"
    echo ""
    echo "## Czego nie sprawdziłem i dlaczego"; echo ""
    sed 's/^/* /' "$NOTCHK"; echo ""; echo "$LIMITS"; echo ""
    echo "## Plan działania"; echo ""
    awk '{print NR ". " $0}' "$PLAN"; echo ""
    echo "## Porządki i wydajność (wypełniane po sekcji 7)"; echo ""
    echo "Na razie tylko pomiar, nic nie zostało usunięte ani zmienione. Sprzątanie i naprawy zrobimy po usunięciu zagrożeń, każde po pokazaniu, ile miejsca zwolni."; echo ""
    echo '```'; echo "$PERF"; echo '```'; echo ""
    echo "## Sprawdzone, bez uwag"; echo ""
    if [ -s "$CLEAN" ]; then sed 's/^/* /' "$CLEAN"; else echo "brak"; fi
} > "$OUT/RAPORT.md"

# HTML: jeden plik, bez zewnętrznych zasobów
he() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'; }
html_items() {
    n=0
    awk -F"$FS" -v k="$1" '$1 == k' "$FIND" | while IFS="$FS" read -r kat obs co gdzie dowod dlaczego dalej pyt; do
        n=$((n + 1))
        echo "<div class=\"card k-$kat\"><h3>$n. $(he "$co")</h3>"
        [ -n "$pyt" ] && echo "<div class=\"q\"><b>Pytanie:</b> $(he "$pyt")</div>"
        echo "<ul>"
        [ -n "$gdzie" ] && echo "<li><b>Gdzie:</b> <code>$(he "$gdzie")</code></li>"
        { printf '%s' "$dowod" | tr "$SEP" '\n'; echo; } | while IFS= read -r d; do [ -n "$d" ] && echo "<li><b>Dowód:</b> <code>$(he "$d")</code></li>"; done
        echo "<li><b>Dlaczego ta kategoria:</b> $(he "$dlaczego")</li><li><b>Co dalej:</b> $(he "$dalej")</li></ul></div>"
    done
    awk -F"$FS" -v k="$1" '$1 == k' "$FIND" | grep -q . || echo "<p>brak</p>"
}
{
    echo '<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>Audyt inwigilacji</title><style>'
    echo 'body{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1d2433;line-height:1.5;background:#fafbfc}h2{margin-top:32px;border-bottom:2px solid #e3e7ee}.verdict,.card{background:#fff;border:1px solid #d9dee8;border-radius:8px;padding:12px 16px;margin:12px 0}.card{border-left:6px solid #999}.k-POTWIERDZONE{border-left-color:#c62828}.k-PODEJRZANE{border-left-color:#ef8f00}.k-DO_WYJASNIENIA{border-left-color:#1e6fd9}.q{background:#eef4ff;padding:6px 10px;border-radius:4px}code{background:#f1f3f6;padding:1px 4px;border-radius:3px;word-break:break-all}table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #d9dee8;padding:6px 8px;text-align:left;vertical-align:top}pre{background:#f7f8fa;padding:10px;overflow-x:auto}.top{background:#fff8e6;border:1px solid #f0d79a;border-radius:6px;padding:8px 14px}@media print{body{background:#fff}.card,.verdict{break-inside:avoid}}'
    echo '</style></head><body>'
    echo "<h1>Audyt inwigilacji: $(he "$HOSTN"), $DZIEN</h1>"
    echo "<p>$(he "$OS"), konto: $(he "$REAL_USER"), sudo: $([ "$IS_ROOT" = 1 ] && echo tak || echo nie). Surowe dane w folderze raw.</p>"
    echo "<h2>Werdykt</h2><div class=\"verdict\"><p>$(he "$WERDYKT")</p><p><b>Poziom pewności:</b> $(he "$PEW")</p><p><b>POTWIERDZONE: $nP &nbsp; PODEJRZANE: $nS &nbsp; DO WYJAŚNIENIA: $nW</b></p><div class=\"top\"><b>Najważniejsze teraz:</b><ol>"
    while IFS= read -r l; do echo "<li>$(he "$l")</li>"; done < "$TOP"
    echo "</ol></div></div>"
    echo "<h2>POTWIERDZONE</h2>"; html_items POTWIERDZONE
    echo "<h2>PODEJRZANE</h2>"; html_items PODEJRZANE
    echo "<h2>DO WYJAŚNIENIA (pytania do Ciebie)</h2>"; html_items DO_WYJASNIENIA
    echo "<h2>Telefon: co ma do niego dostęp z tego komputera</h2><table><tr><th>Kanał</th><th>Stan</th><th>Szczegóły</th><th>Co to znaczy</th></tr>"
    while IFS="$FS" read -r a b c d; do echo "<tr><td>$(he "$a")</td><td>$(he "$b")</td><td>$(he "$(printf '%s' "$c" | tr "$SEP" ';')")</td><td>$(he "$d")</td></tr>"; done < "$PHONE"
    echo "</table><h2>Czego nie sprawdziłem i dlaczego</h2><ul>"
    while IFS= read -r l; do echo "<li>$(he "$l")</li>"; done < "$NOTCHK"
    echo "</ul><p>$(he "$LIMITS")</p><h2>Plan działania</h2><ol>"
    while IFS= read -r l; do echo "<li>$(he "$l")</li>"; done < "$PLAN"
    echo "</ol><h2>Porządki i wydajność (wypełniane po sekcji 7)</h2><p>Na razie tylko pomiar, nic nie zostało usunięte ani zmienione.</p><pre>$(he "$PERF")</pre>"
    echo "<h2>Sprawdzone, bez uwag</h2><ul>"
    if [ -s "$CLEAN" ]; then while IFS= read -r l; do echo "<li>$(he "$l")</li>"; done < "$CLEAN"; else echo "<li>brak</li>"; fi
    echo "</ul></body></html>"
} > "$OUT/raport.html"

cp "$TOP" "$RAW/.top.keep" 2>/dev/null
rm -f "$PLAN" "$NOTCHK" "$CORPUS" "$STATUS_TMP" "$TOP"

# Paczka dowodów: sumy SHA256 każdego pliku i jedno archiwum do skopiowania na pendrive.
# Suma archiwum pozwala później wykazać, że nikt nic w nim nie zmienił.
sha() { if have sha256sum; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
ZIPHASH=""
if (
    cd "$OUT" || exit 1
    { echo "# Audyt $HOSTN, $REAL_USER, $DZIEN"; find raw skrypty RAPORT.md raport.html -type f ! -name '.top.keep' -print 2>/dev/null | LC_ALL=C sort | while IFS= read -r f; do sha "$f"; done; } > dowody-sha256.txt
    tar -czf dowody.tar.gz --exclude='.top.keep' raw RAPORT.md raport.html dowody-sha256.txt 2>/dev/null || tar -czf dowody.tar.gz raw RAPORT.md raport.html dowody-sha256.txt
    sha dowody.tar.gz > dowody.tar.gz.sha256
); then ZIPHASH=$(cut -d' ' -f1 "$OUT/dowody.tar.gz.sha256" 2>/dev/null); fi
[ -n "${SUDO_USER:-}" ] && chown -R "$SUDO_USER" "$UHOME/audyt-inwigilacji" 2>/dev/null

echo ""
echo "Gotowe. Niczego nie zmieniłem."
echo "  POTWIERDZONE:   $nP"
echo "  PODEJRZANE:     $nS"
echo "  DO WYJAŚNIENIA: $nW"
awk -F"$FS" '$1 == "POTWIERDZONE" || $1 == "PODEJRZANE" {print "    [" $1 "] " $3}' "$FIND" | head -8
echo ""
echo "Najważniejsze teraz:"
awk '{print "  " NR ". " $0}' "$RAW/.top.keep" 2>/dev/null
rm -f "$RAW/.top.keep"
echo ""
echo "Raport: $OUT/raport.html"
echo "        $OUT/RAPORT.md"
echo "Surowe dane (dowody): $RAW"
[ -n "$ZIPHASH" ] && echo "Paczka dowodów: $OUT/dowody.tar.gz (SHA256 $ZIPHASH)"
[ -n "$PREV" ] && echo "Porównano z poprzednim audytem: $PREV"
[ "$IS_ROOT" = 1 ] || echo "Następny krok: sudo bash audyt.sh (pełny audyt)."
