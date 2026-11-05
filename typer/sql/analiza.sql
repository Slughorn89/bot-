-- Szablony zapytan (PostgreSQL) do analizy wynikow, sekcja 14.4 skilla, dopasowane do schematu
-- typer/store/db.py. Oficjalny log loss rynkow wieloselekcyjnych liczy wylacznie tools/evaluate.py:
-- ll_binarny tutaj to szybki podglad.

-- 1) CLV i szybki log loss per liga, ostatnie 30 dni, biezacy champion, segmenty z n >= 100
WITH champ AS (SELECT version FROM model_registry WHERE role = 'champion' ORDER BY created_utc DESC LIMIT 1),
close_fair AS (   -- kurs zamkniecia bez marzy (de-vig proporcjonalny w obrebie meczu i rynku)
  SELECT event_id, market, selection, price AS odds_close,
         price * sum(1.0 / price) OVER (PARTITION BY event_id, market) AS odds_close_fair
  FROM (SELECT DISTINCT ON (event_id, market, selection) event_id, market, selection, price
        FROM odds_snapshots WHERE kind = 'close'
        ORDER BY event_id, market, selection, (bookmaker <> 'pinnacle'), snapshot_utc DESC) c
)
SELECT e.league, count(*) AS n,
       avg(b.odds / cf.odds_close_fair - 1) AS clv,
       avg(-ln(CASE WHEN (p.market = '1X2' AND p.selection = CASE WHEN r.fthg > r.ftag THEN '1'
                                                             WHEN r.fthg = r.ftag THEN 'X' ELSE '2' END)
                    THEN p.p_model ELSE 1 - p.p_model END)) AS ll_binarny
FROM bets b
JOIN predictions p ON p.id = b.prediction_id
JOIN events e ON e.event_id = b.event_id
JOIN results r ON r.event_id = b.event_id
JOIN close_fair cf ON cf.event_id = b.event_id AND cf.market = b.market AND cf.selection = b.selection
WHERE e.kickoff_utc >= now() - interval '30 days'
  AND p.model_version = (SELECT version FROM champ)
  AND p.market = '1X2'
GROUP BY e.league
HAVING count(*) >= 100
ORDER BY clv;

-- 2) Eksport do evaluate.py (Zalacznik B). Wynik (outcome) liczy learn/settle.py:outcome(),
--    bo results trzyma gole, nie selekcje; najprosciej: python cli.py analyze (robi to samo).
SELECT p.event_id, (e.kickoff_utc AT TIME ZONE 'UTC')::date AS date, e.sport, e.league, p.market,
       p.selection, p.p_model, p.p_baseline, r.fthg, r.ftag, p.odds_taken, c.price AS odds_close,
       COALESCE(b.stake_frac, 0) AS stake, p.model_version
FROM predictions p
JOIN events e ON e.event_id = p.event_id
JOIN results r ON r.event_id = p.event_id
LEFT JOIN LATERAL (SELECT price FROM odds_snapshots s WHERE s.event_id = p.event_id AND s.market = p.market
                   AND s.selection = p.selection AND s.kind = 'close'
                   ORDER BY (s.bookmaker <> 'pinnacle'), s.snapshot_utc DESC LIMIT 1) c ON true
LEFT JOIN bets b ON b.prediction_id = p.id
WHERE e.kickoff_utc >= :since AND p.role = 'champion';

-- 3) Kompletnosc rozliczen (14.2 krok 4): mecze rozegrane bez predykcji championa
SELECT e.league, count(*) AS bez_predykcji
FROM events e
WHERE e.status = 'finished' AND e.kickoff_utc >= :since
  AND NOT EXISTS (SELECT 1 FROM predictions p WHERE p.event_id = e.event_id AND p.role = 'champion')
GROUP BY e.league ORDER BY 2 DESC;
