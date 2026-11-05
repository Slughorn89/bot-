"""Spojnosc nazw druzyn w danych historycznych jednego zrodla.

Zrodla potrafia zmienic zapis nazwy w polowie sezonu ("Nottm Forest" -> "Nott'm Forest").
Model traktuje wtedy klub jak beniaminka i gubi jego historie. Dlatego:
  1. nazwy rozniace sie tylko interpunkcja i wielkoscia liter laczymy automatycznie
     (do najnowszego zapisu), z logiem,
  2. aliasy zweryfikowane recznie bierzemy z config/aliases.yaml,
  3. kazde pozostale "przekazanie" (nazwa A znika w trakcie sezonu, nazwa B pojawia sie zaraz po)
     to blad kontraktu: pobranie stoi, dopoki czlowiek nie wpisze decyzji. Nigdy po cichu.
"""
from __future__ import annotations

import difflib
import logging
import re

import pandas as pd

from typer.entities.mapping import normalize

log = logging.getLogger("typer.entities.history")


def squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def auto_aliases(df: pd.DataFrame) -> dict[str, dict[str, str]]:
    """{liga: {stara_nazwa: kanoniczna}} dla nazw identycznych po usunieciu interpunkcji."""
    out: dict[str, dict[str, str]] = {}
    for lg, g in df.groupby("league"):
        last = pd.concat([g[["home", "date"]].set_axis(["t", "d"], axis=1),
                          g[["away", "date"]].set_axis(["t", "d"], axis=1)]).groupby("t")["d"].max()
        groups: dict[str, list[str]] = {}
        for n in last.index:
            groups.setdefault(squash(n), []).append(n)
        for names in groups.values():
            if len(names) > 1:
                canon = max(names, key=lambda n: last[n])  # najnowszy zapis
                for n in names:
                    if n != canon:
                        out.setdefault(lg, {})[n] = canon
    return out


def apply_aliases(df: pd.DataFrame, aliases: dict[str, dict[str, str]]) -> pd.DataFrame:
    if not aliases:
        return df
    df = df.copy()
    for lg, mp in aliases.items():
        m = df["league"] == lg
        df.loc[m, "home"] = df.loc[m, "home"].replace(mp)
        df.loc[m, "away"] = df.loc[m, "away"].replace(mp)
    return df


def name_handovers(df: pd.DataFrame, min_similarity: float = 0.5) -> list[dict]:
    """Pary (A, B) w tej samej lidze i sezonie: A gra tylko na poczatku, B tylko na koncu,
    lacznie ok. tyle meczow, co typowa druzyna, a nazwy sa podobne. To prawie zawsze ten sam klub."""
    out = []
    long = pd.concat([df[["league", "season", "home", "date"]].set_axis(["league", "season", "t", "d"], axis=1),
                      df[["league", "season", "away", "date"]].set_axis(["league", "season", "t", "d"], axis=1)])
    for (lg, se), g in long.groupby(["league", "season"]):
        st = g.groupby("t")["d"].agg(["min", "max", "size"])
        med = st["size"].median()
        part = st[st["size"] < 0.8 * med]
        for a, ra in part.iterrows():
            for b, rb in part.iterrows():
                if a == b or not ra["max"] < rb["min"]:
                    continue
                total = ra["size"] + rb["size"]
                sim = difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()
                prefix = normalize(b).startswith(normalize(a).rstrip(". ").split(" ")[0])
                if abs(total - med) <= 0.15 * med and (sim >= min_similarity or prefix):
                    out.append(dict(league=lg, season=se, stara=a, nowa=b, mecze_stara=int(ra["size"]),
                                    mecze_nowa=int(rb["size"]), od=str(rb["min"]), podobienstwo=round(sim, 2)))
    return out


def harmonize(df: pd.DataFrame, manual: dict[str, dict[str, str]] | None = None) -> pd.DataFrame:
    """Automatyczne + reczne aliasy, potem kontrola przekazan. Rzuca ContractError, gdy zostaje
    niezweryfikowane przekazanie nazwy."""
    from typer.ingest.schema import ContractError
    auto = auto_aliases(df)
    for lg, mp in auto.items():
        for a, b in mp.items():
            log.warning("alias automatyczny %s: %r -> %r", lg, a, b)
    df = apply_aliases(df, auto)
    df = apply_aliases(df, manual or {})
    left = name_handovers(df)
    if left:
        lines = [f"{h['league']} {h['season']}: {h['stara']!r} ({h['mecze_stara']} m.) -> {h['nowa']!r} "
                 f"({h['mecze_nowa']} m., od {h['od']})" for h in left]
        raise ContractError("niezweryfikowana zmiana nazwy druzyny w trakcie sezonu (dopisz decyzje do "
                            "config/aliases.yaml):\n  " + "\n  ".join(lines))
    return df
