"""Zloty plik aliasow (sekcja 12.1): kazdy znany alias trafia do wlasciwej nazwy, niepewne do kolejki."""
import csv
from pathlib import Path

import pytest

from typer.entities.mapping import ALIASES, resolve

GOLD = list(csv.DictReader(open(Path(__file__).parent / "fixtures" / "aliases_golden.csv", encoding="utf-8")))


@pytest.mark.parametrize("row", GOLD, ids=[r["raw"] for r in GOLD])
def test_zloty_plik(row):
    m = resolve(row["raw"], row["candidates"].split(";"))
    if row["expected"] == "PENDING":
        assert m.status == "pending", "niepewne dopasowanie nie moze przejsc po cichu"
    else:
        assert m.canonical == row["expected"] and m.status in ("alias", "auto")


@pytest.mark.parametrize("raw,canon", sorted(ALIASES.items()))
def test_kazdy_alias_ze_slownika_dziala(raw, canon):
    assert resolve(raw, [canon, "Inna Druzyna FC"]).canonical == canon
