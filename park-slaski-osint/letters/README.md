# Pisma do administratorów monitoringu

| Plik | Po co |
|---|---|
| `01_wniosek_zabezpieczenie_nagran.md` | żeby nagrania nie zostały skasowane (art. 18 ust. 1 lit. c RODO) |
| `02_wniosek_art15_rodo_kopia_nagrania.md` | żeby dostać kopię nagrania z Twoim wizerunkiem (art. 15 ust. 3 RODO) |

## Najważniejsze: czas

Rejestratory monitoringu zwykle nadpisują nagrania po kilku do kilkunastu dniach (okres zależy od administratora).
Od 17.10.2026 minęło już sporo dni, więc **wyślij oba pisma od razu, tego samego dnia**:

1. e-mailem do Inspektora Ochrony Danych (adres jest w polityce prywatności / klauzuli monitoringu na stronie podmiotu) i na ogólny adres firmy,
2. dodatkowo listem poleconym za potwierdzeniem odbioru albo przez ePUAP, jeśli to podmiot publiczny,
3. zachowaj dowody wysłania. Możesz też zadzwonić i poprosić o wstrzymanie kasowania, a potem to potwierdzić pismem.

Jeżeli zdarzenie może być przestępstwem lub wykroczeniem, zgłoś je też na Policji i powiedz, gdzie są kamery.
Policja może sama zażądać wydania nagrań (art. 217 Kodeksu postępowania karnego) i zwykle robi to szybciej niż odpowiedź na wniosek z RODO.

## Co wiadomo o monitoringu w parku

Według artykułu z ok. 2014 r. Park Śląski uruchomił centrum monitoringu w budynku administracji, z ok. 40 kamerami,
m.in. na podporach kolejki Elka, obejmującymi centrum parku i al. gen. Jerzego Ziętka. Nagrania miały służyć jako
dowód w sprawach karnych ([Chorzowianin, archiwum](http://www.archiwum.chorzowianin.pl/park-bedzie-sledzilo-40-kamer,n-4337.html)).
Nie wiadomo, ile z tego działa dziś, ale warto w piśmie poprosić wprost o nagrania „z centrum monitoringu parku,
w tym z kamer na podporach kolejki linowej Elka”.

## Do kogo pisać

Każdy podmiot z kamerami to osobny administrator, więc piszesz osobno do każdego, którego kamery mogły Cię nagrać.
Adresy i e-maile IOD sprawdź na stronach (zakładki Kontakt, RODO, Polityka prywatności, Monitoring):

* Park Śląski S.A., zarządca parku: https://parkslaski.pl/
* operator Stadionu Śląskiego: https://www.stadionslaski.pl/
* Legendia Śląskie Wesołe Miasteczko: https://legendia.pl/
* Śląski Ogród Zoologiczny: https://zoo.silesia.pl/
* Planetarium Śląskie: https://www.planetarium.edu.pl/
* Muzeum „Górnośląski Park Etnograficzny w Chorzowie”: https://muzeumgpe-chorzow.pl/
* Urząd Miasta Chorzów / Straż Miejska (monitoring miejski na ulicach wokół parku)
* Tramwaje Śląskie S.A. (kamery w tramwajach dojeżdżających do parku) i operatorzy autobusów ZTM
* pobliskie parkingi, stacje paliw, sklepy (często mają kamery na wejścia i ulicę)

## Jak wypełnić

```bash
cp letters/dane.example.yaml letters/dane.yaml   # uzupełnij dane
python -m parkosint letters                      # wynik w output/letters/
```

Pola, których nie uzupełnisz, zostaną w piśmie jako `[NAZWA_POLA]`, a skrypt je wypisze.
Gotowy plik `.md` otworzysz w każdym edytorze; do Worda: `pandoc output/letters/01_wniosek_zabezpieczenie_nagran.md -o 01.docx`
albo po prostu skopiuj tekst.

## Kilka uwag

* Art. 15 i 18 RODO działają, gdy na nagraniu są **Twoje** dane (Twój wizerunek). Jeśli szukasz nagrania zdarzenia, na którym Ciebie nie ma, właściwa droga to Policja albo sąd.
* Administrator może rozmyć wizerunki innych osób (art. 15 ust. 4 RODO). Pismo zawiera na to zgodę, żeby nie było pretekstu do odmowy.
* Na odpowiedź administrator ma miesiąc (art. 12 ust. 3 RODO). Gdy odmówi albo nie odpowie, możesz złożyć skargę do Prezesa UODO.
* To są wzory, nie porada prawna. Przy poważnej sprawie (np. szkoda na zdrowiu, spór z ubezpieczycielem) warto pokazać je prawnikowi.
