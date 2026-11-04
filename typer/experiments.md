# Dziennik eksperymentów

Zasada: jedna hipoteza, jedna zmiana, porównanie na **walidacji** (2018-07-01 do 2025-06-30, 14 379 meczów
w 6 ligach), decyzja. Odrzucone też zapisujemy, żeby ich nie testować drugi raz.
Holdout (od 2025-07-01) jest dotykany raz, na samym końcu.

Metryka strojenia: J = log loss 1X2 + 0,5 × (log loss O/U 2.5 + log loss BTTS).
„Rynek” w tej tabeli to kurs Bet365 **sprzed meczu** bez marży (kursów zamknięcia w danych nie ma).

| # | Data | Hipoteza | Zmiana | Wynik na walidacji | Decyzja |
|---|---|---|---|---|---|
| 0 | 2026-10-31 | Dane są czyste | Kontrola rozkładu dat i odstępów między meczami drużyny | Ekstraklasa: daty z dniem ≤ 12 mają zamieniony dzień z miesiącem (0 meczów w „styczniu”, 159 przypadków gry dwa razy w ciągu doby). Top 5 lig: 0 przypadków | Naprawa w adapterze + twarda reguła kontraktu (odstęp < 36 h = błąd) |
| 1 | 2026-10-31 | Proxy xG ze strzałów mierzy formę lepiej niż same gole | Cel aktualizacji ocen: 0,5 × gole + 0,5 × (0,27 × celne + 0,006 × niecelne); współczynniki z MNK na rozgrzewce | J 1,68354 vs 1,68875 bez xG; 1X2 0,9972 vs 0,9994; O/U 0,6834 vs 0,6872 | Przyjęte |
| 2 | 2026-10-31 | Domyślne tempa nauki nie są optymalne | Strojenie po współrzędnych (4 rundy, 70 przebiegów walk forward): lr_team 0,035→0,0143, lr_home 0,004→0,0027, lr_mu 0,002→0,0006, w_xg 0,5→0,2, season_regress 0,25→0,0, promoted_obr −0,15→−0,21, new_team_boost 1,5→1,0, rho −0,06→−0,09 | J 1,68354 → 1,67541; 1X2 0,9972 → 0,9934; O/U 0,6834 → 0,6783; BTTS 0,6894 → 0,6872 | Przyjęte (`config/model.yaml`). Uwaga: wolniejsza nauka = lepsza walidacja w spokojnym okresie, ale wolniejsza reakcja na zmianę reżimu, stąd obowiązkowy monitoring dryfu |
| 3 | 2026-10-31 | Dixon-Coles z wagami czasowymi (penaltyblog 1.13.1, xi = 0,0018, okno 2 lata, przeliczany co tydzień per liga) będzie lepszy od ocen online | Challenger na tych samych 14 291 meczach (beniaminkowie bez historii pominięci w obu modelach) | 1X2 1,0054 vs 0,9934; O/U 0,6903 vs 0,6783; BTTS 0,6988 vs 0,6872 (online lepsze we wszystkich rynkach) | Odrzucone |
| 4 | 2026-10-31 | Kalibracja out-of-fold poprawi prawdopodobieństwa | Kroczący Platt/vector scaling (1X2) + Platt (binarne) vs temperatura vs izotoniczna | 1X2: surowe 0,9926, vector 0,9924, temperatura 0,9922, izotoniczna 0,9955; O/U 0,6783 → 0,6777 (Platt) | Przyjęte: Platt/vector (zysk mały, ale stały); izotoniczna odrzucona (przeuczenie koszyków) |
| 5 | 2026-10-31 | Dixon-Coles z szybszym wygaszaniem (xi = 0,004) dogoni oceny online | Jak wpis 3, xi = 0,004 | 1X2 1,0072 vs 0,9933; O/U 0,6935 vs 0,6784 | Odrzucone. Klasa modelu odpada (dwa xi, oba wyraźnie gorsze) |
| 6 | 2026-10-31 | LightGBM na cechach (oceny, forma, xG proxy, odpoczynek, Elo, baseline) wyciągnie nieliniowości | Warstwa GBM (kroczący trening per sezon, wczesne zatrzymanie na ostatnim roku) + kalibracja | 1X2 0,9924 (= online+cal), O/U 0,6782 (gorzej o 0,0005), BTTS 0,6868 (gorzej o 0,0005) | Odrzucone: złożoność bez zysku |
| 7 | 2026-10-31 | Mieszanka z rynkiem w chwili typu (kurs Bet365 sprzed meczu bez marży) poprawi log loss | Pooling log-liniowy, waga modelu dopasowywana krocząco | 1X2 0,9926 → 0,9805 (na meczach z kursami 0,9847 → 0,9707 = rynek); O/U 0,6783 → 0,6729. **Waga modelu w 1X2 = 0,0 we wszystkich 7 sezonach**, w O/U 0,00 do 0,03 | Przyjęte jako champion (z kalibracją po mieszance: 1X2 0,9802, na meczach z kursami 0,9704 vs rynek 0,9707). Wniosek: model z goli i strzałów nie ma informacji krańcowej ponad kurs Bet365 sprzed meczu w top 5 lig |
| 8 | 2026-10-31 | Ekstraklasa (segment „słaby”, luka +0,0158 do benchmarku) potrzebuje innych temp nauki | Poprawka celowana: siatka lr_team × season_regress × rho tylko dla POL (`league_params`) | Najlepiej 1,0455 vs 1,0463 (1847 meczów), O/U i BTTS bez zmian | Odrzucone (w granicach szumu). Przyczyna to brak informacji: brak strzałów, benchmark POL to być może kurs zamknięcia |
| 9 | 2026-10-31 | Odchylenia z raportu (BTTS „tak” zaniżone w D1 o 3,4 pp i w I1 o 2,8 pp; gospodarz zawyżony w I1 o 2,3 pp) są specyficzne dla ligi | Kalibracja per liga (min. 1500 meczów historii), globalna dla reszty | D1 BTTS: odchylenie 3,4 → 1,4 pp; łącznie J 1,6597 → 1,6596 (1X2 −0,0004, O/U +0,0007, BTTS −0,0001) | Odrzucone (brak łącznego zysku). Do backlogu: rosnąca częstość BTTS w Bundeslidze, rho per liga |
| 10 | 2026-10-31 | Analiza wrażliwości (nie werdykt): przewaga przy braniu najlepszego kursu z ~17 bukmacherów | Champion, `odds_taken` = kurs maksymalny sprzed meczu | Próg 2%: 6646 zakładów, ROI −1,4% (CI90 −5,6% do +2,5%); próg 5%: 1665 zakładów, ROI +4,7% (CI90 −5,7% do +15,3%) | Tylko informacyjnie. ROI w granicach szumu, kurs maksymalny jest optymistyczny (nieaktualne kursy, limity kont), a bez zamknięcia nie ma CLV |

## Holdout (2025-07-01 do 2026-09-03, 1851 meczów, uruchomiony raz: 2026-10-31 09:11 UTC)

Champion `op-v1` = oceny online (`config/model.yaml`) + mieszanka z rynkiem + kalibracja.

| Rynek | Champion | Same oceny online | Rynek (Bet365 sprzed meczu, bez marży) | Baseline |
|---|---|---|---|---|
| 1X2 | 0,9758 | 0,9895 | 0,9763 | 1,0707 |
| O/U 2.5 | 0,6753 | 0,6842 | 0,6753 | n/d |
| BTTS | 0,6860 | 0,6871 | brak kursów | n/d |

Bramki: próba, spójność, kalibracja (ECE 0,0040), lepszy od baseline (−0,0359), brak wycieku (luka −0,0002): OK.
Zakłady z przewagą ≥ 5%: 0. CLV: nie do policzenia (brak kursów zamknięcia).
**Werdykt: GOTOWY tylko do typowania (brak dowodu przewagi nad rynkiem).**

Obserwacje do monitoringu (bez strojenia, holdout spalony):
* Premier League 1X2: luka do rynku +0,0024 (CI90 +0,0002 do +0,0049), alarm dryfu od 2026-02-21.
* Serie A O/U 2.5: luka +0,0010 (CI90 +0,0003 do +0,0017).
Kolejny uczciwy test wymaga nowego okresu (paper trading od wdrożenia).

## Backlog cech (ze ślepych plamek i raportów)
1. Składy i kontuzje (~60 min przed meczem): największa brakująca informacja; tabela `lineups` gotowa, brak źródła.
2. Kursy zamknięcia Pinnacle (football-data.co.uk): odblokowują CLV i bramkę `clv_dodatni`.
3. Prawdziwe xG (Understat/FBref zamiast proxy ze strzałów), strzały dla Ekstraklasy.
4. Rho / częstość BTTS per liga (wpis 9), dryf przewagi gospodarza w Premier League (holdout).
