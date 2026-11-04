"""Reguly "as of": z jakich danych wolno korzystac przy typowaniu meczu.

football-data.co.uk zbiera kursy sprzed meczu w piatek po poludniu (mecze pt-pn) i we wtorek
po poludniu (mecze wt-czw). Jesli w backteście "bierzemy" te kursy, to typ musi powstac z danych
dostepnych w chwili ich zebrania, czyli z wynikow sprzed tego dnia. Tryb "fduk" robi dokladnie to.
Tryb "day" (typowanie na zywo 60-90 min przed meczem): wszystkie mecze z poprzednich dni.
"""
from __future__ import annotations

from datetime import date as Date, datetime, time, timedelta, timezone

import pandas as pd

COLLECTION_HOUR_UTC = 12


def prediction_cutoff(d, mode: str = "fduk") -> Date:
    """Pierwszy dzien, ktorego wynikow NIE wolno uzyc przy typowaniu meczu z dnia d."""
    d = pd.Timestamp(d).date()
    if mode == "day":
        return d
    if mode != "fduk":
        raise ValueError(mode)
    wd = d.weekday()  # pon=0 ... nd=6
    if wd in (4, 5, 6, 0):          # pt, sob, nd, pn -> ostatni piatek
        back = (wd - 4) % 7
    else:                            # wt, sr, czw -> ostatni wtorek
        back = wd - 1
    return d - timedelta(days=back)


def collection_time(d, mode: str = "fduk") -> datetime:
    """Szacowana chwila zebrania kursu 'wzietego' (do odds_snapshots)."""
    c = prediction_cutoff(d, mode)
    return datetime.combine(c, time(COLLECTION_HOUR_UTC), tzinfo=timezone.utc)
