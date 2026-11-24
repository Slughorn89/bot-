---
name: Trading Bot
description: Ciemny panel operatora bota spot, który zawsze mówi, w jakim jest trybie i czy żyje.
colors:
  chart-night: "#131722"
  panel-slate: "#1e222d"
  hairline: "#2a2e39"
  hairline-strong: "#363a45"
  ink: "#d1d4dc"
  ink-strong: "#f0f3fa"
  ink-muted: "#9598a1"
  gain-teal: "#26a69a"
  loss-coral: "#ef5350"
  loss-coral-soft: "#ffb3b1"
  signal-blue: "#5b8cff"
  entry-blue: "#2962ff"
  caution-amber: "#ffb547"
  live-red: "#c62828"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, sans-serif"
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.4
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
  meta:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.08em"
rounded:
  item: "6px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  tag:
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 10px"
    height: "24px"
  tag-live:
    backgroundColor: "{colors.live-red}"
    textColor: "{colors.ink-strong}"
    rounded: "{rounded.pill}"
    padding: "0 10px"
    height: "24px"
  live-band:
    backgroundColor: "{colors.live-red}"
    textColor: "{colors.ink-strong}"
    padding: "6px 20px"
  list-item:
    backgroundColor: "{colors.chart-night}"
    textColor: "{colors.ink}"
    rounded: "{rounded.item}"
    padding: "8px 10px"
  sidebar:
    backgroundColor: "{colors.panel-slate}"
    textColor: "{colors.ink}"
    padding: "16px"
    width: "348px"
---

# Design System: Trading Bot

## Overview

**Creative North Star: "Uczciwy przyrząd"**

Panel ma działać jak przyrząd na desce rozdzielczej, a nie jak witryna. Odpowiada najpierw na cztery pytania:
czy bot żyje, czy handluje prawdziwymi pieniędzmi, czy ma pozycję i jak ona stoi. Dopiero potem pokazuje
kontekst. Świat wizualny celowo stoi blisko konwencji terminali giełdowych (ciemne tło wykresu, turkus
i koral dla wzrostu i spadku), bo operator zna je z innych narzędzi i nie musi się uczyć nowego języka.

Charakter nadają szczegóły, nie ozdoby: pasek trybu LIVE na całą szerokość, puls bota z wiekiem ostatniego
ticka, wyciszenie danych, które mogą być nieaktualne, i słowo „brak danych” zamiast cyfry, której nikt nie
zmierzył. Gęstość jest wysoka, ale każda wartość ma etykietę i znak.

**Key Characteristics:**
- Ciemny, płaski, tonalny układ z cienkimi liniami zamiast cieni.
- Jeden krój systemowy, cyfry tabelaryczne, mała skala typograficzna.
- Kolor tylko dla znaczenia: zysk, strata, ostrzeżenie, tryb LIVE, informacja.
- Każdy stan ma słowo i znak, kolor tylko je wzmacnia.

## Colors

Paleta jest powściągliwa: dwa ciemne neutralne podłoża, trzy poziomy tekstu i kolory wyłącznie semantyczne.

### Primary
- **Turkus zysku** (gain-teal): świece wzrostowe, dodatnie wyniki, sygnał BUY, linia TP, kropka „bot działa”.
- **Koral straty** (loss-coral): świece spadkowe, ujemne wyniki, sygnał SELL, linia SL, błędy połączenia.
- **Jasny koral** (loss-coral-soft): tylko tekst banera błędu na tle korala 12%.

### Secondary
- **Niebieski sygnałowy** (signal-blue): pierścień fokusu i zaznaczenie tekstu.
- **Niebieski wejścia** (entry-blue): wyłącznie linia ceny wejścia na wykresie.

### Tertiary
- **Bursztyn ostrożności** (caution-amber): ostrzeżenia, które nie są awarią (bot milczy, niedostępne źródło
  danych, panel bez bota).
- **Czerwień trybu LIVE** (live-red): pasek i etykieta trybu LIVE. Nic innego nie używa tego koloru.

### Neutral
- **Noc wykresu** (chart-night): tło strony, wykresu i elementów list.
- **Łupek panelu** (panel-slate): nagłówek i panel boczny, drugi poziom tonalny.
- **Linia** (hairline) i **linia mocna** (hairline-strong): podziały, obrysy etykiet i elementów.
- **Atrament** (ink): zwykły tekst. **Atrament mocny** (ink-strong): wartości i tytuły.
  **Atrament wyciszony** (ink-muted): etykiety, metadane, puste stany (5,5:1 na łupku).

### Named Rules
**Zasada jednej czerwieni.** Czerwień LIVE oznacza tylko prawdziwe pieniądze. Błędy używają korala, nigdy jej.

**Zasada spokojnego PAPER.** Tryb symulacji ma neutralną etykietę z obrysem. Kolor jest zarezerwowany dla
stanów, które wymagają uwagi.

## Typography

**Body Font:** systemowy sans (-apple-system, Segoe UI, Roboto)

**Character:** jeden krój dla wszystkiego, jak w narzędziu, nie w broszurze. Hierarchię niesie waga,
nie rozmiar.

### Hierarchy
- **Title** (650, 15px, 1.4): nazwa w nagłówku i dwie wiodące wartości pozycji (strona, wynik otwarty).
- **Body** (400 i 600, 13px, 1.4, cyfry tabelaryczne): wiersze etykieta i wartość, treść list.
- **Meta** (400, 12px): metadane elementów, notatki, puls bota, etykiety trybu.
- **Label** (700, 11px, 0.08em, wersaliki): tylko nagłówki sekcji panelu bocznego.

### Named Rules
**Zasada stojących cyfr.** Wszystkie liczby mają `tabular-nums`, żeby odświeżanie co 5 s nie trzęsło kolumną.

**Zasada braku danych.** Brak wartości to słowo „brak danych” albo „nie dotyczy” w kolorze wyciszonym,
nigdy zero ani myślnik.

## Layout

Na desktopie: pasek LIVE (gdy dotyczy), nagłówek, opcjonalny baner stanu, a pod nimi siatka z wykresem
(elastyczna kolumna) i panelem bocznym o szerokości 348px. Całość wypełnia okno (`100dvh`), przewija się
tylko panel boczny. Poniżej 900px panel boczny schodzi pod wykres (56vh, min. 300px), nagłówek się zawija,
a strona przewija się w całości.

Rytm: 4px wewnątrz wierszy, 6px między elementami listy, 16px wewnątrz panelu, 24px między sekcjami.

## Elevation & Depth

Brak cieni. Głębię daje tonalność: łupek panelu leży „wyżej” niż noc wykresu, a elementy list wracają do
nocy wykresu z obrysem 1px. Nieaktualne dane schodzą w tło przez przyciemnienie (opacity 0,55) całych sekcji.

### Named Rules
**Zasada płaskiego przyrządu.** Żadnych cieni, poświat ani szkła. Stan zmienia kolor, słowo i jasność.

## Shapes

Elementy list i komunikaty mają łagodne narożniki (6px), etykiety w nagłówku są pigułkami (999px).
Obrysy zawsze pełne, 1px. Nie ma pasków po jednej stronie elementu.

## Components

### Etykiety w nagłówku (tag)
- **Styl:** pigułka 24px wysokości, obrys hairline-strong, tekst 12px/650.
- **Warianty:** neutralna (para, strategia, PAPER), wyciszona z przerywanym obrysem (wartość jeszcze
  nieznana), turkusowa i koralowa z obrysem (LONG, SHORT), pełna czerwień (LIVE).

### Pasek LIVE
- Pełna szerokość nad nagłówkiem, czerwień LIVE, tekst atramentem mocnym 12px/700 (5:1), zdanie wprost: bot składa prawdziwe zlecenia.

### Puls bota (heartbeat)
- Kropka 8px i zdanie z wiekiem ostatniego ticka po prawej stronie nagłówka.
- Poziomy: działa (turkus), milczy albo panel bez bota (bursztyn), brak połączenia albo bot nie działa (koral).
- Po każdym udanym odświeżeniu kropka raz „bije” (600ms, ease-out, wyłączone przy prefers-reduced-motion).
- Zmiana poziomu trafia do ukrytego regionu `role="status"`, zwykłe odświeżenia nie są ogłaszane.

### Baner stanu
- Pełna szerokość pod nagłówkiem. Błąd: tło korala 12%, jasny koral. Ostrzeżenie: tło bursztynu 10%.
- Zawsze mówi, co się stało, od kiedy, czy dane są aktualne i co sprawdzić.

### Wiersze statystyk
- Lista definicji: etykieta wyciszona po lewej, wartość 600 atramentem mocnym po prawej, dopisek w `small`.
- Wartości ze znakiem mają kolor zysku albo straty i zawsze jawny znak + lub −.

### Elementy list (sygnały, transakcje, wieloryby)
- Noc wykresu, obrys hairline, 6px, padding 8px 10px.
- Tytuł 600, treść zwykła, metadane 12px wyciszone. HOLD ma tekst wyciszony.

## Do's and Don'ts

### Do:
- **Do** pokazuj tryb słowem w nagłówku i w tytule karty przeglądarki (`LIVE · BTC/USDT 76 169,31 · Trading Bot`).
- **Do** używaj tokenów z `:root` w `static/dashboard.html` zamiast wpisywać kolory na sztywno.
- **Do** zostawiaj ostatnie znane dane po utracie połączenia, ale przyciemnione i z banerem.
- **Do** sprawdzaj kontrast tekstu: minimum 4,5:1 na obu podłożach.

### Don't:
- **Don't** ustawiaj domyślnie PAPER ani FLAT, zanim przyjdą dane. Nieznany tryb to „tryb nieznany”.
- **Don't** wstawiaj emoji ani znaków Unicode jako ikon.
- **Don't** używaj paska po jednej stronie elementu do oznaczania kupna i sprzedaży; znak niesie słowo i kolor tekstu.
- **Don't** wstawiaj surowych danych z API przez `innerHTML` bez `esc()`.
