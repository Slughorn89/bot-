"""Wyznaczanie sezonu z dat meczow (zrodla nie zawsze maja kolumne sezonu)."""
from __future__ import annotations

import pandas as pd

# Nowy sezon zaczyna sie po przerwie > MIN_GAP dni, jesli wznowienie wypada w lipcu-wrzesniu.
# Dzieki temu przerwa covidowa (wznowienie maj-czerwiec 2020) i przerwa zimowa nie tna sezonu.
MIN_GAP_DAYS = 25
START_MONTHS = (7, 8, 9)


def assign_seasons(dates: pd.Series) -> pd.Series:
    """dates: daty meczow jednej ligi. Zwraca etykiety '2024-25' w kolejnosci wejscia."""
    d = pd.to_datetime(dates)
    order = d.sort_values(kind="stable")
    gaps = order.diff().dt.days.fillna(0)
    new_season = (gaps > MIN_GAP_DAYS) & order.dt.month.isin(START_MONTHS)
    season_idx = new_season.cumsum()
    first_dates = order.groupby(season_idx).transform("min")
    start_year = first_dates.dt.year - (first_dates.dt.month < 7).astype(int)
    labels = start_year.astype(str) + "-" + ((start_year + 1) % 100).astype(str).str.zfill(2)
    return labels.reindex(d.index)


def season_of_date(date) -> str:
    """Przyblizona etykieta sezonu dla pojedynczej daty (do terminarza): lipiec = nowy sezon."""
    t = pd.Timestamp(date)
    y = t.year if t.month >= 7 else t.year - 1
    return f"{y}-{(y + 1) % 100:02d}"
