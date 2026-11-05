# tresci-ai-influencera: iteracja 2

Wejście: raport `review-iteration-1.html` (2 ewale, wersja nowa vs stara, po 1 przebiegu).

## Co pokazał raport iteracji 1

| Ewal | Nowa wersja | Stara wersja |
|---|---|---|
| 1. kalendarz na 2 tygodnie | 8/8 | 7/8 (0 z 12 reelsów miało prompt wideo i scenariusz) |
| 2. analiza wyników | 7/7 | 7/7 |
| Tokeny (średnio) | 220,5 tys. | 212,1 tys. |

Wniosek: nowa wersja jest lepsza, ale asercje prawie jej nie odróżniają od starej (14/15 vs 15/15). Prawdziwe różnice i problemy widać dopiero w samych plikach.

## Znaleziska (z pewnością)

1. **`check` przepuszczał rozjazdy, które w ewalu 2 okazały się przyczyną najsłabszych postów** (pewność 0.95). Hook "Trencz na 4 sposoby" przy sesji ze skórzaną kurtką, "Poniedziałek w Kazimierzu" w sobotę i w lofcie, lista w pojedynczym zdjęciu, post sprzedażowy z `reklama: brak`, puste opisy. Sprawdziłem: wstawiłem 7 takich błędów do czystego kalendarza z ewalu 1 i stary `check` dał `WYNIK: OK`.
2. **`stats` wyciągał fałszywy wniosek o porze** (0.95). Na danych z ewalu 2 pisał "Pora z najlepszą medianą: wieczór 19-24", a wszystkie zdjęcia szły o 18:29-18:46, a reelsy i karuzele o 19:04-19:53. To różnica formatu, nie pory. Obie wersje agenta to wyłapały same, ale narzędzie podsuwało błędną decyzję.
3. **Daty z przeszłości** (0.85). Ewal szedł 4.11, plan zaczynał się 2.11. Stara wersja ostrzegła wyraźnie na samej górze, że pipeline opublikuje zaległe wiersze `pending` naraz. Nowa wspomniała o tym w środku odpowiedzi. Narzędzie tego nie sprawdzało.
4. **Deklaracje użycia w reklamie** (0.9). "Ten sweter z Wełniaka noszę od tygodnia" w ustach postaci AI to nieprawdziwe twierdzenie w reklamie. Wyłapały to obie wersje, ale skill nie miał na to zasady ani kontroli. Do tego dwa przebiegi dały sprzeczne rady o zdjęciach produktu (generować z referencją vs brać od marki).
5. **Kolumny pod pipeline** (0.8). Nowa wersja sama dopisała `id`, `proporcje` i `seed`, a stara w ewalu 2 obcięła kalendarz do 13 kolumn, bo skill pisał o "13 podstawowych", co psuje mapowanie w n8n.
6. **Ręczna robota przy dniach delikatnych i sesjach** (0.75). Obie wersje ręcznie przenosiły posty z 2.11 i 11.11. W ewalu 2 agent musiał zrobić kopię karty z inną kolejnością miejsc, żeby pierwsza sesja wypadła w lumpeksie, bo `plan` łączył miejsca i stroje zawsze w tych samych parach.
7. **Fałszywe alarmy "prompt prawie jak poprzedni"** (0.8). Kolejne kadry tej samej sesji (to samo miejsce, strój, światło) z definicji mają podobne prompty. Stary raport kontrolny w ewalu 2 miał 31 takich ostrzeżeń.
8. **Stara wersja zmieniła kartę persony bez prośby** (karta-lena-v2.md), nowa tylko zaproponowała dopiski. Dobre zachowanie, ale asercje tego nie sprawdzały.

Ogólna pewność, że poprawki 1-7 podnoszą jakość bez psucia czegoś innego: 0.85. Najsłabszy punkt to heurystyki tekstowe (dni tygodnia, listy w hookach). Sprawdziłem je na prawdziwych kalendarzach z obu ewali i nie dają fałszywych alarmów, ale na innych personach i niszach mogą czasem zgłosić coś na wyrost. Dlatego to ostrzeżenia, nie błędy.

## Co zmieniłem

**Narzędzie `infl_tool.py`**
- `check`, nowe BŁĘDY: pusty caption, deklaracja osobistego użycia w reklamie, powtórzone `id`.
- `check`, nowe OSTRZEŻENIA: daty sprzed dziś ze statusem do publikacji (jedno zbiorcze), strój albo miejsce w prompcie inne niż w sesji, dzień tygodnia w hooku niezgodny z datą (bez "po piątku", "co niedzielę"), lista w pojedynczym zdjęciu, filar sprzedażowy bez wpisu w `reklama`, złe proporcje, limit sprzedaży z karty (`sprzedaz_max: 1/6`).
- `check`: kolejne kadry tej samej sesji nie dostają już ostrzeżenia o podobnym prompcie.
- `stats`: wykrywa, gdy pora pokrywa się z formatem, i wtedy zamiast wniosku o porze proponuje test. Nowa tabela typów hooków. Dni tygodnia i pory z mniej niż 3 postami oznaczone jako za mało danych. Kalendarz bez kolumny platforma też się dokleja.
- `plan`: przenosi publikacje z dni delikatnych na najbliższy zwykły dzień, łączy miejsca i stroje w zmieniające się pary, przyjmuje `--miejsca` i `--stroje`, nadaje `id`, `proporcje`, `seed`, ostrzega o starcie w przeszłości (`--dzis` do testów).

**Instrukcje w SKILL.md**
- Pełna lista kolumn z `id`, `proporcje`, `seed` i zakaz usuwania kolumn.
- Zasada "tekst wynika z sesji, nie odwrotnie" (strój, miejsce, dzień tygodnia, lista = karuzela).
- "Persona AI a produkt": bez deklaracji noszenia i testowania, jedna spójna zasada co do zdjęć produktu.
- Krok 7: ostrzeżenie o datach z przeszłości idzie na początek odpowiedzi.
- Krok 8: pułapka pora vs format, typy hooków, porównanie kalendarza z realizacją, reklama jako pilna poprawka.
- Szablon karty: opcjonalne `sprzedaz_max`, zasada reklamy w Granicach.

## Testy

`python3 -I skills/tresci-ai-influencera-workspace/test_infl_tool.py` wypakowuje narzędzie z SKILL.md i sprawdza:
- czysty kalendarz: 0 błędów i 0 ostrzeżeń,
- 8 wstrzykniętych błędów: wszystkie wykryte,
- "Po piątku trzynastego": brak fałszywego alarmu,
- `stats` na danych, gdzie pora = format: brak wniosku o porze, jest propozycja testu,
- `plan` dla 2-15.11: na 2.11 i 11.11 zostają tylko stories, `id` unikalne, pary miejsce+strój się nie powtarzają.

Wynik: wszystko przechodzi. Kalendarze z iteracji 1 przez nowy `check`: nowa wersja 0 błędów i tylko zasadne ostrzeżenie o datach z przeszłości; stara 0 błędów, plus zasadne uwagi o pustej kolumnie `reklama`.

## Co dalej

1. Wgraj `skills/tresci-ai-influencera/SKILL.md` w miejsce obecnej wersji skilla.
2. Puść iterację 2 ewali z `evals/evals.json` (4 ewale, ostrzejsze asercje plus nowe: komentarze i karta od zera). Pliki wejściowe w `evals/files` są odtworzone z raportu; jeśli masz oryginały z iteracji 1, użyj ich.
3. Najlepiej po 2-3 przebiegi na wersję, bo przy jednym przebiegu nie widać rozrzutu.
