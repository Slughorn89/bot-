# Audyt inwigilacji: komputer i telefon

Mały program, który odpowiada na dwa pytania: **czy coś na tym komputerze mnie śledzi** i **czy coś ma stąd dostęp do mojego telefonu**.

Pierwsza faza tylko czyta. Niczego nie usuwa, nie zamyka programów i nie zmienia ustawień. Dzięki temu nie niszczysz dowodów i nie alarmujesz osoby, która mogła coś zainstalować. Na końcu dostajesz raport po polsku z dowodami i planem, a nie listę 4000 procesów.

Większość takich audytów kończy się wynikiem "czysto" albo "jest TeamViewer, którego nie pamiętasz". To też jest wartościowa odpowiedź.

## Windows

1. Pobierz ten folder (`audyt-inwigilacji/windows`). Na GitHubie: wybierz gałąź, potem **Code > Download ZIP**.
2. Zanim rozpakujesz: prawy przycisk na pliku ZIP > **Właściwości** > zaznacz **Odblokuj** > OK. Inaczej Windows będzie pytał przy każdym pliku.
3. Kliknij dwa razy `uruchom-audyt.bat`. Jeśli zobaczysz "System Windows ochronił ten komputer", wybierz **Więcej informacji > Uruchom mimo to**.
4. Na początku padnie pytanie, czy pobrać publiczną listę domen stalkerware z GitHuba. To tylko pobranie (ruch w jedną stronę), nic nie jest wysyłane. Możesz odpowiedzieć `N`.
5. Po kilku minutach otworzy się raport w przeglądarce.
6. Potem uruchom `uruchom-audyt-admin.bat` i potwierdź okno Kontroli konta użytkownika. To pełny audyt: dochodzą subskrypcje WMI, wykluczenia Defendera, logowania przez Pulpit zdalny, nowe konta i zaufane iPhone'y.

Wyniki lądują w `%USERPROFILE%\audyt-inwigilacji\RRRR-MM-DD_GGMM\` (wersja admin z dopiskiem `_admin`):

| Co | Po co |
|---|---|
| `raport.html` | raport do czytania, jeden plik, działa bez internetu |
| `RAPORT.md` | ten sam raport w formie tekstowej |
| `raw\` | surowe dane i `_status.json` (który test się udał, który pominięto i dlaczego). To są Twoje dowody |
| `dowody.zip` + `dowody-sha256.txt` | paczka do skopiowania na pendrive i suma SHA256 każdego pliku. Suma archiwum (`dowody.zip.sha256`) pozwala później wykazać, że nikt nic w nim nie zmienił |
| `skrypty\` | kopia skryptu, którym zrobiono audyt |
| `kwarantanna\`, `kopia-rejestru\` | na razie puste, przydadzą się przy naprawie |

Uruchomienie ręczne (PowerShell):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File audyt.ps1
```

Opcje: `-Out <folder>`, `-PobierzIOC` (pobierz listę bez pytania), `-BezPytan`, `-NieOtwieraj`. `Bypass` dotyczy tylko tego jednego uruchomienia, polityka systemu się nie zmienia.

**Uruchamiaj co jakiś czas.** Każdy kolejny audyt porównuje się z poprzednim w tym samym trybie (zwykłym albo admin) i pokazuje, co doszło: nowe wpisy autostartu, usługi, zadania, programy, rozszerzenia, certyfikaty, konta. Po sprzątaniu od razu widać, czy coś nie wróciło.

## macOS i Linux

```bash
bash audyt.sh
```

```bash
sudo bash audyt.sh
```

Tu też powstaje paczka dowodów (`dowody.tar.gz` z sumami SHA256) i porównanie z poprzednim uruchomieniem.

Na macOS daj Terminalowi **Pełny dostęp do dysku** (Ustawienia systemowe > Prywatność i ochrona), inaczej nie da się odczytać uprawnień prywatności (TCC) ani kopii iPhone'a. Hasło do sudo wpisujesz tylko w terminalu.

## Co sprawdza

* autostart, usługi, zaplanowane zadania, subskrypcje WMI, ukryte punkty startowe (Winlogon, IFEO, AppInit)
* procesy (podszywanie się pod pliki systemowe, niepodpisane programy z AppData, Temp, Pobranych), połączenia i porty narzędzi zdalnych
* pamięć DNS, plik hosts, proxy, serwery DNS, dodane certyfikaty główne (certyfikat razem z proxy to klasyczny podsłuch HTTPS)
* kto i kiedy używał kamery, mikrofonu i lokalizacji
* programy, rozszerzenia przeglądarek, polityki "Zarządzane przez organizację", zapis do MDM
* konta, administratorzy, Pulpit zdalny, SSH, WinRM
* zapora Windows: czy jest włączona i czy nie wpuszcza połączeń do niepodpisanych programów z nietypowych miejsc
* Defender: czy działa, historia wykryć, wykluczenia, dziennik zdarzeń z 30 dni
* telefon: Łącze z telefonem, zaufane iPhone'y, kopie iPhone'a na dysku (i czy są zaszyfrowane), ślady ADB, scrcpy, KDE Connect, Bluetooth
* znane nazwy: stalkerware, keyloggery, RAT-y, narzędzia zdalne, programy do wyciągania danych z telefonów
* stan dysku, wolne miejsce, ile śmieci da się bezpiecznie usunąć, co obciąża komputer, ile trwa start systemu i które programy go spowalniają (tylko pomiar)

## Jak czytać wyniki

Na samej górze raportu jest werdykt z poziomem pewności i ramka **Najważniejsze teraz**: najwyżej trzy konkretne kroki. Resztę czytasz, kiedy masz czas.

* **POTWIERDZONE**: znane stalkerware, keylogger albo RAT, trafienie w listę wskaźników, wykrycie Defendera.
* **PODEJRZANE**: zachowanie typowe dla malware, np. niepodpisany plik z AppData w autostarcie, zakodowany PowerShell w zadaniu, plik udający systemowy.
* **DO WYJAŚNIENIA**: legalne narzędzia, które dają podgląd lub zdalny dostęp (TeamViewer, AnyDesk, Łącze z telefonem, iMazing). Groźne tylko, jeśli to nie Ty je instalowałeś. Raport zadaje przy nich konkretne pytania.
* **Sprawdzone, bez uwag**: obszary, w których nic nie znaleziono.

Ocena w raporcie jest automatyczna (reguły). Pozycje PODEJRZANE i DO WYJAŚNIENIA warto omówić, zanim cokolwiek zostanie zmienione.

## Co dalej: naprawa i sprzątanie

Usuwanie nie dzieje się automatycznie. Po raporcie omawiamy pozycje i naprawiamy je po kolei, każdą z pokazaną komendą:

1. najpierw punkt przywracania systemu i kopia kluczy rejestru (`kopia-rejestru\`),
2. podejrzane pliki trafiają do `kwarantanna\` z opisem (skąd, hash, dlaczego), a nie od razu do kosza,
3. oficjalny deinstalator, potem tylko te wpisy, które należały do wykrytego zagrożenia. Żadnych "czyścicieli rejestru",
4. na końcu porządki: pliki tymczasowe, Windows Update, `sfc`, `DISM`, `chkdsk`, wyłączenie zbędnego autostartu (odwracalnie).

Najwygodniej zrobić to z Claude działającym na Twoim komputerze (aplikacja Claude Desktop albo `claude remote-control` uruchomione w folderze audytu). Wtedy Claude czyta wyniki na miejscu i prowadzi naprawę krok po kroku.

## Jeśli podejrzewasz konkretną osobę

Partner, ex, ktoś z rodziny, pracodawca na prywatnym sprzęcie: usunięcie programu może tę osobę zaalarmować. Kolejność jest ważna:

1. zabezpiecz dowody (skopiuj cały folder audytu na pendrive),
2. z innego, czystego urządzenia zmień hasła do poczty, Apple ID lub konta Google, banku i komunikatorów, włącz weryfikację dwuetapową,
3. dopiero potem usuwamy.

W razie zagrożenia: **112**. Przemoc lub nękanie: **Niebieska Linia 800 120 002** (całodobowo, bezpłatnie). Incydent komputerowy: zgłoszenie do CERT Polska przez **incydent.cert.pl**.

## Prywatność

Dane zostają na komputerze. Program nie wysyła list procesów, plików, hashy ani raportu nigdzie. Jedyny ruch sieciowy to opcjonalne pobranie publicznej listy wskaźników z [AssoEchap/stalkerware-indicators](https://github.com/AssoEchap/stalkerware-indicators). Historia przeglądarki nie jest czytana.

Raport zawiera nazwy programów, ścieżki i nazwy kont. Zanim komuś go prześlesz, przejrzyj go.

## Granice

Audyt dobrze wykrywa komercyjne stalkerware, keyloggery, narzędzia zdalne, typowe RAT-y i kanały dostępu do telefonu. Nie wykryje z pewnością zaawansowanego malware w jądrze systemu lub firmware ani rządowego oprogramowania szpiegującego na telefonie. "Nic nie znaleziono" znaczy "nic, co da się wykryć tymi metodami", a nie gwarancję.
