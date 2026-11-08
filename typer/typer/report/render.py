"""Komponenty raportu (sekcja 13.2) i kanaly (13.3). Czyste funkcje: JSON -> tekst/HTML.

Komponenty: KartaTypu, PasekBramek, KartaMetryki, TabelaSegmentow, Alarm.
Kanaly: CLI (<= 100 znakow, bez ANSI), Telegram (<= 4096 znakow na wiadomosc, najpierw werdykt
i typy, kazdy alarm osobno, segmenty jako zalacznik HTML), HTML (kontrast >= 4.5:1, status
zawsze podpisany slowem, <th scope>, liczby do prawej cyframi o stalej szerokosci).
Nowy element raportu: najpierw opis w sekcji 13 skilla, potem kod tutaj.
"""
from __future__ import annotations

import html
import textwrap

from typer.report import fmt

WIDTH = 100
TG_LIMIT = 4096
ACTION_ALARM = "diagnoza wg sekcji 9.4: potok danych -> odchylenia -> poprawka celowana jako challenger"
STATUS_RANK = {"error": 0, "warn": 1, "na": 2, "ok": 3}


# ----------------------------------------------------------------- komponenty (dane)
def karta_typu(t: dict, threshold: float) -> dict:
    """Stan: normalny | ponizej_progu (nie wysylamy) | kurs_sie_ruszyl (stary -> nowy)."""
    state = "normalny"
    if t.get("przewaga") is None or t["przewaga"] < threshold:
        state = "ponizej_progu"
    elif t.get("kurs_poprzedni") and abs(t["kurs_poprzedni"] - t["kurs"]) >= 0.01:
        state = "kurs_sie_ruszyl"
    return dict(t, stan=state)


def pasek_bramek(bramki: list[dict]) -> list[dict]:
    """Twarde przed ostrzezeniami, bledy na gorze."""
    rows = [dict(b, status=fmt.GATE_TO_STATUS.get(b["wynik"], "na")) for b in bramki]
    return sorted(rows, key=lambda b: (b["status"] != "error", not b.get("twarda", True),
                                       STATUS_RANK[b["status"]]))


def karta_metryki(nazwa: str, wartosc: str, n, ci: str = "", rynek: str = "", status: str | None = None) -> dict:
    if fmt.small_sample(n):
        status, uwaga = "na", "za mało danych"
    else:
        uwaga = ""
    return dict(nazwa=nazwa, wartosc=wartosc, n=n, ci=ci, rynek=rynek, status=status or "ok", uwaga=uwaga)


def tabela_segmentow(segmenty: list[dict]) -> list[dict]:
    out = []
    for s in segmenty:
        seg = "/".join(str(s[k]) for k in ("league", "market") if k in s)
        st = "error" if s.get("slaby") else ("na" if fmt.small_sample(s.get("n")) else "ok")
        lc = s.get("luka_ci90")
        out.append(dict(segment=seg, n=s.get("n"), ll=fmt.ll(s.get("ll_model")),
                        luka=(fmt.with_ci(s["luka_vs_rynek"], lc[0], lc[1], "gap") if lc else "--"),
                        ece=fmt.ece(s.get("ece")), clv=fmt.pct(s.get("clv")), status=st,
                        _sort=s.get("luka_vs_rynek", s.get("ll_model", 0)) or 0))
    return sorted(out, key=lambda r: -r["_sort"])


def alarmy(dryf: dict, inne: list[dict] | None = None) -> list[dict]:
    out = [dict(typ="dryf", segment=seg, od=hits[0], ile=len(hits), co_zrobic=ACTION_ALARM)
           for seg, hits in (dryf or {}).items()]
    return out + list(inne or [])


# ----------------------------------------------------------------- CLI
def _wrap(text: str, indent: str = "  ") -> list[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=indent + "  ") or [indent]


def _tip_lines(t: dict) -> list[str]:
    """KartaTypu w CLI. Nic nie ucinamy: za dlugie linie sa zawijane."""
    out = _wrap(f"{t['godz']} {t['liga']} {t['mecz']}")
    out += _wrap(f"{t['rynek']} {t['selekcja']} | p {fmt.p(t['p'])} | kurs fair {fmt.odds(t['kurs_fair'])} | "
                 f"kurs {fmt.odds(t['kurs'])} | przewaga {fmt.pct(t['przewaga'])} | stawka {fmt.stake(t['stawka'])}",
                 indent="    ")
    if t["stan"] == "kurs_sie_ruszyl":
        out += _wrap(f"kurs się ruszył: {fmt.odds(t['kurs_poprzedni'])} -> {fmt.odds(t['kurs'])}", indent="    ")
    return out


def _metric_line(m: dict, ch: str = "cli") -> str:
    parts = [f"{m['nazwa']} {m['wartosc']}"]
    if m["ci"]:
        parts[0] += f" {m['ci']}"
    if m["rynek"]:
        parts.append(f"vs rynek {m['rynek']}")
    parts.append(fmt.n(m["n"]))
    txt = " | ".join(parts)
    if m["status"] != "ok":
        txt = f"{fmt.token(m['status'], ch)} {txt}" + (f" ({m['uwaga']})" if m["uwaga"] else "")
    return txt


def window_metrics(w: dict) -> list[dict]:
    """KartaMetryki dla okna (z podsumowania evaluate.py)."""
    if not w:
        return []
    z = w.get("zaklady") or {}
    out = [karta_metryki("log loss", fmt.ll(w.get("ll")), w.get("n"),
                         rynek=(f"{fmt.ll(w['ll_rynek'])} (luka {fmt.gap(w['luka'])}, {fmt.n(w['n_rynek'])})"
                                if w.get("ll_rynek") is not None else "brak kursów zamknięcia")),
           karta_metryki("ECE", fmt.ece(w.get("ece")), w.get("n"),
                         status="ok" if (w.get("ece") or 0) <= 0.03 else "error")]
    if z.get("clv_sr") is not None:
        out.append(karta_metryki("CLV", fmt.pct(z["clv_sr"]), z.get("n_bets"), ci=fmt.ci(*z["clv_ci90"]),
                                 status="ok" if z["clv_ci90"][0] > 0 else "warn"))
    if z.get("roi") is not None:
        out.append(karta_metryki("ROI", fmt.pct(z["roi"]), z.get("n_bets"), ci=fmt.ci(*z["roi_ci90"]),
                                 status="error" if z["roi_ci90"][1] <= 0 else "ok"))
    return out


def render_cli(p: dict) -> str:
    L = [f"TYPER  {p['data']}  (model {p.get('model', {}).get('version', '?')})"]
    st, txt = fmt.verdict_status(p.get("stan_modelu", {}).get("werdykt"))
    bad = p.get("stan_modelu", {}).get("niezaliczone") or []
    L += _wrap(f"Stan modelu: {fmt.token(st)} {txt} ({fmt.n(p.get('stan_modelu', {}).get('n'))}, "
               f"od wdrożenia {p.get('stan_modelu', {}).get('od', '?')})"
               + (f"; niezaliczone bramki: {', '.join(bad)}" if bad else ""), indent="")
    L.append("Typy na dziś")
    sent = [t for t in p.get("typy", []) if t["stan"] != "ponizej_progu"]
    for t in sent:
        L += _tip_lines(t)
    if not sent:
        L.append("  brak zakładów z przewagą powyżej progu")
    L.append("Wczoraj")
    w = p.get("wczoraj") or {}
    if w.get("typy"):
        clv = fmt.pct(w["clv"]) + f" ({fmt.n(w['clv_n'])})" if w.get("clv") is not None else "brak kursów zamknięcia"
        L.append(f"  {w['typy']} typów, trafione {w['trafione']}, CLV śr. {clv}, wynik {w['wynik_j']:+.2f} j")
    else:
        L.append("  brak rozliczonych zakładów")
    L.append("Okno 30 / 90 dni")
    for days in ("30", "90"):
        ms = window_metrics(p.get("okna", {}).get(days) or {})
        if not ms:
            L.append(f"  {days} dni: {fmt.token('na')} brak rozliczonych predykcji")
            continue
        L += _wrap(f"{days} dni: " + " ; ".join(_metric_line(m) for m in ms))
    L.append("Alarmy")
    al = p.get("alarmy", [])
    for a in al:
        seg = f" {a['segment']}" if a.get("segment") else ""
        L += _wrap(f"{fmt.token('warn')} {a['typ']}{seg} od {a.get('od', '?')}: "
                   f"{a.get('info') or a.get('co_zrobic', '')}")
    if not al:
        L.append("  brak")
    L.append("Wnioski")
    for x in p.get("wnioski", []):
        L += _wrap(x)
    if not p.get("wnioski"):
        L.append("  brak nowych wpisów w dzienniku błędów")
    assert all(len(line) <= WIDTH for line in L), "CLI: linia dluzsza niz 100 znakow"
    return "\n".join(L)


# ----------------------------------------------------------------- Telegram
def render_telegram(p: dict) -> list[str]:
    """Lista wiadomosci. 1: werdykt + typy, 2: metryki, potem kazdy alarm osobno, na koncu wnioski."""
    st, txt = fmt.verdict_status(p.get("stan_modelu", {}).get("werdykt"))
    bad = p.get("stan_modelu", {}).get("niezaliczone") or []
    m1 = [f"TYPER {p['data']}", f"Stan modelu: {fmt.token(st, 'tg')} {txt} "
                                f"({fmt.n(p.get('stan_modelu', {}).get('n'))})"
                                + (f"\nniezaliczone bramki: {', '.join(bad)}" if bad else ""), "", "Typy na dziś"]
    sent = [t for t in p.get("typy", []) if t["stan"] != "ponizej_progu"]
    for t in sent:
        moved = f" (kurs się ruszył: {fmt.odds(t['kurs_poprzedni'])} → {fmt.odds(t['kurs'])})" \
            if t["stan"] == "kurs_sie_ruszyl" else ""
        m1.append(f"{t['godz']} {t['liga']} {t['mecz']}\n  {t['rynek']} {t['selekcja']} | p {fmt.p(t['p'])} | "
                  f"fair {fmt.odds(t['kurs_fair'])} | kurs {fmt.odds(t['kurs'])} | przewaga {fmt.pct(t['przewaga'])} | "
                  f"stawka {fmt.stake(t['stawka'])}{moved}")
    if not sent:
        m1.append("brak zakładów z przewagą powyżej progu (nowe typy przychodzą osobno, ok. 90 min przed meczem)")
    m2 = ["Wyniki"]
    w = p.get("wczoraj") or {}
    m2.append(f"Wczoraj: {w['typy']} typów, trafione {w['trafione']}, wynik {w['wynik_j']:+.2f} j"
              if w.get("typy") else "Wczoraj: brak rozliczonych zakładów")
    for days in ("30", "90"):
        ms = window_metrics(p.get("okna", {}).get(days) or {})
        m2.append(f"{days} dni: " + (" ; ".join(_metric_line(m, "tg") for m in ms) if ms
                                    else f"{fmt.token('na', 'tg')}"))
    msgs = ["\n".join(m1), "\n".join(m2)]
    for a in p.get("alarmy", []):
        seg = f" {a['segment']}" if a.get("segment") else ""
        msgs.append(f"{fmt.token('warn', 'tg')} Alarm: {a['typ']}{seg}\n"
                    f"od: {a.get('od', '?')}\n{a.get('info') or a.get('co_zrobic', '')}")
    if p.get("wnioski"):
        msgs.append("Wnioski\n" + "\n".join(p["wnioski"]))
    out = []
    for m in msgs:  # twardy limit kanalu: dzielimy po liniach, nigdy nie ucinamy po cichu
        while len(m) > TG_LIMIT:
            cut = m.rfind("\n", 0, TG_LIMIT)
            cut = cut if cut > 0 else TG_LIMIT
            out.append(m[:cut])
            m = m[cut:].lstrip("\n")
        out.append(m)
    return out


def nowy_typ(t: dict) -> str:
    """Jedna wiadomosc Telegrama dla typu postawionego tuz przed meczem (ten sam uklad co w raporcie)."""
    return (f"Nowy typ\n{t['godz']} {t['liga']} {t['mecz']}\n"
            f"{t['rynek']} {t['selekcja']} | kurs {fmt.odds(t['kurs'])} (fair {fmt.odds(t['kurs_fair'])})\n"
            f"p {fmt.p(t['p'])} | przewaga {fmt.pct(t['przewaga'])} | stawka {fmt.stake(t['stawka'])}\n"
            "Zakład papierowy: sprawdź kurs u siebie przed graniem.")


def render_preview(preds, chosen: list[dict], tz: str, limit: int = 25) -> list[str]:
    """Podglad (cli.py preview): kandydaci z przewaga i rozklad 1X2 kazdego meczu. Wyraznie wstepne."""
    import pandas as pd
    def godz(k):
        return pd.Timestamp(k).tz_convert(tz).strftime("%d.%m %H:%M") if pd.Timestamp(k).tzinfo \
            else pd.Timestamp(k).tz_localize("UTC").tz_convert(tz).strftime("%d.%m %H:%M")
    head = ("WSTĘPNE TYPY (podgląd, bez składów)\nTo nie są zakłady. Właściwy typ przyjdzie ok. 90 min przed "
            "meczem i może się różnić.")
    m1 = [head, "", "Z przewagą przy obecnym kursie:"]
    for c in chosen[:limit]:
        m1.append(f"{godz(c['kickoff_utc'])} {c['league']} {c['home']} - {c['away']}\n  {c['market']} "
                  f"{c['selection']} | kurs {fmt.odds(c['odds'])} (fair {fmt.odds(1 / c['p'])}) | "
                  f"p {fmt.p(c['p'])} | przewaga {fmt.pct(c['edge'])}")
    if not chosen:
        m1.append("brak (albo nie ma jeszcze kursów na te mecze)")
    m2 = ["Szanse według modelu (1 / X / 2):"]
    if len(preds):
        x = preds[preds["market"] == "1X2"].pivot_table(
            index=["kickoff_utc", "league", "home", "away"], columns="selection", values="p_model").reset_index()
        x = x.sort_values("kickoff_utc")
        for _, d in x.head(limit).iterrows():
            m2.append(f"{godz(d['kickoff_utc'])} {d['league']} {d['home']} - {d['away']}: "
                      f"{fmt.p(d.get('1'))} / {fmt.p(d.get('X'))} / {fmt.p(d.get('2'))}")
        if len(x) > limit:
            m2.append(f"... i {len(x) - limit} kolejnych")
    else:
        m2.append("brak meczów w terminarzu na najbliższe 3 dni")
    out = []
    for m in ("\n".join(m1), "\n".join(m2)):
        while len(m) > TG_LIMIT:
            cut = m.rfind("\n", 0, TG_LIMIT)
            cut = cut if cut > 0 else TG_LIMIT
            out.append(m[:cut])
            m = m[cut:].lstrip("\n")
        out.append(m)
    return out


def render_history(h: dict) -> list[str]:
    """Symulacja wstecz (cli.py history): bilans i lista typow z wynikami."""
    tips = h.get("typy", [])
    head = [f"TYPY WSTECZ {h['od']} .. {h['do']} (symulacja)",
            "Model widział tylko mecze sprzed dnia typu. Kursy przedmeczowe z football-data.co.uk, "
            "nie z chwili typu, więc wynik jest przybliżony.", ""]
    if not tips:
        return ["\n".join(head + [f"Rozegrane mecze: {h.get('mecze', 0)}, brak typów z przewagą powyżej progu."])]
    n, hit = len(tips), sum(1 for t in tips if t["trafiony"] == 1)
    flat = sum((t["odds"] - 1) if t["trafiony"] == 1 else -1 for t in tips)
    kelly = sum(t["stake_frac"] * ((t["odds"] - 1) if t["trafiony"] == 1 else -1) for t in tips) * 100
    head += [f"Rozegrane mecze: {h.get('mecze', 0)}, typy: {n}, trafione: {hit} ({hit / n:.0%})",
             f"Stała stawka 10 zł na typ: {flat * 10:+.2f} zł (ROI {flat / n:+.1%})",
             f"Stawki typera (Kelly): {kelly:+.2f} j (1 j = 1% bankrolla)",
             "Kilka tygodni to za mało, żeby ocenić typera: o przewadze mówi dopiero CLV na setkach typów.", ""]
    lines = []
    for t in tips:
        mark = "✅" if t["trafiony"] == 1 else "❌"
        lines.append(f"{t['data'][8:10]}.{t['data'][5:7]} {t['league']} {t['home']} - {t['away']} "
                     f"{t['fthg']}:{t['ftag']}\n  {mark} {t['market']} {t['selection']} kurs {fmt.odds(t['odds'])} "
                     f"| p {fmt.p(t['p'])} | przewaga {fmt.pct(t['edge'])}")
    m = "\n".join(head + lines)
    out = []
    while len(m) > TG_LIMIT:
        cut = m.rfind("\n", 0, TG_LIMIT)
        cut = cut if cut > 0 else TG_LIMIT
        out.append(m[:cut])
        m = m[cut:].lstrip("\n")
    out.append(m)
    return out


# ----------------------------------------------------------------- HTML
CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#101828;background:#fff;
max-width:980px;margin:24px auto;padding:0 16px;line-height:1.45}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.6em}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border-bottom:1px solid #EAECF0;padding:6px 8px;text-align:left}
th{background:#F9FAFB;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums;font-family:ui-monospace,Consolas,monospace}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-weight:600;font-size:.9em}
"""


def badge(status: str) -> str:
    s = fmt.STATUS[status]
    return f'<span class="badge" style="background:{s["bg"]};color:{s["fg"]}">{html.escape(s["label"])}</span>'


def _table(headers: list[str], rows: list[list[str]], num_cols: set[int]) -> str:
    th = "".join(f'<th scope="col">{html.escape(h)}</th>' for h in headers)
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            cls = ' class="num"' if i in num_cols else ""
            tds.append(f"<td{cls}>{c}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html_evaluation(rep: dict, title: str) -> str:
    """Raport z JSON-a evaluate.py (schema typer.report/v2): PasekBramek, metryki, TabelaSegmentow."""
    st, txt = fmt.verdict_status(rep.get("werdykt"))
    e = html.escape
    parts = [f"<!DOCTYPE html><html lang=\"pl\"><head><meta charset=\"utf-8\"><title>{e(title)}</title>"
             f"<style>{CSS}</style></head><body>",
             f"<h1>{e(title)}</h1>",
             f"<p>Okres {e(' .. '.join(rep.get('okres', ['?', '?'])))} | {fmt.n(rep.get('zdarzenia'))} | "
             f"werdykt: {badge(st)} {e(txt)}</p>", "<h2>Bramki</h2>"]
    rows = [[badge(b["status"]), e(b["bramka"]), "twarda" if b.get("twarda") else "ostrzeżenie", e(b["info"])]
            for b in pasek_bramek(rep.get("bramki", []))]
    parts.append(_table(["Status", "Bramka", "Typ", "Opis"], rows, set()))
    parts.append("<h2>Metryki</h2>")
    w = dict(n=rep.get("zdarzenia"), ll=rep.get("ll_model"), ece=rep.get("ece"), zaklady=rep.get("zaklady") or {})
    rows = [[badge(m["status"]), e(m["nazwa"]), e(m["wartosc"]), e(m["ci"]), e(fmt.n(m["n"])), e(m["rynek"] or m["uwaga"])]
            for m in window_metrics(w)]
    parts.append(_table(["Status", "Metryka", "Wartość", "CI90", "n", "Uwagi"], rows, {2, 3, 4}))
    parts.append("<h2>Segmenty (najgorsze na górze)</h2>")
    rows = [[badge(s["status"]), e(s["segment"]), e(str(s["n"])), e(s["ll"]), e(s["luka"]), e(s["ece"]), e(s["clv"])]
            for s in tabela_segmentow(rep.get("segmenty", []))]
    parts.append(_table(["Status", "Segment", "n", "Log loss", "Luka do rynku [CI90]", "ECE", "CLV"], rows,
                        {2, 3, 4, 5, 6}))
    al = alarmy(rep.get("dryf", {}))
    parts.append("<h2>Alarmy</h2>")
    parts.append("<p>brak</p>" if not al else _table(
        ["Status", "Typ", "Segment", "Pierwszy sygnał", "Co zrobić"],
        [[badge("warn"), e(a["typ"]), e(a["segment"]), e(a["od"]), e(a["co_zrobic"])] for a in al], {3}))
    parts.append("<p><small>Wszystkie liczby z tools/evaluate.py (bez ręcznych wpisów). "
                 "Status zawsze podpisany słowem.</small></p></body></html>")
    return "\n".join(parts)


def render_html_daily(p: dict) -> str:
    e = html.escape
    st, txt = fmt.verdict_status(p.get("stan_modelu", {}).get("werdykt"))
    parts = [f"<!DOCTYPE html><html lang=\"pl\"><head><meta charset=\"utf-8\"><title>Typer {e(p['data'])}</title>"
             f"<style>{CSS}</style></head><body><h1>Typer {e(p['data'])}</h1>",
             f"<p>Stan modelu {e(p.get('model', {}).get('version', '?'))}: {badge(st)} {e(txt)} "
             f"({e(fmt.n(p.get('stan_modelu', {}).get('n')))})</p>", "<h2>Typy na dziś</h2>"]
    sent = [t for t in p.get("typy", []) if t["stan"] != "ponizej_progu"]
    parts.append("<p>brak zakładów z przewagą powyżej progu</p>" if not sent else _table(
        ["Godz.", "Liga", "Mecz", "Rynek", "Selekcja", "p", "Kurs fair", "Kurs", "Przewaga", "Stawka"],
        [[e(t["godz"]), e(t["liga"]), e(t["mecz"]), e(t["rynek"]), e(t["selekcja"]), fmt.p(t["p"]),
          fmt.odds(t["kurs_fair"]), fmt.odds(t["kurs"]), fmt.pct(t["przewaga"]), fmt.stake(t["stawka"])]
         for t in sent], {5, 6, 7, 8, 9}))
    for days in ("30", "90"):
        ms = window_metrics(p.get("okna", {}).get(days) or {})
        parts.append(f"<h2>Okno {days} dni</h2>")
        parts.append("<p>" + badge("na") + " brak rozliczonych predykcji</p>" if not ms else _table(
            ["Status", "Metryka", "Wartość", "CI90", "n", "Rynek / uwagi"],
            [[badge(m["status"]), e(m["nazwa"]), e(m["wartosc"]), e(m["ci"]), e(fmt.n(m["n"])),
              e(m["rynek"] or m["uwaga"])] for m in ms], {2, 3, 4}))
    if p.get("segmenty"):
        parts.append("<h2>Segmenty (90 dni, najgorsze na górze)</h2>")
        parts.append(_table(["Status", "Segment", "n", "Log loss", "Luka do rynku [CI90]", "ECE", "CLV"],
                            [[badge(s["status"]), e(s["segment"]), e(str(s["n"])), e(s["ll"]), e(s["luka"]),
                              e(s["ece"]), e(s["clv"])] for s in tabela_segmentow(p["segmenty"])], {2, 3, 4, 5, 6}))
    parts.append("<h2>Alarmy</h2>")
    al = p.get("alarmy", [])
    parts.append("<p>brak</p>" if not al else _table(
        ["Status", "Typ", "Segment", "Od", "Opis"],
        [[badge("warn"), e(a["typ"]), e(a.get("segment", "")), e(a.get("od", "")),
          e(a.get("info") or a.get("co_zrobic", ""))] for a in al], set()))
    parts.append("</body></html>")
    return "\n".join(parts)


def contrast_ratio(fg: str, bg: str) -> float:
    """Kontrast WCAG 2.1 (do testu tokenow: >= 4.5:1)."""
    def lum(hexc):
        c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = sorted([lum(fg), lum(bg)], reverse=True)
    return (a + 0.05) / (b + 0.05)


def render_cli_weekly(w: dict, title: str = "PRZEGLAD TYGODNIOWY") -> str:
    rep = w.get("ocena") or {}
    mv = w.get("model") or {}
    L = [f"{title}  {w.get('data')}" + (f"  (model {mv.get('version')}, od wdrożenia {mv.get('od')})"
                                         if mv.get("version") else "")]
    if not rep:
        L.append(f"  {fmt.token('na')} brak rozliczonych predykcji od daty wdrożenia")
        return "\n".join(L)
    st, txt = fmt.verdict_status(rep.get("werdykt"))
    L.append(f"Werdykt: {fmt.token(st)} {txt} ({fmt.n(rep.get('zdarzenia'))}, okres "
             f"{' .. '.join(rep.get('okres', ['?', '?']))})")
    L.append("Bramki")
    for b in pasek_bramek(rep.get("bramki", [])):
        L += _wrap(f"{fmt.token(b['status'])} {b['bramka']}: {b['info']}")
    L.append("Metryki")
    s = w.get("podsumowanie") or {}
    L += _wrap(" ; ".join(_metric_line(m) for m in window_metrics(s)))
    L.append("Segmenty (najgorsze na górze)")
    for r in tabela_segmentow(rep.get("segmenty", []))[:8]:
        L += _wrap(f"{fmt.token(r['status'])} {r['segment']} {fmt.n(r['n'])} | log loss {r['ll']} | luka {r['luka']} "
                   f"| ECE {r['ece']} | CLV {r['clv']}")
    korekta = [k for k in w.get("segmenty_po_korekcie", []) if k["slaby_bez_korekty"]]
    if korekta:
        L.append("Segmenty 'slaby' po korekcie Bonferroniego (sekcja 14.3)")
        for k in korekta:
            st = "error" if k["slaby_po_korekcie"] else "warn"
            L += _wrap(f"{fmt.token(st)} {k.get('league')}/{k.get('market')} luka {fmt.gap(k['luka'])}, "
                       f"p={k['p_jednostronne']:.4f}, m={k['m']}: "
                       + ("istotne po korekcie" if k["slaby_po_korekcie"] else "nieistotne po korekcie, "
                          "potwierdź na nowym okresie"))
    L.append("Kontrole danych (sekcja 14.2)")
    for c in w.get("kontrole_danych", []):
        L += _wrap(f"{fmt.token(c['status'])} {c['kontrola']}: {c['info']}")
    L.append("Alarmy")
    al = alarmy(rep.get("dryf", {}))
    for a in al:
        L += _wrap(f"{fmt.token('warn')} dryf {a['segment']} od {a['od']}: {a['co_zrobic']}")
    if not al:
        L.append("  brak")
    return "\n".join(L)
