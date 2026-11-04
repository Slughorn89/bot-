#!/usr/bin/env python3
"""evaluate.py: ocena typera, bramki jakosci, post mortem i detekcja dryfu.

Wejscie: CSV, jeden wiersz = jedna selekcja (1X2 = 3 wiersze na mecz, O/U 2.5 = 2 wiersze
albo 1 wiersz "over"). Wymagane kolumny:
  event_id, date, market, selection, p_model, outcome (0/1)
Opcjonalne:
  sport, league, p_baseline (np. czyste Elo), odds_taken (kurs w chwili typu),
  odds_close (kurs zamkniecia), stake (stawka; >0 = zagrany zaklad), model_version

Uzycie:
  python tools/evaluate.py preds.csv --by sport,league,market --json report.json
  python tools/evaluate.py preds.csv --value-threshold 0.03   # sam wybierze value bety
Kod wyjscia: 0 = gotowy do gry (twarde bramki + CLV), 1 = tylko do typowania, 2 = NIEGOTOWY.
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd

EPS = 1e-12
GATES = dict(
    min_events=300,          # minimalna proba out-of-sample
    max_ece=0.03,            # blad kalibracji
    max_gap_vs_market=0.015, # o ile log loss modelu moze byc gorszy od rynku zamkniecia
    leak_margin=0.03,        # model lepszy od zamkniecia o tyle = podejrzenie wycieku
    min_bets=300,            # minimalna liczba zakladow do oceny CLV i ROI
)


def load(path):
    df = pd.read_csv(path)
    need = {"event_id", "date", "market", "selection", "p_model", "outcome"}
    miss = need - set(df.columns)
    if miss:
        sys.exit(f"Brak kolumn: {sorted(miss)}")
    df["date"] = pd.to_datetime(df["date"])
    for c in ("sport", "league"):
        if c not in df.columns:
            df[c] = "all"
    for c in ("p_model", "p_baseline"):
        if c in df.columns:
            df[c] = df[c].astype(float).clip(EPS, 1 - EPS)
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def _ll(p, out):
    """Log loss zdarzenia: grupa wielowierszowa = -log p(wynik), jeden wiersz = binarny."""
    if len(p) == 1:
        return -np.log(p[0] if out[0] == 1 else 1 - p[0])
    p = p / p.sum()
    return -np.log(max(p[out == 1][0], EPS))


def event_table(df):
    has_base = "p_baseline" in df.columns
    has_close = "odds_close" in df.columns
    rows, bad_sum, skipped = [], 0, 0
    for (eid, mkt), g in df.groupby(["event_id", "market"], sort=False):
        out = g["outcome"].to_numpy()
        p = g["p_model"].to_numpy()
        if len(g) > 1 and out.sum() != 1:
            skipped += 1  # zwrot / void / blad danych
            continue
        if len(g) > 1 and abs(p.sum() - 1) > 0.02:
            bad_sum += 1
        pn = p / p.sum() if len(g) > 1 else p
        r = dict(event_id=eid, market=mkt, date=g["date"].iloc[0],
                 sport=g["sport"].iloc[0], league=g["league"].iloc[0],
                 ll_model=_ll(p, out),
                 brier=float(((pn - out) ** 2).sum()) if len(g) > 1
                 else float((p[0] - out[0]) ** 2))
        r["ll_base"] = _ll(g["p_baseline"].to_numpy(), out) if has_base else np.nan
        r["ll_market"] = np.nan
        if has_close and len(g) > 1 and g["odds_close"].notna().all():
            inv = 1.0 / g["odds_close"].to_numpy(dtype=float)
            r["ll_market"] = _ll(inv / inv.sum(), out)  # de-vig proporcjonalny
        rows.append(r)
    return pd.DataFrame(rows), bad_sum, skipped


def ece(p, y, bins=10):
    p, y = np.asarray(p), np.asarray(y)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot, table = 0.0, []
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        mp, my = p[m].mean(), y[m].mean()
        tot += abs(mp - my) * m.sum() / len(p)
        table.append(dict(bin=f"{b / bins:.1f}-{(b + 1) / bins:.1f}", n=int(m.sum()),
                          p_sr=round(mp, 3), czestosc=round(my, 3), roznica=round(my - mp, 3)))
    return tot, table


def boot(fn, arrays, n=2000, seed=7):
    """Bootstrap: zwraca (5. percentyl, 95. percentyl) statystyki fn."""
    k = len(arrays[0])
    if k == 0:
        return (np.nan, np.nan)
    idx = np.random.default_rng(seed).integers(0, k, (n, k))
    vals = fn(*[a[idx] for a in arrays])
    return float(np.percentile(vals, 5)), float(np.percentile(vals, 95))


def select_bets(df, value_threshold):
    if "stake" in df.columns:
        bets = df[df["stake"].fillna(0) > 0].copy()
    elif value_threshold is not None and "odds_taken" in df.columns:
        edge = df["p_model"] * df["odds_taken"] - 1
        bets = df[edge >= value_threshold].copy()
        bets["stake"] = 1.0
    else:
        return pd.DataFrame()
    bets = bets[bets["odds_taken"].notna()]
    bets["profit"] = np.where(bets["outcome"] == 1, bets["stake"] * (bets["odds_taken"] - 1),
                              -bets["stake"])
    if "odds_close_fair" in bets.columns:
        # CLV wzgledem kursu zamkniecia BEZ marzy = estymata oczekiwanego zysku z zakladu.
        # Wzgledem kursu z marza CLV jest zawyzony i "dodatni" nawet dla slabego modelu.
        bets["clv"] = bets["odds_taken"] / bets["odds_close_fair"] - 1
    return bets


def add_fair_close(df):
    """Kurs zamkniecia bez marzy (de-vig proporcjonalny w obrebie event+market)."""
    if "odds_close" not in df.columns:
        return df
    inv = 1.0 / df["odds_close"]
    grp = df.groupby(["event_id", "market"])
    tot, n, full = grp["odds_close"].transform(lambda x: (1 / x).sum()), grp["odds_close"].transform("size"), \
        grp["odds_close"].transform(lambda x: x.notna().all())
    df["odds_close_fair"] = np.where((n > 1) & full, tot / inv, np.nan)
    return df


def betting_stats(bets):
    if bets.empty:
        return {}
    s, pr = bets["stake"].to_numpy(float), bets["profit"].to_numpy(float)
    out = dict(n_bets=len(bets), stawki=round(s.sum(), 2), zysk=round(pr.sum(), 2),
               roi=pr.sum() / s.sum(),
               roi_ci90=boot(lambda a, b: a.sum(1) / b.sum(1), [pr, s]))
    if "clv" in bets.columns and bets["clv"].notna().any():
        c = bets["clv"].dropna().to_numpy(float)
        out.update(clv_sr=float(c.mean()), clv_ci90=boot(lambda a: a.mean(1), [c]),
                   bije_zamkniecie=float((c > 0).mean()))
    return out


def cusum_drift(ev, warmup=200, k=0.1, h=22.0, clip=4.0):
    """Jednostronny CUSUM (Page) na standaryzowanej nadwyzce log loss.
    Strumien = ll_model - ll_market (gdy jest rynek), inaczej ll_model.
    Referencja = pierwsze `warmup` zdarzen segmentu. k=0.1, h=22 daje ok. 5000 zdarzen
    miedzy falszywymi alarmami (przy wielu segmentach naraz nizszy prog = lawina
    falszywych alarmow) i wykrywa pogorszenie o ~0.3 odchylenia w ~110 zdarzen.
    Przyciecie z do +-4 sprawia, ze pojedyncza niespodzianka nie wywola alarmu.
    WAZNE: do monitoringu uruchamiaj z --since = data wdrozenia biezacej wersji modelu.
    Stara referencja (np. z okresu, gdy model sie rozgrzewal) oslepia detektor."""
    x = (ev["ll_model"] - ev["ll_market"]).to_numpy() if ev["ll_market"].notna().all() \
        else ev["ll_model"].to_numpy()
    if len(x) < warmup + 50:
        return []
    mu, sd = x[:warmup].mean(), x[:warmup].std() + 1e-9
    s, alarms = 0.0, []
    for i in range(warmup, len(x)):
        z = np.clip((x[i] - mu) / sd, -clip, clip)
        s = max(0.0, s + z - k)
        if s > h:
            alarms.append(str(ev["date"].iloc[i].date()))
            s = 0.0
    return alarms


def segment_report(ev, df, bets, by):
    out = []
    for key, g in ev.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        r = dict(zip(by, key), n=len(g), ll_model=g["ll_model"].mean())
        if g["ll_market"].notna().all():
            d = (g["ll_model"] - g["ll_market"]).to_numpy()
            r["luka_vs_rynek"] = d.mean()
            r["luka_ci90"] = boot(lambda a: a.mean(1), [d])
        rows = df.merge(g[["event_id", "market"]], on=["event_id", "market"])
        r["ece"] = ece(rows["p_model"], rows["outcome"])[0]
        if not bets.empty:
            b = bets.merge(g[["event_id", "market"]], on=["event_id", "market"])
            if len(b):
                r["n_bets"], r["roi"] = len(b), b["profit"].sum() / b["stake"].sum()
                if "clv" in b.columns:
                    r["clv"] = b["clv"].mean()
        r["slaby"] = bool(len(g) >= 50 and "luka_ci90" in r and r["luka_ci90"][0] > 0)
        out.append(r)
    return sorted(out, key=lambda r: -r.get("luka_vs_rynek", r["ll_model"]))


def selection_bias(df, by, min_n=100):
    """Systematyczne odchylenia: srednie p_model minus czestosc per segment i selekcja.
    Np. model zawyza '1' (gospodarz) w L3 o 6 pp = rozjechana przewaga gospodarza."""
    out = []
    for key, g in df.groupby(by + ["market", "selection"] if "market" not in by else by + ["selection"]):
        if len(g) < min_n:
            continue
        b = g["p_model"].mean() - g["outcome"].mean()
        se = np.sqrt((g["p_model"] * (1 - g["p_model"])).mean() / len(g))
        if abs(b) > 2.5 * se:
            key = key if isinstance(key, tuple) else (key,)
            cols = by + ["market", "selection"] if "market" not in by else by + ["selection"]
            out.append(dict(zip(cols, key), n=len(g), p_sr=round(g["p_model"].mean(), 3),
                            czestosc=round(g["outcome"].mean(), 3), odchylenie_pp=round(100 * b, 1)))
    return sorted(out, key=lambda r: -abs(r["odchylenie_pp"]))


def gates(ev, df, bets, bstats, G, bad_sum=0):
    res = []

    def add(name, ok, info, hard=True):
        res.append(dict(bramka=name, wynik="OK" if ok else ("BLAD" if hard else "UWAGA"),
                        info=info, twarda=hard))

    n = len(ev)
    add("proba", n >= G["min_events"], f"{n} zdarzen (min {G['min_events']})")
    add("spojnosc_prawdopodobienstw", bad_sum == 0,
        f"{bad_sum} rynkow, w ktorych p_model nie sumuje sie do 1 (+-0.02) = blad modelu")
    e = ece(df["p_model"], df["outcome"])[0]
    add("kalibracja", e <= G["max_ece"], f"ECE {e:.4f} (max {G['max_ece']})")
    if ev["ll_base"].notna().all():
        d = ev["ll_model"].mean() - ev["ll_base"].mean()
        add("lepszy_od_baseline", d < 0, f"log loss model - baseline = {d:+.4f}")
    if ev["ll_market"].notna().all():
        gap = ev["ll_model"].mean() - ev["ll_market"].mean()
        add("konkurencyjny_vs_rynek", gap <= G["max_gap_vs_market"],
            f"luka {gap:+.4f} (max {G['max_gap_vs_market']}); model moze byc ogolnie slabszy od "
            f"zamkniecia i zarabiac na wczesnych kursach, dlatego to ostrzezenie, a decyduje CLV",
            hard=False)
        add("brak_wycieku", gap > -G["leak_margin"],
            f"luka {gap:+.4f}; ponizej -{G['leak_margin']} = model 'za dobry', szukaj wycieku")
    if not bstats or "clv_sr" not in bstats:
        add("ocena_wartosci", False, "brak zakladow z kursem zamkniecia: model mozna oceniac jako "
            "predyktor, ale nie wiadomo, czy daje przewage nad bukmacherem", hard=False)
    if bstats and bstats["n_bets"] >= G["min_bets"]:
        if "clv_sr" in bstats:
            add("clv_dodatni", bstats["clv_ci90"][0] > 0,
                f"sredni CLV (vs zamkniecie bez marzy) {bstats['clv_sr']:+.4f}, "
                f"CI90 {fmt_ci(bstats['clv_ci90'])}; dolna granica musi byc > 0")
        lo, hi = bstats["roi_ci90"]
        add("roi_nie_ujemny_istotnie", hi > 0, f"ROI {bstats['roi']:+.3%}, CI90 {fmt_ci(bstats['roi_ci90'], pct=True)}")
        add("roi_dodatni_istotnie", lo > 0, "dolna granica CI90 ROI > 0", hard=False)
    elif bstats:
        add("proba_zakladow", False, f"{bstats['n_bets']} zakladow (min {G['min_bets']})", hard=False)
    return res


def fmt_ci(ci, pct=False):
    return f"[{ci[0]:+.2%}, {ci[1]:+.2%}]" if pct else f"[{ci[0]:+.4f}, {ci[1]:+.4f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--by", default="sport,league,market")
    ap.add_argument("--drift-by", default="sport,league,market")
    ap.add_argument("--value-threshold", type=float, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--since", default=None, help="RRRR-MM-DD, np. poczatek holdoutu")
    ap.add_argument("--until", default=None)
    for k, v in GATES.items():
        ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    a = ap.parse_args()
    G = {k: getattr(a, k) for k in GATES}

    df = load(a.csv)
    if a.since:
        df = df[df["date"] >= pd.Timestamp(a.since)]
    if a.until:
        df = df[df["date"] <= pd.Timestamp(a.until)]
    df = add_fair_close(df)
    ev, bad_sum, skipped = event_table(df)
    if ev.empty:
        sys.exit("Brak rozliczonych zdarzen do oceny.")
    bets = select_bets(df, a.value_threshold)
    bstats = betting_stats(bets)
    e, rel = ece(df["p_model"], df["outcome"])
    by = [c for c in a.by.split(",") if c]
    segs = segment_report(ev, df, bets, by)
    dby = [c for c in a.drift_by.split(",") if c]
    alarms = {}
    for key, g in (ev.groupby(dby) if dby else [(("all",), ev)]):
        key = key if isinstance(key, tuple) else (key,)
        hits = cusum_drift(g.reset_index(drop=True))
        if hits:
            alarms["/".join(map(str, key))] = hits
    gs = gates(ev, df, bets, bstats, G, bad_sum)
    ready = all(g["wynik"] == "OK" for g in gs if g["twarda"])
    money = ready and any(g["bramka"] == "clv_dodatni" and g["wynik"] == "OK" for g in gs)
    verdict = ("GOTOWY do typowania i gry (CLV potwierdzony)" if money else
               "GOTOWY tylko do typowania (brak dowodu przewagi nad rynkiem)" if ready else
               "NIEGOTOWY")
    misses = ev.nlargest(10, "ll_model")[["date", "event_id", "market", "league", "ll_model"]]
    misses = misses.assign(date=misses["date"].dt.date.astype(str), ll_model=misses["ll_model"].round(3))

    P = print
    P(f"# Raport typera  {ev['date'].min().date()} .. {ev['date'].max().date()}\n")
    P(f"WERDYKT: {verdict}\n")
    if bad_sum:
        P(f"Uwaga: {bad_sum} grup z p_model nie sumujacym sie do 1 (znormalizowano).")
    if skipped:
        P(f"Uwaga: pominieto {skipped} grup bez jednoznacznego wyniku (void/blad).")
    P("## Bramki")
    for g in gs:
        P(f"[{g['wynik']}] {g['bramka']}: {g['info']}")
    P("\n## Metryki ogolne")
    P(f"zdarzenia {len(ev)} | log loss model {ev['ll_model'].mean():.4f}"
      + (f" | baseline {ev['ll_base'].mean():.4f}" if ev['ll_base'].notna().all() else "")
      + (f" | rynek zamk. {ev['ll_market'].mean():.4f}" if ev['ll_market'].notna().all() else "")
      + f" | Brier {ev['brier'].mean():.4f} | ECE {e:.4f}")
    if bstats:
        P(f"zaklady {bstats['n_bets']} | ROI {bstats['roi']:+.2%} CI90 {fmt_ci(bstats['roi_ci90'], True)}"
          + (f" | CLV {bstats['clv_sr']:+.2%} | bije zamkniecie {bstats['bije_zamkniecie']:.0%}"
             if "clv_sr" in bstats else ""))
    P("\n## Kalibracja (koszyki prawdopodobienstwa)")
    P(pd.DataFrame(rel).to_string(index=False))
    P(f"\n## Segmenty ({', '.join(by)}), najgorsze na gorze")
    seg_df = pd.DataFrame(segs)
    for c in ("luka_ci90",):
        if c in seg_df:
            seg_df[c] = seg_df[c].map(lambda t: fmt_ci(t) if isinstance(t, tuple) else "")
    P(seg_df.round(4).to_string(index=False))
    bias = selection_bias(df, by)
    P("\n## Systematyczne odchylenia per selekcja (|odchylenie| > 2.5 SE)")
    P(pd.DataFrame(bias).to_string(index=False) if bias else "brak")
    P("\n## Dryf (CUSUM na nadwyzce log loss)")
    if not alarms:
        P("alarmy: brak")
    for seg, hits in alarms.items():
        P(f"{seg}: {len(hits)} alarm(y), pierwszy {hits[0]}" + (f", ostatni {hits[-1]}" if len(hits) > 1 else ""))
    P("\n## 10 najwiekszych pomylek (do dziennika bledow)")
    P(misses.to_string(index=False))

    if a.json:
        rep = dict(gotowy=ready, gotowy_do_gry=money, werdykt=verdict, bramki=gs, zdarzenia=len(ev),
                   ll_model=ev["ll_model"].mean(), ece=e, zaklady=bstats,
                   segmenty=segs, odchylenia=bias, dryf=alarms,
                   najwieksze_pomylki=misses.astype(str).to_dict("records"))
        with open(a.json, "w") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=float)
    sys.exit(0 if money else (1 if ready else 2))


if __name__ == "__main__":
    main()
