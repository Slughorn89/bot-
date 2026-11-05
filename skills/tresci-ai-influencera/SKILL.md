---
name: "tresci-ai-influencera"
description: "Planuje, pisze i analizuje treści wirtualnej persony AI (karta, kalendarz, hooki, opisy, prompty Flux/LoRA i wideo, wyniki postów). Używaj przy każdej pracy nad contentem AI influencera."
---

# Treści AI influencera

Używaj zawsze, gdy ktoś planuje, pisze albo ocenia treści wirtualnej postaci AI: karta persony, kalendarz postów, opisy, hooki do reelsów, scenariusze, stories, karuzele, wątki na X, bio, prompty do zdjęć (ComfyUI, Flux, LoRA, SDXL) i wideo (image-to-video), odpowiedzi na komentarze, analiza wyników z Instagrama albo TikToka, plan pod Instagram, TikTok, X, Threads lub Fanvue. Także wtedy, gdy nie pada słowo "influencer", a chodzi o konto prowadzone przez postać wygenerowaną przez AI.

Cel: jedna spójna postać, która wygląda tak samo na każdym zdjęciu, mówi jednym głosem, daje odbiorcy powód, żeby ją obserwować, i działa zgodnie z zasadami platform i prawem (AI Act, UOKiK), więc konto nie dostaje bana ani ucięcia zasięgów. Kalendarz wychodzi w formacie gotowym do arkusza i do pipeline'u (n8n + ComfyUI/Higgsfield).

## Zasady nadrzędne (nie podlegają negocjacji)
- **Jawnie AI.** Persona otwarcie jest wirtualna: dopisek w bio na każdej platformie, oznaczenie platformy (Instagram: przełącznik "AI-generated profile" w edycji profilu, od 31.08.2026 zastąpił etykietę "AI creator"; TikTok: przełącznik "AI-generated content" przy każdym poście z realistyczną postacią; Fanvue: konto oznaczone jako AI) i tag w opisie tam, gdzie to potrzebne. W UE od 2.08.2026 działa art. 50 AI Act: realistyczne treści z AI trzeba oznaczać. Jawność to atut, a "kulisy AI" to zwykle jeden z najmocniejszych filarów.
- **Dorosła postać.** Wiek w karcie co najmniej 21 lat. W promptach "woman", nigdy "girl", zero słów kojarzących się z dziećmi i szkołą (mundurek, nastolatka, petite young itp.).
- **SFW.** Ten skill pisze treści bezpieczne dla ogólnej publiczności: moda, lifestyle, fitness, podróże, humor, kulisy, edukacja. Nie pisze treści seksualnych ani rozbieranych, także na płatne kanały.
- **Nie realne osoby.** Żadnego "wygląda jak [celebrytka]", twarzy realnych ludzi, cudzych zdjęć jako referencji twarzy, podszywania się.
- **Uczciwie wobec fanów.** Szkice odpowiedzi nie udają człowieka, nie obiecują spotkań ani relacji, nie naciskają na zakup. Na "czy jesteś prawdziwa?" persona odpowiada zgodnie z prawdą. Człowiek przegląda odpowiedzi przed wysłaniem.
- **Reklama oznaczona.** Każda współpraca, afiliacja, barter, paczka PR i promocja własnego produktu jest oznaczona zgodnie z UOKiK (szczegóły niżej). Wzrost tylko metodami zgodnymi z regulaminem.

## Przebieg

### 0. Przygotuj narzędzie (raz na sesję)
Wypakuj `infl_tool.py` z ostatniej części. Jeśli znasz katalog skilla (podany przy uruchomieniu jako "Base directory"):
```bash
mkdir -p /tmp/infl && python3 -I -c "import sys;s=open(sys.argv[1],encoding='utf-8').read();open('/tmp/infl/infl_tool.py','w',encoding='utf-8').write(s.rsplit('# >>> infl_tool.py',1)[1].split('# <<< infl_tool.py')[0])" "KATALOG_SKILLA/SKILL.md"
```
Jeśli nie znasz katalogu, zapisz blok kodu z ostatniej części jako `/tmp/infl/infl_tool.py` bez zmian. Trzy komendy: `plan` (szkielet kalendarza), `check` (kontrola gotowego kalendarza), `stats` (analiza wyników).

### 1. Karta persony
Wszystko wychodzi z karty (szablon niżej). Jeśli użytkownik ją ma, trzymaj się jej co do słowa. Jeśli nie, zbuduj ją najpierw na podstawie niszy, platform i rynku, pokaż i dopiero potem planuj. Karta to dokument do zachowania, więc dostarcz ją jako dokument albo plik.

Sekcja **Kotwice** w karcie jest czytana przez narzędzie, więc trzymaj dokładnie format `- klucz: wartość; wartość`. Z niej `plan` bierze trigger, miejsca i stroje, a `check` pilnuje, żeby każdy prompt miał trigger i stałe cechy, prompt zgadzał się z sesją (miejsce i strój), emoji nie przekraczały limitu, sprzedaż nie przekraczała limitu i nie pojawiały się zakazane tematy. Opcjonalnie: `sprzedaz_max` (np. `1/6` albo `15`, w procentach) i `swiatla` (własna lista świateł do sesji). Brak triggera LoRA: pisz `TRIGGER` i powiedz, że trzeba go podmienić.

### 2. Strategia na okres
Ustal albo przyjmij i wypisz jako **Założenia**:
- **Cel z liczbą**: np. +800 obserwujących w miesiąc, 3% kliknięć w link, 20 subskrypcji. Bez liczby nie da się potem ocenić wyników.
- **Rytm do utrzymania.** Domyślnie: Instagram 5 postów w feedzie tygodniowo (1 zdjęcie, 2 karuzele, 2 reelsy) i stories codziennie, TikTok 4 tygodniowo, X albo Threads 1 dziennie. Mniej i regularnie bije dużo przez tydzień.
- **3-5 filarów z udziałami.** Przykład: styl/nisza 40%, codzienność i humor 25%, kulisy AI 15%, interakcja 10%, sprzedaż 10%. Sprzedaż nie więcej niż 20-25%.
- **Lejek**: dokąd idzie odbiorca (link w bio, newsletter, Fanvue, sklep z afiliacją) i jakie CTA go tam prowadzą.
- **Okazje w okresie** (narzędzie wypisuje je samo, lista niżej). Dni delikatne bez sprzedaży i żartów.

### 3. Szkielet kalendarza (narzędzie)
```bash
python3 -I /tmp/infl/infl_tool.py plan --start 2026-11-02 --days 14 --karta karta.md \
  --rytm "instagram:post=1,karuzela=2,reel=2,story=7;tiktok:reel=4;x:tweet=7" \
  --filary "styl/nisza:40,codzienność:25,kulisy AI:15,interakcja:10,sprzedaż:10" --out kalendarz.csv
```
Dostajesz wiersze z datą, godziną (rozrzuconą o kilka minut, żeby nie wyglądało na bota), platformą, formatem, filarem (bez powtórek pod rząd), okazją, sesją zdjęciową (miejsce, strój, światło), kadrem, początkiem promptu, `id`, `proporcje` i `seed` sesji. Narzędzie samo:
- przenosi publikacje z dni delikatnych na najbliższy zwykły dzień (zostaje jedna spokojna story, opis w `uwagi`); `--delikatne zostaw` wyłącza przenoszenie,
- łączy miejsca i stroje w różne pary (po pierwszym przejściu przez kartę kombinacje się przesuwają); `--miejsca "a; b"` i `--stroje "x; y"` zmieniają kolejność albo zestaw na ten okres bez ruszania karty,
- ostrzega, gdy `--start` jest przed dzisiejszą datą (`--dzis RRRR-MM-DD` nadpisuje "dziś").

Potem uzupełniasz treść: hook, caption, hashtagi, dokończony prompt (zamień `[CZYNNOŚĆ]`, `[APARAT]`, `[NASTRÓJ]`), prompt wideo, CTA, uwagi. Szkielet możesz zmieniać: przesuń post, zmień filar, dodaj wiersz. Godziny to punkt startowy; po 2-4 tygodniach ustawiasz je według `stats`.

Kolumny w tej kolejności. Pipeline je czyta, więc żadnej nie usuwaj ani nie zmieniaj nazw; własne kolumny dopisuj na końcu:
`data, godzina, platforma, format, filar, okazja, sesja, kadr, swiatlo, hook, caption, hashtagi, prompt_obrazu, prompt_wideo, cta, oznaczenie_ai, reklama, status, uwagi, id, proporcje, seed`

- `data` RRRR-MM-DD, `godzina` GG:MM w strefie odbiorców (Polska: Europe/Warsaw).
- `format`: post, karuzela, reel, story, tweet, wątek, zdjęcie (Fanvue). Jeden wiersz `story` to sekwencja dnia (3-5 klatek).
- `reklama`: `brak` albo rodzaj i marka: `współpraca: Marka`, `afiliacja: Sklep`, `barter: Marka`, `autopromocja: ebook`. Narzędzie wtedy wymaga oznaczenia na początku opisu.
- `status`: `pending` dla nowego. Pipeline generuje wiersze `pending`, człowiek zmienia na `approved`, po publikacji `published`.
- `uwagi`: scenariusz reela, teksty slajdów karuzeli, info o repurpose. Narzędzie samo podpowiada, który klip z IG może iść na TikToka.
- `id`: `persona-RRRRMMDD-NN`, unikalne. Po nim pipeline aktualizuje status, więc nie zmieniaj go po imporcie. Przy przesuwaniu wiersza id zostaje.
- `proporcje`: 4:5 dla feedu i karuzeli, 9:16 dla stories, reelsów i TikToka. `seed`: stały dla sesji, warianty to seed+1, seed+2.
- Gdy środowisko ma typ arkusza (Sheets), dostarcz kalendarz także jako arkusz; CSV zostaw zawsze do importu.

### 4. Sesje, prompty i produkcja
**Pracuj sesjami, nie pojedynczymi zdjęciami.** Jedna sesja = jedno miejsce, jeden strój, jedno światło, 6 różnych kadrów. Tak wygląda prawdziwy twórca i tak łatwiej o spójność. Z jednej sesji robisz kilka publikacji:

| Z jednej sesji (6 kadrów) | Co powstaje |
|---|---|
| 3-4 najlepsze kadry | karuzela |
| 1 kadr | post albo okładka reela |
| 1 kadr + image-to-video | reel, potem ten sam klip na TikTok z innym hookiem i dźwiękiem |
| 2 kadry "z ręki" | stories |
| kulisy generowania | tweet albo story z filaru kulisy AI |

Formuła promptu (Flux, język naturalny, 40-80 słów, po angielsku):
`TRIGGER woman, [kadr], [stałe cechy z karty], [strój], [czynność/emocja], [miejsce + 1-2 detale], [światło + pora], [aparat/obiektyw/styl], [nastrój]`

Przykład: `lnx_woman woman, half-body shot, shoulder-length copper hair, green eyes, light freckles, oversized beige knit sweater, holding a ceramic cup and laughing at something off-camera, Kraków Kazimierz café with rain on the window, soft overcast window light, shot on 35mm film, shallow depth of field, natural skin texture, candid lifestyle photo`

- Stałe cechy zawsze tymi samymi słowami z karty. Inaczej LoRA się rozjedzie.
- Detal, wide shot, POV i over-the-shoulder mogą być bez twarzy, wtedy cechy, których nie widać, pomijasz.
- Flux dev na start: guidance 3-3.5, 20-30 kroków, siła LoRA 0.8-1.0. **Seed**: stały w ramach sesji (zmieniasz tylko kadr i czynność), nowy seed na wariant. 2-3 warianty na wiersz, wybierasz najlepszy.
- Spójność twarzy: IP-Adapter FaceID albo PuLID z referencją własnej persony, FaceDetailer na koniec. Sprawdź dłonie, tekst w tle, biżuterię (zmienia się między kadrami).
- Proporcje: feed i karuzela 4:5 (np. 896×1120, skaluj do 1080×1350), stories, reels, TikTok 9:16 (768×1344, skaluj do 1080×1920).
- SDXL zamiast Flux: na końcu `prompt_obrazu` dopisz `| NEG: deformed hands, extra fingers, blurry, watermark, text`.
- Karuzela: kolejne slajdy w `prompt_obrazu` oddzielone ` || `.
- Wideo (image-to-video z gotowego zdjęcia): tylko ruch i kamera, 1-2 zdania, bez zmiany wyglądu: `slow push-in, she turns toward the window and smiles, hair moves slightly, 5 s`.
- Zapas: generuj z wyprzedzeniem 3-5 dni, nie w dniu publikacji.

**Tekst wynika z sesji, nie odwrotnie.** Hook i caption opisują to, co jest na zdjęciu tego wiersza: ten strój, to miejsce, tę porę. Jeśli pomysł na hook wymaga innego stroju albo miejsca ("Trencz na 4 sposoby"), przenieś wiersz do sesji z trenczem albo zmień sesję i prompt razem, nigdy sam tekst. Dzień tygodnia w hooku ("Poniedziałek w Kazimierzu") musi się zgadzać z datą. Hook z listą ("3 swetry", "na 4 sposoby") to karuzela, slajd na pozycję, a nie pojedyncze zdjęcie. Takie rozjazdy (trencz w hooku, kurtka na zdjęciu; "poniedziałek" w sobotę; lista w jednym zdjęciu) dają najsłabsze posty, bo obietnica z pierwszej linii nie zgadza się z tym, co widać.

### 5. Teksty i formaty
**Głos** z karty: długość zdań, emoji (które i ile), zwroty. Każdy tekst przeczytaj w myślach jej głosem; brzmi jak reklama, to przepisz.

**Hook** (pierwsza linia albo pierwsze 2 s, maks. ok. 10 słów). Typy do rotacji, każdy w kalendarzu zaczyna się inaczej:
- kontrast: "Wszyscy kupują X. Ja wróciłam do Y."
- liczba: "3 swetry, które noszę na okrągło"
- POV: "POV: jesteś AI i pierwszy raz widzisz śnieg w Krakowie"
- błąd: "Przestań prasować oversize, serio"
- pytanie z wyborem: "Kawa na mieście czy w domu? Bez kombinowania"
- kulisy: "Tak powstaje moje zdjęcie, krok po kroku"
- mini historia: "Miałam dziś wyjść o 8. Wyszłam o 11."
Bez clickbaitu, który kłamie.

**Caption**: hook, 1-3 zdania wartości albo historii, jedno pytanie albo jedno CTA. Instagram działa też jak wyszukiwarka, więc w pierwszym zdaniu użyj słów, które ktoś by wpisał ("jesienne stylizacje do pracy").

**Hashtagi**: Instagram maks. 5 (twardy limit od grudnia 2025, liczone razem z komentarzami): 2 niszowe, 1-2 tematyczne, 1 własny. Threads 1 temat. X 0-2. TikTok 3-5. Zestawy rotuj.

**CTA**: jedno na post. Najlepsze dla zasięgu prowadzą do udostępnienia albo zapisu ("wyślij komuś, kto...", "zapisz na zakupy"), bo to najmocniejsze sygnały dla Instagrama, zwłaszcza u osób, które jeszcze nie obserwują. Sprzedażowe najwyżej co 4-5 post.

**Formaty** (scenariusze i teksty slajdów wpisuj do `uwagi`):
- **Karuzela (5-8 slajdów)**: S1 hook na zdjęciu, maks. 8 słów tekstu; S2-S6 jedna myśl na slajd; ostatni: podsumowanie + "zapisz". Tekst na grafice nakładasz w edytorze, nie w prompcie (modele psują litery).
- **Reel / TikTok (7-20 s)**: `0-2 s: hook na ekranie + ruch | 2-12 s: treść, zmiana ujęcia co 2-3 s | końcówka: puenta albo pętla do początku | audio: trend wybrany w aplikacji albo voiceover`. Muzykę z biblioteki dodajesz w aplikacji przy publikacji, nie wklejasz cudzych utworów do pliku.
- **Stories (sekwencja dnia)**: rano kontekst ("dziś plan na..."), w środku naklejka (ankieta, quiz, suwak, pytanie), wieczorem kulisy albo odpowiedź na pytania. Naklejki dają odpowiedzi w DM, a DM to mocny sygnał relacji.
- **Wątek na X**: 1/ hook i obietnica, 3-6 tweetów po jednej myśli, ostatni z CTA. Każdy do 280 znaków.
- **Threads**: krótko, rozmowa, pytanie do ludzi. 1 temat.
- **Voiceover**: jeśli persona ma głos (np. ElevenLabs), to głos zaprojektowany od zera, nigdy klon realnej osoby. Napisy zawsze, większość ogląda bez dźwięku.

Fakty, porady zdrowotne, finansowe i prawne persona podaje ostrożnie albo wcale (YouTube od lipca 2026 odbiera monetyzację personom AI w tych tematach i powtarzalnym treściom AI).

### 6. Sprawdź (obowiązkowo)
```bash
python3 -I /tmp/infl/infl_tool.py check kalendarz.csv --karta karta.md
```
(bez karty: `--trigger SLOWO_LORA`). Popraw wszystkie **BŁĘDY**: pusty caption, limity znaków i hashtagów, brak oznaczenia AI, brak triggera, słowa niedozwolone, reklama bez poprawnego oznaczenia, deklaracja osobistego użycia produktu w reklamie ("noszę od tygodnia", "testowałam"), powtórzone `id`, zła data. Przejrzyj **OSTRZEŻENIA**: daty z przeszłości ze statusem do publikacji, prompt niezgodny z sesją (inny strój albo miejsce), dzień tygodnia w hooku niezgodny z datą, lista w pojedynczym zdjęciu, filar sprzedażowy bez wpisu w `reklama`, złe proporcje, placeholdery w promptach, brak stałych cech, "girl", powtarzalne hooki i opisy, podobne prompty pod rząd (kolejne kadry tej samej sesji są OK), za dużo sprzedaży, sprzedaż w dzień delikatny, za dużo emoji, zakazane tematy z karty. Potem przeczytaj 3 losowe teksty: czy brzmią jak ta sama osoba i czy opisują to, co jest w prompcie?

### 7. Dostarcz
Jeśli `check` pokazał daty z przeszłości, zacznij od tego odpowiedź: ile wierszy, od kiedy, i dwie opcje (przesunąć cały plan o tydzień albo dać tym wierszom status `draft`). Pipeline działa według statusu, więc ostrzeżenie schowane w środku odpowiedzi łatwo przeoczyć.
1. `kalendarz-<persona>-<okres>.csv` (+ arkusz, jeśli jest typ Sheets).
2. Karta persony jako dokument, gdy była tworzona albo zmieniana.
3. W czacie krótko: rozkład filarów, 3 najmocniejsze hooki, okazje w okresie, co wygenerować najpierw (pierwsze 2 sesje), co włączyć na platformach (oznaczenia AI, płatne partnerstwo przy reklamie).

### 8. Pętla wyników (gdy użytkownik da eksport albo liczby)
```bash
python3 -I /tmp/infl/infl_tool.py stats wyniki.csv --kalendarz kalendarz.csv --platforma instagram
```
Czyta eksport z Meta Business Suite, Instagrama, TikTok Studio albo własny arkusz (rozpoznaje polskie i angielskie nazwy kolumn). Kalendarz dokleja filar, gdy eksport go nie ma (dopasowanie po dacie i godzinie). Gdy dane są tylko w czacie, zapisz je do CSV i puść przez narzędzie, nie licz w głowie.

Miary:
- **ER z zasięgu** = (polubienia + komentarze + zapisania + udostępnienia) / zasięg × 100. Gdy nie ma zasięgu, mianownik to wyświetlenia (TikTok: (polubienia + komentarze + udostępnienia) / wyświetlenia).
- **Udostępnienia i zapisania na 1000 zasięgu**: najlepszy znak, że treść ma wartość i pójdzie dalej.
- **Obserwacje na 1000 zasięgu**: czy treść zamienia widzów w obserwujących.
Porównuj z własną medianą konta, nie z cudzymi "benchmarkami". Poniżej 20 postów to wskazówki, nie reguły.

Narzędzie pokazuje też typ hooka (kulisy, liczba, pytanie, POV, błąd, hack, mini historia, kontrast) i ostrzega, gdy pora pokrywa się z formatem (np. wszystkie zdjęcia szły o 18:30, a reelsy o 19:30). Wtedy nie wyciągaj wniosku o porze, tylko zaplanuj test: ten sam format i filar o dwóch porach. Dni tygodnia z mniej niż 3 postami na dzień to szum.

Zanim wyciągniesz wnioski, porównaj kalendarz z tym, co wyszło naprawdę: czy hook pasuje do zdjęcia z sesji, czy dzień tygodnia w tekście zgadza się z datą, czy posty sprzedażowe mają oznaczenie reklamy w faktycznym opisie, czy któryś hook poszedł dwa razy. Takie rozjazdy często tłumaczą słaby wynik lepiej niż filar albo pora. Problemy z oznaczeniem reklamy zgłoś jako pilne, do poprawy od razu, niezależnie od nowego planu.

Z wyników wyciągasz 3 decyzje na następny okres: czego więcej (filar, format, pora), czego mniej albo inaczej, jeden test (np. 3 reelsy z hookiem typu kulisy o 21:00). Nowe `--filary` i godziny wchodzą do kolejnego `plan`.

## Oznaczenia: AI i reklama

**AI** (stan: październik 2026, sprawdzaj co kwartał):
| Platforma | Co włączyć | Co grozi bez tego |
|---|---|---|
| Instagram, Threads | profil: "AI-generated profile" (Edytuj profil); posty z C2PA/IPTC dostają "AI info" | ograniczony zasięg, brak polecania; Instagram sam wykrywa i powiadamia, status w "Stan konta" |
| TikTok | przełącznik "AI-generated content" przy każdym poście z realistyczną postacią | natychmiastowy strike; treści w pełni z AI nie łapią się do Creator Rewards |
| Fanvue | konto oznaczone jako AI + informacja w bio i opisach | ryzyko blokady konta i wypłat |
| X | dopisek w bio | zgłoszenia i ograniczenia za wprowadzanie w błąd |
| YouTube | w Studio zaznacz "treści zmienione lub syntetyczne" | usuwanie filmów, wyłączenie z programu partnerskiego |
Automatycznych etykiet C2PA nie da się i nie należy usuwać. W UE od 2.12.2026 wchodzi też obowiązek oznaczania maszynowego (metadane) dla systemów już na rynku, więc zostawiaj metadane w plikach.

**Reklama (UOKiK, rekomendacje z 26.09.2022)**:
- Oznaczenie od razu widoczne, na początku opisu albo na zdjęciu/w nagraniu: `[reklama]`, `#reklama`, `#współpracareklamowa`, `#materiałsponsorowany`, przy własnym produkcie `#autopromocja`. Samo `#ad`, `#współpraca`, `#collab` nie wystarczy. Nazwij markę.
- Dwa poziomy: własne oznaczenie w treści + funkcja platformy "płatne partnerstwo" / "Paid partnership" / TikTok "Branded content".
- Dotyczy też afiliacji, barteru, paczek PR i kodów rabatowych. Na stories oznaczenie na każdej klatce z produktem.
- Kara dla twórcy i marki: do 10% obrotu. Persona AI to nie wyjątek, a podwójna jawność: AI + reklama.

**Persona AI a produkt.** Persona niczego nie nosi, nie testuje i nie kupuje, więc w reklamie nie pisze "noszę od tygodnia", "przetestowałam", "po 10 praniach dalej jak nowy". Mówi o stylizacji, wyglądzie, wyborze i zestawieniu ("tak bym to zestawiła", "3 sposoby na ten kardigan"). Wygląd produktu nie może wprowadzać w błąd: najlepiej zdjęcia od marki; jeśli generujesz produkt na personie, to z referencją zdjęcia produktu (za zgodą marki), z porównaniem koloru i faktury oraz z dopiskiem w opisie, że to wizualizacja AI.

## Okazje w Polsce (narzędzie liczy je samo, z Wielkanocą i świętami ruchomymi)
Sprzedażowe i lekkie: Walentynki, Dzień Kobiet, Tłusty Czwartek, Prima aprilis, Majówka, Dzień Matki, Dzień Ojca, Dzień Chłopaka, Halloween, Andrzejki, Black Friday, Cyber Monday, Mikołajki, Wigilia i Święta, Sylwester, Blue Monday, pierwszy dzień wiosny i lata.
**Delikatne (bez sprzedaży i żartów, najwyżej spokojny, krótki post albo przerwa)**: 1.11 Wszystkich Świętych, 2.11 Zaduszki, 11.11 Narodowe Święto Niepodległości, Wielki Piątek, 1.08 rocznica Powstania Warszawskiego, 1.09 rocznica wybuchu II wojny. Persona AI nie "przeżywa" żałoby ani patriotycznych wzruszeń w pierwszej osobie; lepiej neutralny gest (np. biało-czerwone akcenty, cisza w publikacjach).

## Komentarze i wiadomości (szkice do przejrzenia przez człowieka)
| Sytuacja | Jak odpowiedzieć | Przykład |
|---|---|---|
| "Czy jesteś prawdziwa?" | prawda, lekko, bez tłumaczenia się | "Nie, jestem postacią AI 🙂 Za mną stoi człowiek, który mnie wymyśla. Kawa z tego zdjęcia za to istnieje naprawdę ☕" |
| komplement | dziękuj konkretnie, pytanie zwrotne | "Dzięki! Ten sweter to mój numer jeden w listopadzie. Ty też masz taki na okrągło?" |
| pytanie o produkt | konkret + oznaczenie, jeśli to afiliacja | "To [marka], link w bio (link afiliacyjny)." |
| prośba o spotkanie, numer, "bądź moją dziewczyną" | ciepło, ale jasno: jestem AI, spotkań nie będzie | "Miło mi, ale jestem wirtualna, więc kawy razem nie wypijemy. Wpadaj tu, zawsze odpisuję w komentarzach." |
| hejt o AI | spokojnie albo wcale; nie karm trolla | "Rozumiem, że AI nie każdemu pasuje. Tu wszystko jest jawne, możesz scrollować dalej 🙂" |
| obrażanie, groźby, spam | nie odpowiadaj, ukryj, zablokuj, zgłoś | brak |
| osoba w kryzysie albo niepełnoletnia | nie ciągnij rozmowy, człowiek przejmuje; przy kryzysie podaj telefon zaufania 116 123 (dorośli) albo 116 111 (dzieci i młodzież) | brak szkicu persony |
Nigdy: obietnic relacji, "tylko dla ciebie", nacisku na zakup, udawania, że persona jest człowiekiem.

## Fanvue (subskrypcja)
- Publiczne zapowiedzi (teasery) na innych platformach: SFW i bez obietnic, których nie ma w środku.
- Treści dla subskrybentów w tym skillu: serie zdjęć z sesji, wcześniejszy dostęp, kulisy powstawania, ankiety, personalizowane pozdrowienia SFW.
- Odpowiedzi do fanów według tabeli wyżej, zawsze z przeglądem człowieka.

## Wzrost zgodnie z regulaminem
Działa: regularność, serie (ten sam format co tydzień), odpowiedzi na komentarze w pierwszej godzinie, kolaboracje z innymi twórcami (także AI) przez "Collab", trendujące dźwięki dodane w aplikacji, przypięte posty z najlepszymi treściami, słowa kluczowe w opisach, przenoszenie najlepszych reelsów na TikTok.
Nie rób: kupowania obserwujących i polubień, grup wzajemnego lajkowania (engagement pods), masowego follow/unfollow, masowych DM-ów, fałszywych konkursów, botów komentujących. Konkurs tylko z regulaminem i zgodnie z zasadami platformy.

## Pipeline (gdy użytkownik chce automatyzacji)
Kalendarz CSV → arkusz → n8n czyta wiersze `pending` → generowanie (ComfyUI przez API albo Higgsfield) → człowiek akceptuje (`approved`) → publikacja (Instagram Graph API, TikTok Content Posting API z flagą treści AI, X API) → `published`. Workflow buduje skill `automatyzacje-n8n-make`. Jeśli w sesji jest podłączony Higgsfield (generowanie postaci, zdjęć, wideo) albo ElevenLabs (voiceover), możesz z nich korzystać, ale generowanie kosztuje kredyty: najpierw pokaż plan i liczbę generacji, dopiero potem odpalaj. Publikacji nie automatyzuj bez etapu akceptacji przez człowieka.

## Szablon karty persony
```markdown
# [Imię]: karta persony
**Status:** wirtualna postać AI (jawnie). Linia do bio: "[np. Wirtualna stylistka AI z Krakowa ✨ treści generowane przez AI]"

## Kotwice (czyta je narzędzie, zachowaj format)
- trigger: [słowo LoRA]
- cechy: [cecha 1]; [cecha 2]; [cecha 3]
- miejsca: [miejsce 1]; [miejsce 2]; [miejsce 3]
- stroje: [strój 1]; [strój 2]; [strój 3]
- emoji_max: [np. 2]
- zakazane: [temat 1]; [temat 2]
- sprzedaz_max: [opcjonalnie, np. 1/6]

## Podstawy
- Imię, wiek (min. 21), miasto/kraj (fikcyjne lub ogólne), język postów
- Nisza i obietnica dla odbiorcy (jedno zdanie: co dostajesz, obserwując ją)

## Osobowość
- Big Five (1-10): otwartość, sumienność, ekstrawersja, ugodowość, neurotyczność + jak to widać w tekstach
- Wartości, humor, czego nie znosi, o czym nigdy nie mówi

## Głos
- Długość zdań, ty/wy, emoji (lista), ulubione zwroty, zakazane słowa
- 3 przykładowe zdania w jej stylu
- Odpowiedź na "czy jesteś prawdziwa?" (jej słowami, zgodnie z prawdą)

## Wygląd (stały, do promptów)
- Cechy z Kotwic opisane zawsze tymi samymi słowami (po angielsku, jak w promptach)
- Styl ubioru, paleta kolorów, akcesoria-wizytówki
- Styl zdjęć: aparat, światło, ulubione kadry

## Filary treści
| Filar | Udział | Formaty | Przykład |

## Lejek i monetyzacja
- Link w bio prowadzi do: [...]
- Typy CTA i jak często; współprace i afiliacje zawsze z oznaczeniem

## Granice
- SFW na wszystkich kanałach, brak podobieństwa do realnych osób
- Tematy zakazane (te same co w Kotwicach)
- Oznaczanie AI: bio + oznaczenie platformy + tag w opisie tam, gdzie wymagany
- Reklama: oznaczenie na początku, marka z nazwy, bez deklaracji osobistego używania produktu
```

## Ściąga platform (stan: październik 2026)
| Platforma | Limit opisu | Hashtagi | Formaty |
|---|---|---|---|
| Instagram | 2200 znaków | maks. 5 (twardy limit) | post 4:5, karuzela do 20 slajdów, reel 9:16, stories |
| TikTok | 4000 znaków | 3-5 | wideo 9:16, karuzela zdjęć |
| X | 280 znaków (bez Premium) | 0-2 | tweet, wątek, zdjęcie |
| Threads | 500 znaków | 1 temat | tekst, zdjęcie |
| Fanvue | długie opisy OK | do 5 | zdjęcia, wideo, wiadomości; media publiczne bezpieczne dla ogółu; operator przechodzi weryfikację; odpowiedzi AI do fanów z przeglądem człowieka |

Zasady i limity zmieniają się szybko. Przy planie na nowy kwartał sprawdź aktualne zasady AI i limity platform, na których działa persona.

## infl_tool.py
Kod narzędzia z kroku 0. Nie zmieniaj go przy wypakowywaniu.
```python
# >>> infl_tool.py
#!/usr/bin/env python3
"""Narzędzie do treści AI influencera.
  plan   --start RRRR-MM-DD --days N [--rytm "instagram:post=1,karuzela=2,reel=2,story=7;tiktok:reel=4;x:tweet=7"]
         [--filary "styl:40,codziennosc:25,kulisy AI:15,interakcja:10,sprzedaz:10"] [--karta karta.md] [--out plik.csv] [--seed 7]
         [--miejsca "a; b"] [--stroje "x; y"] [--delikatne przesun|zostaw] [--persona imie] [--dzis RRRR-MM-DD]
         -> szkielet kalendarza: daty, godziny, filary, okazje, sesje zdjęciowe, kadry, światło, id, proporcje, seed
  check  kalendarz.csv [--karta karta.md] [--trigger SLOWO] [--dzis RRRR-MM-DD] [--json]
         -> limity platform, oznaczenia AI i reklamy, spójność z kartą i sesją, daty, powtórki, granice treści
  stats  wyniki.csv [--kalendarz kalendarz.csv] [--platforma instagram] [--json]
         -> co działa: filary, formaty, typy hooków, dni, pory (z ostrzeżeniem, gdy pora = format), najlepsze i najsłabsze posty
Kod wyjścia check: 0 OK, 1 błędy, 2 problem z plikiem."""
import csv, io, json, random, re, statistics, sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

CORE = ["data", "godzina", "platforma", "format", "filar", "hook", "caption", "hashtagi",
        "prompt_obrazu", "prompt_wideo", "cta", "oznaczenie_ai", "status"]
PLAN_COLS = ["data", "godzina", "platforma", "format", "filar", "okazja", "sesja", "kadr", "swiatlo",
             "hook", "caption", "hashtagi", "prompt_obrazu", "prompt_wideo", "cta", "oznaczenie_ai", "reklama", "status", "uwagi",
             "id", "proporcje", "seed"]
RATIO = {"story": "9:16 768x1344", "reel": "9:16 768x1344", "post": "4:5 896x1120", "karuzela": "4:5 896x1120", "zdjęcie": "4:5 896x1120"}
LIVE = {"pending", "approved", "draft", "szkic", "do akceptacji", "zaakceptowany"}
LIMITS = {"instagram": (2200, 5), "tiktok": (4000, 5), "x": (280, 2), "threads": (500, 1),
          "facebook": (63206, 5), "fanvue": (5000, 5), "youtube": (5000, 5)}
AI_LABEL = {"instagram": "profil: etykieta AI-generated profile + post: AI info",
            "tiktok": "przełącznik AI-generated content", "x": "bio: wirtualna postać AI",
            "threads": "profil IG: AI-generated profile", "fanvue": "konto oznaczone jako AI + info w opisie",
            "facebook": "etykieta AI info", "youtube": "Studio: zaznaczone treści syntetyczne"}
STATUSES = {"pending", "draft", "approved", "published", "szkic", "do akceptacji", "zaakceptowany", "opublikowany"}
SLOTS = {("instagram", "post"): ["18:40", "12:20", "20:10"], ("instagram", "karuzela"): ["19:15", "12:35"],
         ("instagram", "reel"): ["19:40", "21:05", "17:50"], ("instagram", "story"): ["08:20", "13:10", "21:30"],
         ("tiktok", "reel"): ["19:20", "21:40", "16:30"], ("x", "tweet"): ["08:35", "12:50", "21:15"],
         ("threads", "post"): ["09:10", "20:25"], ("fanvue", "zdjęcie"): ["20:30"], ("fanvue", "post"): ["20:30"]}
WEEKEND_SHIFT = {"08": "10", "07": "10", "12": "12", "13": "13"}
KADRY = ["close-up portrait", "half-body shot", "full-body shot", "mirror selfie", "over-the-shoulder shot",
         "POV shot with her hand in frame", "detail shot (hands, cup, shoes)", "wide shot showing the place"]
SWIATLO = ["soft overcast daylight", "golden hour sunlight", "window light", "blue hour city lights",
           "neon night light", "warm indoor lamp light", "flash snapshot at night", "bright morning sun"]
MINOR = re.compile(r"\b(teen\w*|schoolgirl\w*|school\s*uniform|young\s*girl|little\s*girl|child\w*|kid|kids|minor|underage|loli\w*|barely\s*legal|"
                   r"jailbait|1[0-7]\s*-?\s*(yo|y/o|years?\s*old|lat\w*)|nastolat\w*|uczennic\w*|dziewczynk\w*|dziecko|dziecka|małoletn\w*|niepełnoletn\w*|gimnazjalist\w*|licealist\w*)\b", re.I)
EXPLICIT = re.compile(r"\b(nsfw|nude\w*|naked|topless|nipple\w*|explicit|porn\w*|sex|erotic\w*|"
                      r"nago|naga|nagie|goła|gołe|rozebran\w*|erotyczn\w*)\b", re.I)
SUGGESTIVE = re.compile(r"\b(sexy|seksown\w*|sensual|seductive|uwodzicielsk\w*|lingerie|bieliźn\w*|bielizn\w*)\b", re.I)
LIKENESS = re.compile(r"\b(look\s*alike|lookalike|looks\s*like|in\s*the\s*style\s*of|resembling|sobowtór\w*|wygląda\s*jak|podobn\w*\s+do)\b", re.I)
AD_KIND = re.compile(r"współprac|reklam|afili|barter|autopromo|sponsor|paczk|ambasad", re.I)
AD_WEAK = re.compile(r"(#ad|#sponsored|#collab|#współpraca|#partner)(?![\wąćęłńóśźż])", re.I)
AD_LABEL = re.compile(r"(\[?#?reklama\]?|#?materiał\s*reklamowy|#?współpraca\s*reklamowa|#?materiał\s*sponsorowany|#?autopromocja|#?lokowanie)", re.I)
AD_HINT = re.compile(r"kod\s*rabat|rabat\w*|zniżk\w*|link\s*afili|link\s*w\s*bio.*(kup|zamów)|-\d{1,2}\s*%|\bpromocj\w*", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤]")
# persona AI niczego nie nosi ani nie testuje: w reklamie to deklaracja nieprawdziwa
USE_CLAIM = re.compile(r"\b(nosz[eę]\s+(go|ją|je|to)?\s*od|nosiłam\s+(go|ją|je)?\s*(przez|od|cał)|testowałam|przetestowałam|używam\s+(go|jej|ich)?\s*od|"
                       r"używałam|sprawdziłam\s+na\s+sobie|kupiłam|mam\s+(go|ją|je)\s+od|po\s+\d+\s+(dniach|tygodniach|praniach))", re.I)
LIST_HOOK = re.compile(r"^\W*\d+\s+\w+|\bna\s+\d+\s+sposob\w*|\b\d+\s+(rzecz\w*|sposob\w*|stylizac\w*|błęd\w*|hack\w*|krok\w*|zasad\w*|trik\w*)", re.I)
# dzień "dzisiejszy" w hooku: mianownik, "w + biernik" i przymiotnik ("piątkowy"); "po piątku", "co niedzielę" to inne dni
WEEKDAY_RE = [re.compile(r"\bponiedział(ek|kow\w*)\b", re.I), re.compile(r"\bwtor(ek|kow\w*)\b", re.I), re.compile(r"\bśrod(a|ę|ow\w*)\b", re.I),
              re.compile(r"\bczwart(ek|kow\w*)\b", re.I), re.compile(r"\bpiąt(ek|kow\w*)\b", re.I), re.compile(r"\bsobot(a|ę)\b|\bsobotni\w*", re.I),
              re.compile(r"\bniedziel(a|ę|n\w*)\b", re.I)]
NOT_TODAY = {"po", "przed", "od", "do", "co", "każdy", "każdą", "wczoraj", "jutro", "zeszły", "zeszłą", "zeszłym", "przyszły", "przyszłą", "przyszłym",
             "następny", "następną", "ostatni", "ostatnią"}
DAY_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
DAY_W = ["w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę", "w niedzielę"]


def named_days(text):
    out = []
    for i, rx in enumerate(WEEKDAY_RE):
        for m in rx.finditer(text or ""):
            before = re.findall(r"\w+", text[:m.start()].lower())[-2:]
            if not NOT_TODAY & set(before):
                out.append(i)
    return out
HOOK_TYPES = [("POV", r"^\W*pov\b"), ("kulisy", r"kulis|tak powstaje|promp|wersj\w* mnie|\bAI\s+(psuje|pilnuje|robi|myli)|odrzucon"),
              ("liczba", r"^\W*\d|\b\d+\s+(rzecz|sposob|stylizac|swetr|błęd|hack|krok)|na\s+\d+\s+sposob"),
              ("pytanie", r"\?"), ("błąd", r"^\W*(przestań|nie\s+(noś|rób|kupuj|prasuj))|\bbłąd"),
              ("hack", r"\bhack"), ("mini historia", r"^\W*\w+łam\b"), ("kontrast", r"\bwszyscy\b|\bzamiast\b|\bale\b")]


# ---------------------------------------------------------------- wspólne
def read_csv(path):
    text = open(path, encoding="utf-8-sig").read()
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def plat(p):
    p = (p or "").strip().lower()
    alias = {"ig": "instagram", "insta": "instagram", "reels": "instagram", "stories": "instagram",
             "twitter": "x", "x/twitter": "x", "tt": "tiktok", "fb": "facebook", "yt": "youtube"}
    if p in alias:
        return alias[p]
    for k in LIMITS:
        if k in p:
            return k
    return p


def words(s):
    return set(re.findall(r"[a-ząćęłńóśźż0-9]{4,}", (s or "").lower()))


def jacc(a, b):
    a, b = words(a), words(b)
    return len(a & b) / len(a | b) if len(a | b) >= 6 else 0


def read_card(path):
    """Czyta sekcję '## Kotwice' z karty persony: linie 'klucz: wartość; wartość'."""
    card = {}
    if not path:
        return card
    text = open(path, encoding="utf-8").read()
    h = re.search(r"^#\s+([^:\n#]+?)\s*(:|$)", text, re.M)
    if h:
        card["_name"] = [h.group(1).strip()]
    m = re.search(r"^##\s*Kotwice.*?$(.*?)(^##\s|\Z)", text, re.M | re.S)
    block = m.group(1) if m else text
    for line in block.splitlines():
        mm = re.match(r"^\s*[-*]?\s*`?([a-ząćęłńóśźż_ ]+)`?\s*:\s*(.+)$", line.strip(), re.I)
        if mm:
            key = mm.group(1).strip().lower().replace(" ", "_")
            vals = [v.strip().strip("`") for v in mm.group(2).split(";") if v.strip()]
            card[key] = vals
    return card


# ---------------------------------------------------------------- okazje PL
def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def occasions(y):
    """(data) -> (nazwa, czy_delikatna). Delikatne: bez sprzedaży i żartów."""
    o = {}
    fixed = {(1, 1): "Nowy Rok", (1, 6): "Trzech Króli", (1, 21): "Dzień Babci", (1, 22): "Dzień Dziadka",
             (2, 14): "Walentynki", (3, 8): "Dzień Kobiet", (3, 21): "pierwszy dzień wiosny", (4, 1): "Prima aprilis",
             (5, 1): "Majówka", (5, 2): "Majówka", (5, 3): "Majówka / 3 Maja", (5, 26): "Dzień Matki",
             (6, 23): "Dzień Ojca", (6, 21): "pierwszy dzień lata", (9, 30): "Dzień Chłopaka", (10, 31): "Halloween",
             (11, 29): "Andrzejki", (12, 6): "Mikołajki", (12, 24): "Wigilia", (12, 25): "Boże Narodzenie",
             (12, 26): "drugi dzień świąt", (12, 31): "Sylwester"}
    for (mo, d), n in fixed.items():
        o[date(y, mo, d)] = (n, False)
    for (mo, d), n in {(11, 1): "Wszystkich Świętych", (11, 2): "Zaduszki", (11, 11): "Narodowe Święto Niepodległości",
                       (8, 1): "rocznica Powstania Warszawskiego", (9, 1): "rocznica wybuchu II wojny"}.items():
        o[date(y, mo, d)] = (n, True)
    e = easter(y)
    o[e - timedelta(days=52)] = ("Tłusty Czwartek", False)
    o[e - timedelta(days=2)] = ("Wielki Piątek", True)
    o[e] = ("Wielkanoc", False)
    o[e + timedelta(days=1)] = ("Lany Poniedziałek", False)
    o[e + timedelta(days=60)] = ("Boże Ciało", False)
    nov = [date(y, 11, d) for d in range(1, 31) if date(y, 11, d).weekday() == 3]
    bf = nov[3] + timedelta(days=1)
    o[bf] = ("Black Friday", False)
    o[bf + timedelta(days=3)] = ("Cyber Monday", False)
    jan = [date(y, 1, d) for d in range(1, 32) if date(y, 1, d).weekday() == 0]
    o[jan[2]] = ("Blue Monday", False)
    return o


def occ(d):
    return occasions(d.year).get(d)


def today(a):
    try:
        return datetime.strptime(a["dzis"], "%Y-%m-%d").date() if a.get("dzis") else date.today()
    except ValueError:
        return date.today()


def slug(s):
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return re.sub(r"[^a-z0-9]+", "-", (s or "post").translate(tr).lower()).strip("-") or "post"


def sales_limit(card):
    """Kotwica 'sprzedaz_max: 1/6' albo '15' (procent). Domyślnie 25%."""
    v = (card.get("sprzedaz_max") or card.get("sprzedaż_max") or [""])[0].replace("%", "").replace(",", ".").strip()
    try:
        if "/" in v:
            x, y = v.split("/", 1)
            return float(x) / float(y)
        return float(v) / 100 if v else 0.25
    except (ValueError, ZeroDivisionError):
        return 0.25


def hook_type(t):
    for name, rx in HOOK_TYPES:
        if re.search(rx, t or "", re.I):
            return name
    return "inne" if (t or "").strip() else "?"


# ---------------------------------------------------------------- plan
def parse_rytm(s):
    out = []
    for part in s.split(";"):
        if ":" not in part:
            continue
        p, fmts = part.split(":", 1)
        for f in fmts.split(","):
            if "=" in f:
                k, v = f.split("=")
                out.append((plat(p), k.strip().lower(), int(v)))
    return out


def parse_filary(s):
    res = []
    for part in (s or "").split(","):
        if ":" in part:
            k, v = part.rsplit(":", 1)
            res.append((k.strip(), float(v)))
    return res or [("styl/nisza", 40), ("codzienność", 25), ("kulisy AI", 15), ("interakcja", 10), ("sprzedaż", 10)]


def weighted_sequence(filary, n, rnd):
    tot = sum(w for _, w in filary)
    quotas = [(k, w / tot * n) for k, w in filary]
    counts = {k: int(q) for k, q in quotas}
    rest = sorted(quotas, key=lambda kv: -(kv[1] - int(kv[1])))
    for k, _ in rest[: n - sum(counts.values())]:
        counts[k] += 1
    pool = [k for k, c in counts.items() for _ in range(c)]
    rnd.shuffle(pool)
    for _ in range(200):  # rozbij powtórki pod rząd
        bad = [i for i in range(1, len(pool)) if pool[i] == pool[i - 1]]
        if not bad:
            break
        i = bad[0]
        j = rnd.randrange(len(pool))
        pool[i], pool[j] = pool[j], pool[i]
    return pool


def jitter(hhmm, rnd, weekend):
    h, m = map(int, hhmm.split(":"))
    if weekend and f"{h:02d}" in WEEKEND_SHIFT:
        h = int(WEEKEND_SHIFT[f"{h:02d}"])
    m = (m + rnd.choice([-11, -7, -4, 3, 6, 9, 13])) % 60
    return f"{h:02d}:{m:02d}"


def cmd_plan(a):
    start = datetime.strptime(a["start"], "%Y-%m-%d").date()
    days = int(a.get("days", 7))
    rnd = random.Random(int(a.get("seed", 7)))
    rytm = parse_rytm(a.get("rytm", "instagram:post=1,karuzela=2,reel=2,story=7;tiktok:reel=4;x:tweet=7"))
    filary = parse_filary(a.get("filary"))
    card = read_card(a.get("karta"))
    split = lambda v: [x.strip() for x in v.split(";") if x.strip()]
    # --miejsca / --stroje nadpisują kartę na ten okres (np. inna kolejność sesji), bez zmiany samej karty
    miejsca = split(a.get("miejsca", "")) or card.get("miejsca") or ["UZUPEŁNIJ_MIEJSCE_1", "UZUPEŁNIJ_MIEJSCE_2", "UZUPEŁNIJ_MIEJSCE_3"]
    stroje = split(a.get("stroje", "")) or card.get("stroje") or ["UZUPEŁNIJ_STRÓJ_1", "UZUPEŁNIJ_STRÓJ_2", "UZUPEŁNIJ_STRÓJ_3"]
    swiatla = card.get("swiatla") or card.get("światła")
    trig = (card.get("trigger") or ["TRIGGER"])[0]
    end = start + timedelta(days=days - 1)
    rows = []
    by_plat = defaultdict(list)
    for p, f, per_week in rytm:
        total = round(per_week * days / 7)
        if total > 0:
            by_plat[p].append([f, total])
    for p, fl in by_plat.items():
        stories = [x for x in fl if x[0] == "story"]
        feed = [x for x in fl if x[0] != "story"]
        seq = []  # przeplatanie formatów: post, reel, karuzela, reel...
        while any(c for _, c in feed):
            for x in sorted(feed, key=lambda x: -x[1]):
                if x[1] > 0:
                    seq.append(x[0])
                    x[1] -= 1
        n = len(seq)
        used = Counter()
        for i, f in enumerate(seq):
            di = min(days - 1, int((i + 0.5) * days / n)) if n else 0
            d = start + timedelta(days=di)
            slots = SLOTS.get((p, f)) or SLOTS.get((p, "post")) or ["19:00"]
            slot = slots[used[d] % len(slots)]
            if used[d] and slot[:2] == "19":
                slot = "12:40"
            used[d] += 1
            rows.append({"data": d.isoformat(), "godzina": jitter(slot, rnd, d.weekday() >= 5), "platforma": p, "format": f})
        for f, total in stories:
            for i in range(total):
                di = min(days - 1, int(i * days / total))
                d = start + timedelta(days=di)
                st_slots = SLOTS.get((p, "story")) or SLOTS[("instagram", "story")]
                rows.append({"data": d.isoformat(), "godzina": jitter(st_slots[i % len(st_slots)], rnd, d.weekday() >= 5), "platforma": p, "format": f})
    # dni delikatne: publikacje z feedu, TikToka i X przechodzą na najbliższy zwykły dzień, zostaje jedna spokojna story
    is_del = lambda d: bool(occ(d) and occ(d)[1])
    shifted = 0
    if a.get("delikatne", "przesun") != "zostaw":
        for r in rows:
            d = datetime.strptime(r["data"], "%Y-%m-%d").date()
            if r["format"] == "story" or not is_del(d):
                continue
            cand = [d + timedelta(days=k) for k in range(1, days) if d + timedelta(days=k) <= end and not is_del(d + timedelta(days=k))]
            cand += [d - timedelta(days=k) for k in range(1, days) if d - timedelta(days=k) >= start and not is_del(d - timedelta(days=k))]
            if not cand:
                continue
            nd = cand[0]
            if any(x is not r and x["platforma"] == r["platforma"] and x["format"] != "story" and x["data"] == nd.isoformat() for x in rows):
                r["godzina"] = jitter("12:40", rnd, nd.weekday() >= 5)
            r["data"] = nd.isoformat()
            r["uwagi"] = f"przesunięte z {d} ({occ(d)[0]}, dzień delikatny)"
            shifted += 1
    by_p = defaultdict(list)
    for r in rows:
        if r["format"] != "story":
            by_p[r["platforma"]].append(r)
    for p, lst in by_p.items():
        lst.sort(key=lambda r: (r["data"], r["godzina"]))
        seq = weighted_sequence(filary, len(lst), rnd)
        for r, fil in zip(lst, seq):
            r["filar"] = fil
    for r in rows:
        if r["format"] == "story":
            r["filar"] = rnd.choice(["codzienność", "interakcja"])
        d = datetime.strptime(r["data"], "%Y-%m-%d").date()
        o = occ(d)
        r["okazja"] = (o[0] + (" (delikatna: bez sprzedaży i żartów)" if o[1] else "")) if o else ""
        if o and o[1] and r["format"] == "story":
            r["filar"] = "codzienność"
            r["uwagi"] = "dzień delikatny: jedna spokojna klatka, bez naklejek, muzyki, żartów i sprzedaży"
        elif o and o[1] and re.search(r"sprzeda|promo|oferta|afili", r["filar"], re.I):
            r["filar"] = "codzienność"
    cechy = ", ".join(card.get("cechy", [])) or "[STAŁE CECHY Z KARTY]"
    visual = [r for r in sorted(rows, key=lambda r: (r["data"], r["godzina"])) if r["platforma"] not in ("x", "threads")]
    # pary miejsce+strój po przekątnych: najpierw 1:1 jak w karcie, potem przesunięte, więc kombinacje się nie zapętlają
    combos = [(p_, (p_ + d_) % len(stroje)) for d_ in range(len(stroje)) for p_ in range(len(miejsca))]
    sid, k = 0, 0
    for i, r in enumerate(visual):
        if i % 6 == 0:  # jedna sesja = jedno miejsce, strój i światło, 6 różnych kadrów
            sid += 1
            pi, oi = combos[(sid - 1) % len(combos)]
            place, outfit = miejsca[pi], stroje[oi]
            light = swiatla[(sid - 1) % len(swiatla)] if swiatla else SWIATLO[(sid * 3) % len(SWIATLO)]
            sess_seed = int(start.strftime("%m%d")) * 100 + sid
        r["sesja"] = f"S{sid:02d}: {place} | {outfit} | {light}"
        r["kadr"] = KADRY[k % len(KADRY)]
        r["swiatlo"] = light
        r["seed"] = str(sess_seed)
        k += 1
        r["prompt_obrazu"] = f"{trig} woman, {r['kadr']}, {cechy}, {outfit}, [CZYNNOŚĆ], {place}, {light}, [APARAT], [NASTRÓJ]"
    ig_reels = sorted([r for r in rows if r["platforma"] == "instagram" and r["format"] == "reel"], key=lambda r: r["data"])
    taken = set()
    for r in sorted(rows, key=lambda r: r["data"]):
        if r["platforma"] == "tiktok" and r["format"] == "reel":
            d = datetime.strptime(r["data"], "%Y-%m-%d").date()
            cand = [x for x in ig_reels if id(x) not in taken and 0 <= (d - datetime.strptime(x["data"], "%Y-%m-%d").date()).days <= 3]
            if cand:
                taken.add(id(cand[0]))
                r["uwagi"] = "; ".join(x for x in (r.get("uwagi", ""), f"repurpose: klip z IG reel {cand[0]['data']}, nowy hook i dźwięk, bez znaku wodnego") if x)
    for r in rows:
        r.setdefault("sesja", "")
        r.setdefault("kadr", "")
        r.setdefault("swiatlo", "")
        r["oznaczenie_ai"] = AI_LABEL.get(r["platforma"], "oznaczenie AI platformy")
        r["reklama"] = "brak"
        r["status"] = "pending"
        r["proporcje"] = RATIO.get(r["format"], "") if r["platforma"] not in ("x", "threads") else ""
    rows.sort(key=lambda r: (r["data"], r["godzina"], r["platforma"]))
    persona = slug(a.get("persona") or (card.get("_name") or ["post"])[0])
    per_date = Counter()
    for r in rows:  # stały identyfikator wiersza: pipeline aktualizuje po nim status
        per_date[r["data"]] += 1
        r["id"] = f"{persona}-{r['data'].replace('-', '')}-{per_date[r['data']]:02d}"
    out = a.get("out") or "kalendarz-szkielet.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PLAN_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in PLAN_COLS})
    cnt = Counter((r["platforma"], r["format"]) for r in rows)
    fil = Counter(r["filar"] for r in rows if r["format"] != "story")
    print(f"Zapisano {out}: {len(rows)} wierszy, {start} + {days} dni, sesji zdjęciowych: {sid}")
    print("Formaty: " + ", ".join(f"{p}/{f} {c}" for (p, f), c in sorted(cnt.items())))
    print("Filary (bez stories): " + ", ".join(f"{k} {v}" for k, v in fil.most_common()))
    oc = sorted({(r["data"], r["okazja"]) for r in rows if r["okazja"]})
    if oc:
        print("Okazje w okresie: " + "; ".join(f"{d} {n}" for d, n in oc))
    if shifted:
        print(f"Dni delikatne: {shifted} publikacji przesuniętych na najbliższy zwykły dzień (opis w kolumnie uwagi)")
    if start < today(a):
        print(f"UWAGA: start {start} jest przed dzisiejszą datą ({today(a)}). Wiersze z przeszłości pipeline może opublikować od razu: "
              "przesuń start albo daj im status draft")
    if not card:
        print("Bez --karta: miejsca, stroje i trigger to placeholdery UZUPEŁNIJ_/TRIGGER")
    return 0


# ---------------------------------------------------------------- check
def cmd_check(a):
    try:
        rows = read_csv(a["file"])
    except Exception as ex:
        print(f"BŁĄD: nie da się wczytać CSV: {ex}")
        return 2
    if not rows:
        print("BŁĄD: pusty kalendarz")
        return 2
    card = read_card(a.get("karta"))
    trig = a.get("trigger") or (card.get("trigger") or [None])[0]
    cechy = card.get("cechy", [])
    emax = int((card.get("emoji_max") or ["99"])[0]) if (card.get("emoji_max") or ["x"])[0].isdigit() else 99
    zakazane = [z.lower() for z in card.get("zakazane", [])]
    miejsca_k, stroje_k = card.get("miejsca", []), card.get("stroje", [])
    limit_sp = sales_limit(card)
    dzis = today(a)
    E, W, I = [], [], []
    past, ids = [], Counter()
    missing = [c for c in CORE if c not in rows[0]]
    if missing:
        E.append(f"Brak kolumn: {missing}")
    if not trig:
        W.append("Brak triggera (--trigger albo karta z 'trigger:'), nie sprawdzam słowa LoRA")
    pillars, per_day, hooks, caps = Counter(), defaultdict(Counter), Counter(), []
    prev_prompt, prev_sesja, prev_kadr, dates = {}, {}, {}, []
    for n, r in enumerate(rows, start=2):
        tag = f"wiersz {n} ({r.get('data', '')} {r.get('platforma', '')} {r.get('format', '')})"
        p, fmt = plat(r.get("platforma")), r.get("format", "").lower()
        cap, hs = r.get("caption", ""), r.get("hashtagi", "")
        tags = set(re.findall(r"#\w+", hs + " " + cap))
        lim = LIMITS.get(p)
        if lim:
            full = len(cap) + (1 + len(hs) if hs and hs not in cap else 0)
            if full > lim[0]:
                E.append(f"{tag}: caption + hashtagi = {full} znaków, limit {p}: {lim[0]}")
            if len(tags) > lim[1] and fmt != "story":
                (E if p in ("instagram", "threads") else W).append(f"{tag}: {len(tags)} hashtagów, {p} maks. {lim[1]}")
        elif p:
            I.append(f"{tag}: nieznana platforma, pomijam limity")
        img, vid = r.get("prompt_obrazu", ""), r.get("prompt_wideo", "")
        alltext = " ".join([r.get("hook", ""), cap, hs, img, vid, r.get("cta", "")])
        hook = r.get("hook", "")
        st = r.get("status", "").lower()
        if fmt != "story" and not cap.strip():
            E.append(f"{tag}: pusty caption. Kalendarz nie idzie do pipeline'u bez gotowego opisu")
        elif fmt == "story" and not (cap.strip() or r.get("cta", "").strip() or r.get("uwagi", "").strip()):
            W.append(f"{tag}: story bez tekstu, naklejki i opisu w uwagach")
        if r.get("id"):
            ids[r["id"]] += 1
        ratio = r.get("proporcje", "")
        if ratio and RATIO.get(fmt) and not ratio.startswith(RATIO[fmt].split()[0]):
            W.append(f"{tag}: proporcje {ratio}, a {fmt} potrzebuje {RATIO[fmt].split()[0]}")
        ses = r.get("sesja", "")
        if img and ses and (miejsca_k or stroje_k):
            parts = [x.strip() for x in ses.split(":", 1)[-1].split("|")]
            low = img.lower()
            for kind, lst, val in (("strój", stroje_k, parts[1] if len(parts) > 1 else ""), ("miejsce", miejsca_k, parts[0] if parts else "")):
                other = [x for x in lst if x.lower() != val.lower() and x.lower() in low]
                if val and other and val.lower() not in low:
                    W.append(f"{tag}: prompt ma {kind} '{other[0]}', a sesja '{val}'. Zmień sesję wiersza albo prompt i tekst")
        if MINOR.search(img + " " + vid):
            E.append(f"{tag}: w prompcie słowo kojarzone z osobą niepełnoletnią ('{MINOR.search(img + ' ' + vid).group(0)}'). Persona jest dorosła")
        if EXPLICIT.search(alltext):
            E.append(f"{tag}: treść seksualna/rozbierana ('{EXPLICIT.search(alltext).group(0)}'). Tylko SFW")
        elif SUGGESTIVE.search(alltext):
            W.append(f"{tag}: '{SUGGESTIVE.search(alltext).group(0)}' ryzykuje ograniczenie zasięgu. Opisz styl inaczej")
        if LIKENESS.search(img):
            W.append(f"{tag}: odwołanie do podobieństwa do kogoś ('{LIKENESS.search(img).group(0)}'). Bez wyglądu realnych osób")
        unfinished = "..." in img or re.search(r"\[[A-ZĄĆĘŁŃÓŚŹŻ ]{3,}\]|UZUPEŁNIJ", img)
        if img and not unfinished:
            if trig and trig.lower() not in img.lower():
                E.append(f"{tag}: prompt_obrazu bez triggera '{trig}'")
            miss = [c for c in cechy if c.lower() not in img.lower()]
            if miss and not re.search(r"detail shot|detal|wide shot|from behind|back view|POV|over-the-shoulder", img, re.I):
                W.append(f"{tag}: prompt bez stałych cech z karty: {miss}")
            if re.search(r"\bgirl\b", img, re.I):
                W.append(f"{tag}: 'girl' w prompcie, pisz 'woman'")
        elif img:
            W.append(f"{tag}: prompt_obrazu ma placeholdery do uzupełnienia")
        if fmt not in ("tekst", "text", "tweet", "wątek", "thread") and not img and p not in ("x", "threads"):
            W.append(f"{tag}: brak prompt_obrazu dla formatu '{fmt}'")
        if fmt in ("reel", "tiktok", "wideo", "video") and not vid:
            W.append(f"{tag}: reel bez prompt_wideo (ruch/kamera)")
        if not r.get("oznaczenie_ai"):
            E.append(f"{tag}: puste oznaczenie_ai")
        if p == "fanvue" and not re.search(r"\bAI\b|#ai\b|sztuczn|wirtualn|virtual|synthetic", cap, re.I):
            W.append(f"{tag}: Fanvue bez informacji o AI w opisie")
        rk = r.get("reklama", "")
        is_ad = bool(rk and rk.lower() not in ("brak", "nie", "-", "none"))
        if is_ad and USE_CLAIM.search(hook + " " + cap):
            E.append(f"{tag}: w reklamie persona AI deklaruje osobiste użycie ('{USE_CLAIM.search(hook + ' ' + cap).group(0)}'). "
                     "To nieprawda i wprowadza w błąd: mów o stylizacji, wyglądzie i wyborze, nie o noszeniu czy testach")
        if not is_ad and re.search(r"sprzeda|afili|promo|oferta", r.get("filar", ""), re.I) and AD_LABEL.search(cap[:90]):
            I.append(f"{tag}: oznaczenie reklamy jest w opisie, ale kolumna reklama jest pusta. Uzupełnij rodzaj i markę dla pipeline'u")
        elif not is_ad and re.search(r"sprzeda|afili|promo|oferta", r.get("filar", ""), re.I):
            W.append(f"{tag}: filar '{r.get('filar')}', a reklama = '{rk or 'puste'}'. Wpisz rodzaj i markę (np. 'afiliacja: Sklep') albo zmień filar")
        if fmt in ("post", "zdjęcie") and LIST_HOOK.search(hook):
            W.append(f"{tag}: hook obiecuje listę ('{LIST_HOOK.search(hook).group(0).strip()}'), a format to jedno zdjęcie. Lista pasuje do karuzeli")
        if is_ad:
            if AD_KIND.search(rk) and not AD_LABEL.search(cap[:90]):
                if AD_LABEL.search(cap):
                    E.append(f"{tag}: oznaczenie reklamy jest, ale za daleko. Musi być widoczne od razu, na początku opisu (pierwsze ok. 90 znaków)")
                elif AD_WEAK.search(cap):
                    E.append(f"{tag}: '{AD_WEAK.search(cap).group(0)}' to za mało dla UOKiK. Użyj [reklama], #reklama albo #współpracareklamowa na początku i nazwij markę")
                else:
                    E.append(f"{tag}: treść komercyjna ({rk}) bez oznaczenia na początku opisu ([reklama], #reklama, #współpracareklamowa, #autopromocja). Wymóg UOKiK + przełącznik 'płatne partnerstwo'")
        elif AD_HINT.search(cap) and not AD_LABEL.search(cap):
            W.append(f"{tag}: opis wygląda na reklamę ('{AD_HINT.search(cap).group(0)}'), a kolumna reklama jest pusta/brak. Jeśli to współpraca, afiliacja lub własny produkt: oznacz")
        try:
            d = datetime.strptime(r.get("data", ""), "%Y-%m-%d").date()
            dates.append(d)
            per_day[d][p] += 1
            if d < dzis and st in LIVE:
                past.append(d)
            named = named_days(hook)
            if named and d.weekday() not in named:
                W.append(f"{tag}: hook mówi '{DAY_PL[named[0]]}', a publikacja wypada {DAY_W[d.weekday()]}. Zmień tekst albo datę")
            o = occ(d)
            if o and o[1] and (re.search(r"sprzeda|promo|oferta|afili", r.get("filar", ""), re.I) or (rk and rk.lower() not in ("brak", "nie", "-", ""))):
                W.append(f"{tag}: {o[0]} to dzień delikatny. Bez sprzedaży, zmień filar albo przesuń")
        except ValueError:
            E.append(f"{tag}: data musi mieć format RRRR-MM-DD")
        if r.get("godzina") and not re.match(r"^\d{1,2}:\d{2}$", r["godzina"]):
            W.append(f"{tag}: godzina w formacie GG:MM")
        elif r.get("godzina", "").endswith(":00") and p not in ("fanvue",):
            I.append(f"{tag}: pełna godzina ({r['godzina']}); przesunięcie o kilka minut wygląda mniej automatycznie")
        if st and st not in STATUSES:
            I.append(f"{tag}: nietypowy status '{r.get('status')}'")
        if fmt != "story" and r.get("filar"):
            pillars[r["filar"]] += 1
        h = " ".join(re.findall(r"\w+", hook.lower())[:4])
        if h:
            hooks[h] += 1
        if fmt in ("reel",) and len(hook.split()) > 12:
            W.append(f"{tag}: hook reela ma {len(hook.split())} słów; na pierwsze 2 s maks. ok. 10")
        ne = len(EMOJI.findall(cap))
        if ne > emax:
            W.append(f"{tag}: {ne} emoji, karta pozwala na {emax}")
        for z in zakazane:
            zr = r"\b" + r"\s+".join(re.escape(w[:max(3, len(w) - 2)]) + r"\w*" for w in z.split()) if z.split() else None
            if zr and re.search(zr, alltext, re.I):
                W.append(f"{tag}: temat/słowo zakazane w karcie: '{z}'")
        same_session_new_frame = ses and ses == prev_sesja.get(p) and r.get("kadr") != prev_kadr.get(p)
        if (img and prev_prompt.get(p) and not unfinished and not same_session_new_frame
                and "repurpose" not in r.get("uwagi", "").lower() and jacc(img, prev_prompt[p]) > 0.75):
            W.append(f"{tag}: prompt prawie jak poprzedni (zmień kadr, miejsce albo strój)")
        if img:
            prev_prompt[p], prev_sesja[p], prev_kadr[p] = img, ses, r.get("kadr")
        if cap:
            for (m, c) in caps:
                if jacc(cap, c) > 0.6:
                    W.append(f"{tag}: opis bardzo podobny do wiersza {m}")
                    break
            caps.append((n, cap))
    for h, c in hooks.items():
        if c > 1:
            W.append(f"Ten sam początek hooka {c}x: '{h}...'")
    total = sum(pillars.values())
    if total:
        top, cnt = pillars.most_common(1)[0]
        if cnt / total > 0.5 and len(pillars) > 1:
            W.append(f"Filar '{top}' to {cnt / total:.0%} treści")
        promo = sum(c for k, c in pillars.items() if re.search(r"promo|sprzeda|oferta|fanvue|afili", k, re.I))
        if promo / total > limit_sp + 1e-9:
            W.append(f"Sprzedaż to {promo / total:.0%} treści ({promo} z {total}); limit {limit_sp:.0%}" + (" z karty" if card.get("sprzedaz_max") or card.get("sprzedaż_max") else ", trzymaj ok. 10-20%"))
    dup = [k for k, c in ids.items() if c > 1]
    if dup:
        E.append(f"Powtórzone id (pipeline nadpisze wiersze): {dup[:5]}")
    if past:
        W.append(f"{len(past)} wierszy z datą sprzed dziś ({dzis}) i statusem do publikacji, najstarszy {min(past)}. "
                 "Pipeline może je opublikować naraz: przesuń daty albo daj status draft. Powiedz o tym użytkownikowi na początku odpowiedzi")
    if dates:
        I.append(f"Okres {min(dates)} - {max(dates)}, wierszy: {len(rows)}")
        busy = [f"{d} {p}: {c}" for d, ps in per_day.items() for p, c in ps.items() if c > 3 and p not in ("x", "threads", "instagram")]
        busy += [f"{d} instagram: {c}" for d, ps in per_day.items() for p, c in ps.items() if p == "instagram" and c > 6]
        if busy:
            W.append("Bardzo gęsto jednego dnia: " + ", ".join(busy[:5]))
    I.append("Filary: " + ", ".join(f"{k} {v}" for k, v in pillars.most_common()))
    out(E, W, I, a, "OK")
    return 1 if E else 0


# ---------------------------------------------------------------- stats
STAT_KEYS = {
    "date": ["publish time", "post time", "posted on", "czas publikacji", "data publikacji", "posted", "date", "data", "time"],
    "platform": ["platform", "platforma", "network", "kanał"],
    "format": ["post type", "typ posta", "content type", "format", "typ", "type"],
    "pillar": ["filar", "pillar", "kategoria", "category"],
    "reach": ["reach", "zasięg", "accounts reached", "konta"],
    "views": ["views", "wyświetlenia", "video views", "plays", "odtworzenia", "impressions"],
    "likes": ["likes", "polubienia", "reactions", "reakcje"],
    "comments": ["comments", "komentarze"],
    "saves": ["saves", "zapisania", "zapisy", "favorites", "ulubione"],
    "shares": ["shares", "udostępnienia", "sends", "wysłania", "reposts"],
    "follows": ["follows", "obserwacje", "new followers", "nowi obserwujący"],
    "text": ["description", "opis", "caption", "hook", "title", "tytuł"],
}


def col(rows, key):
    cols = list(rows[0].keys())
    for k in STAT_KEYS[key]:
        for c in cols:
            if k == c or (len(k) > 4 and k in c):
                if key == "views" and "profile" in c:
                    continue
                return c
    return None


def num(x):
    s = re.sub(r"[^\d,.\-]", "", str(x or "")).replace(",", ".")
    if s.count(".") > 1:
        s = s.replace(".", "", s.count(".") - 1)
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_dt(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:19], f)
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})", s)
    return datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M") if m else None


def norm_fmt(f):
    f = (f or "").lower()
    for k, v in (("reel", "reel"), ("video", "reel"), ("wideo", "reel"), ("carousel", "karuzela"), ("karuzel", "karuzela"),
                 ("album", "karuzela"), ("image", "post"), ("photo", "post"), ("zdjęc", "post"), ("story", "story"),
                 ("tweet", "tweet"), ("text", "tekst"), ("tekst", "tekst")):
        if k in f:
            return v
    return f or "?"


def pora(h):
    return "rano 6-11" if 6 <= h < 11 else "południe 11-15" if h < 15 else "popołudnie 15-19" if h < 19 else "wieczór 19-24" if h >= 19 else "noc 0-6"


def cmd_stats(a):
    rows = read_csv(a["file"])
    if not rows:
        print("Pusty plik")
        return 2
    c = {k: col(rows, k) for k in STAT_KEYS}
    cal = defaultdict(list)
    if a.get("kalendarz"):
        for r in read_csv(a["kalendarz"]):
            if r.get("format", "").lower() != "story":
                cal[r.get("data", "")].append(r)

    def match(dt, p):
        if not dt:
            return {}
        cands = [r for r in cal.get(dt.date().isoformat(), []) if p in ("?", "") or not r.get("platforma") or plat(r.get("platforma")) == p]

        def gap(r):
            try:
                h, m = map(int, r.get("godzina", "0:0").split(":"))
                return abs(h * 60 + m - dt.hour * 60 - dt.minute)
            except ValueError:
                return 9999
        return min(cands, key=gap) if cands else {}
    posts = []
    for r in rows:
        dt = parse_dt(r.get(c["date"], "")) if c["date"] else None
        p = plat(r.get(c["platform"], "")) if c["platform"] else plat(a.get("platforma") or "?")
        cr = match(dt, p)
        if p == "?" and cr:
            p = plat(cr.get("platforma"))
        inter = sum(num(r.get(c[k])) for k in ("likes", "comments", "saves", "shares") if c[k])
        den = num(r.get(c["reach"])) if c["reach"] else 0
        den = den or (num(r.get(c["views"])) if c["views"] else 0)
        if den <= 0:
            continue
        posts.append({"dt": dt, "platform": p,
                      "format": norm_fmt((r.get(c["format"]) if c["format"] else "") or cr.get("format", "?")),
                      "pillar": (r.get(c["pillar"]) if c["pillar"] else "") or cr.get("filar", "?"),
                      "text": ((r.get(c["text"]) if c["text"] else "") or cr.get("hook", ""))[:70],
                      "er": inter / den * 100, "save": num(r.get(c["saves"])) / den * 1000 if c["saves"] else None,
                      "share": num(r.get(c["shares"])) / den * 1000 if c["shares"] else None,
                      "follow": num(r.get(c["follows"])) / den * 1000 if c["follows"] else None, "den": den})
    if not posts:
        print("Brak postów z zasięgiem/wyświetleniami. Kolumny w pliku:", list(rows[0].keys()))
        return 2
    print(f"Postów: {len(posts)} | mianownik: {'zasięg' if c['reach'] else 'wyświetlenia'} | ER = (polubienia+komentarze+zapisania+udostępnienia)/mianownik")
    print(f"Mediana ER: {statistics.median(p['er'] for p in posts):.2f}%")

    def table(key, label, minn=2):
        g = defaultdict(list)
        for p in posts:
            g[key(p)].append(p)
        res = []
        for k, lst in g.items():
            sv = [x["share"] for x in lst if x["share"] is not None]
            sa = [x["save"] for x in lst if x["save"] is not None]
            fo = [x["follow"] for x in lst if x["follow"] is not None]
            res.append((k, len(lst), statistics.median(x["er"] for x in lst),
                        statistics.mean(sa) if sa else None, statistics.mean(sv) if sv else None, statistics.mean(fo) if fo else None))
        res.sort(key=lambda t: -t[2])
        f1 = lambda v: "-" if v is None else f"{v:.1f}"
        print(f"\n{label}: n | mediana ER | zapisania/1000 | udostępnienia/1000 | obserwacje/1000")
        for k, n, er, sa, sv, fo in res:
            flag = "" if n >= minn else "  (za mało danych)"
            print(f"  {str(k)[:28]:28} {n:3} | {er:5.2f}% | {f1(sa)} | {f1(sv)} | {f1(fo)}{flag}")
        return [r for r in res if r[1] >= minn]

    if all(p["pillar"] in ("", "?") for p in posts):
        print("\nFilary: brak w eksporcie, dodaj --kalendarz kalendarz.csv, żeby je dokleić")
        fil = []
    else:
        fil = table(lambda p: p["pillar"] or "?", "Filary")
    fmt = table(lambda p: f"{p['platform']}/{p['format']}", "Platforma/format")
    if any(p["text"] for p in posts):
        table(lambda p: hook_type(p["text"]), "Typ hooka (z pierwszej linii)")
    dni = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
    table(lambda p: dni[p["dt"].weekday()] if p["dt"] else "?", "Dzień tygodnia", minn=3)
    por = table(lambda p: pora(p["dt"].hour) if p["dt"] else "?", "Pora", minn=3)

    def confounded(key):
        """Czy grupy (pora, dzień) to w praktyce różne formaty? Wtedy różnica ER mówi o formacie, nie o porze."""
        g = defaultdict(Counter)
        for p in posts:
            if p["dt"]:
                g[key(p)][p["format"]] += 1
        if len(g) < 2:
            return False, g
        shared = {f for c in g.values() for f in c if sum(1 for c2 in g.values() if c2[f]) >= 2}
        tot = sum(sum(c.values()) for c in g.values())
        return sum(c[f] for c in g.values() for f in shared) / tot < 0.5, g  # mniej niż połowa postów da się porównać w obrębie formatu
    por_conf, por_mix = confounded(lambda p: pora(p["dt"].hour))
    if por_conf:
        print("  UWAGA: pory pokrywają się z formatami (" + "; ".join(
            f"{k}: " + ", ".join(f"{f} {n}" for f, n in c.most_common()) for k, c in por_mix.items()) + "). Różnica w porze to najpewniej różnica formatu")
    best = sorted(posts, key=lambda p: -((p["share"] or 0) + (p["save"] or 0) + p["er"]))[:5]
    worst = sorted(posts, key=lambda p: p["er"])[:3]
    print("\nNajlepsze (udostępnienia + zapisania + ER):")
    for p in best:
        print(f"  {p['dt']:%Y-%m-%d %H:%M} {p['platform']}/{p['format']} [{p['pillar']}] ER {p['er']:.2f}% | {p['text']}" if p["dt"] else f"  {p['platform']} ER {p['er']:.2f}% | {p['text']}")
    print("Najsłabsze:")
    for p in worst:
        print(f"  {p['dt']:%Y-%m-%d %H:%M} {p['platform']}/{p['format']} [{p['pillar']}] ER {p['er']:.2f}% | {p['text']}" if p["dt"] else f"  {p['platform']} ER {p['er']:.2f}% | {p['text']}")
    print("\nWNIOSKI DO PLANU:")
    if len(fil) >= 2:
        print(f"  - Więcej '{fil[0][0]}' (mediana ER {fil[0][2]:.2f}%), mniej albo inaczej '{fil[-1][0]}' ({fil[-1][2]:.2f}%).")
    if len(fmt) >= 2:
        print(f"  - Najlepszy format: {fmt[0][0]}; najsłabszy: {fmt[-1][0]}.")
    if len(por) >= 2 and por_conf:
        print("  - Pory nie da się ocenić: każda pora to inny format. Test: ten sam format i filar o dwóch porach (np. 2 reelsy o 21:00 vs 19:30).")
    elif len(por) >= 2:
        print(f"  - Pora z najlepszą medianą: {por[0][0]}. Przetestuj tam 2-3 posty więcej przed stałą zmianą.")
    if len(posts) < 20:
        print("  - Mniej niż 20 postów: traktuj wnioski jako wskazówkę, nie regułę.")
    if a.get("json"):
        print(json.dumps({"posts": len(posts), "best_pillar": fil[0][0] if fil else None}, ensure_ascii=False))
    return 0


def out(E, W, I, a, ok):
    if a.get("json"):
        print(json.dumps({"ok": not E, "errors": E, "warnings": W, "info": I}, ensure_ascii=False, indent=1))
        return
    for t, xs in (("BŁĘDY", E), ("OSTRZEŻENIA", W), ("INFO", I)):
        if xs:
            print(f"\n{t} ({len(xs)}):\n" + "\n".join(f"  - {x}" for x in xs))
    print("\nWYNIK:", ok if not E else "DO POPRAWY")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("plan", "check", "stats"):
        print(__doc__)
        sys.exit(2)
    cmd, rest = sys.argv[1], sys.argv[2:]
    a, i = {}, 0
    while i < len(rest):
        if rest[i].startswith("--"):
            k = rest[i][2:]
            if k == "json":
                a["json"] = True
                i += 1
                continue
            a[k] = rest[i + 1] if i + 1 < len(rest) else ""
            i += 2
        else:
            a["file"] = rest[i]
            i += 1
    try:
        sys.exit({"plan": cmd_plan, "check": cmd_check, "stats": cmd_stats}[cmd](a))
    except FileNotFoundError as ex:
        print(f"BŁĄD: brak pliku {ex.filename}")
        sys.exit(2)


if __name__ == "__main__":
    main()
# <<< infl_tool.py
```