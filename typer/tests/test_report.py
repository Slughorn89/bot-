"""Raporty (sekcje 11 i 13): snapshot z zamrozonego JSON-a, limity kanalow, tokeny, dostepnosc HTML."""
import json
import re
from pathlib import Path

import pytest

from typer.report import fmt, render

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def payload():
    return json.loads((FIX / "report_payload.json").read_text())


def test_snapshot_cli(payload):
    """Raport z zamrozonego JSON-a daje identyczny tekst. Zmiana szablonu = swiadoma aktualizacja pliku."""
    assert render.render_cli(payload) + "\n" == (FIX / "report_cli.txt").read_text()


def test_cli_szerokosc_i_bez_ansi(payload):
    txt = render.render_cli(payload)
    assert all(len(line) <= 100 for line in txt.splitlines())
    assert "\x1b[" not in txt


def test_cli_kolejnosc_sekcji_jak_w_sekcji_11(payload):
    txt = render.render_cli(payload)
    order = [txt.index(h) for h in ("TYPER", "Typy na dziś", "Wczoraj", "Okno 30 / 90 dni", "Alarmy", "Wnioski")]
    assert order == sorted(order)


def test_typ_ponizej_progu_nie_jest_wysylany(payload):
    assert "Roma - Lazio" not in render.render_cli(payload)
    assert all("Roma - Lazio" not in m for m in render.render_telegram(payload))


def test_kurs_sie_ruszyl_pokazuje_stary_i_nowy(payload):
    assert "kurs się ruszył: 2.05 -> 1.95" in render.render_cli(payload)
    assert "2.05 → 1.95" in render.render_telegram(payload)[0]


def test_mala_proba_ma_status_na_i_dopisek(payload):
    txt = render.render_cli(payload)
    line30 = txt[txt.index("  30 dni:"):txt.index("  90 dni:")]
    assert "[--]" in line30 and "za mało danych" in line30


def test_zadna_metryka_bez_n_i_roi_bez_przedzialu(payload):
    txt = render.render_cli(payload)
    for m in re.finditer(r"ROI [+-]\d+\.\d%", txt):
        assert txt[m.end():m.end() + 2] == " [", "ROI bez przedzialu"
    for part in re.split(r" ; ", txt[txt.index("30 dni"):txt.index("Alarmy")]):
        assert "n=" in part, part


def test_telegram_werdykt_i_typy_najpierw_kazdy_alarm_osobno(payload):
    msgs = render.render_telegram(payload)
    assert msgs[0].startswith("TYPER") and "Stan modelu" in msgs[0] and "Arsenal - Chelsea" in msgs[0]
    alarm_msgs = [m for m in msgs if "Alarm:" in m]
    assert len(alarm_msgs) == len(payload["alarmy"])
    assert all(len(m) <= render.TG_LIMIT for m in msgs)


def test_telegram_dzieli_dlugie_wiadomosci_zamiast_ucinac(payload):
    many = dict(payload, typy=[dict(payload["typy"][0], mecz=f"Druzyna {i} - Rywal {i}") for i in range(200)])
    msgs = render.render_telegram(many)
    assert all(len(m) <= render.TG_LIMIT for m in msgs)
    joined = "\n".join(msgs)
    assert all(f"Druzyna {i} - Rywal {i}" in joined for i in range(200))


def test_html_dostepnosc(payload):
    page = render.render_html_daily(payload)
    assert '<th scope="col">' in page and 'lang="pl"' in page
    assert "tabular-nums" in page
    for st in ("ok", "warn", "error", "na"):  # status zawsze podpisany slowem
        assert fmt.STATUS[st]["label"]
    assert "UWAGA" in page and "BŁĄD" in page  # dryf = warn, slaby segment = error


@pytest.mark.parametrize("status", ["ok", "warn", "error", "na"])
def test_kontrast_tokenow_wcag_aa(status):
    s = fmt.STATUS[status]
    assert render.contrast_ratio(s["fg"], s["bg"]) >= 4.5


@pytest.mark.parametrize("werdykt,oczekiwany", [
    ("GOTOWY do typowania i gry (CLV potwierdzony)", "ok"),
    ("GOTOWY tylko do typowania (brak dowodu przewagi nad rynkiem)", "warn"),
    ("NIEGOTOWY", "error"),
    ("ZLY PLIK (kontrakt danych)", "error"),
])
def test_werdykt_mapuje_sie_na_tokeny(werdykt, oczekiwany):
    st, txt = fmt.verdict_status(werdykt)
    assert st == oczekiwany
    if "PLIK" in werdykt:
        assert "kontrakt danych" in txt


def test_formaty_liczb_z_sekcji_13():
    assert fmt.p(0.5432) == "0.54"
    assert fmt.odds(2.1) == "2.10"
    assert fmt.ll(0.94481) == "0.9448" and fmt.gap(0.00314) == "+0.0031"
    assert fmt.ece(0.0123) == "0.012"
    assert fmt.pct(0.035) == "+3.5%" and fmt.with_ci(0.035, 0.031, 0.039) == "+3.5% [+3.1%, +3.9%]"
    assert fmt.n(412) == "n=412" and fmt.stake(0.012) == "1.2%"


def test_pasek_bramek_bledy_na_gorze_twarde_przed_ostrzezeniami():
    b = [dict(bramka="a", wynik="OK", twarda=True, info=""), dict(bramka="b", wynik="UWAGA", twarda=False, info=""),
         dict(bramka="c", wynik="BLAD", twarda=True, info=""), dict(bramka="d", wynik="OK", twarda=False, info="")]
    assert [x["bramka"] for x in render.pasek_bramek(b)] == ["c", "a", "b", "d"]
