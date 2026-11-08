"""Modul 1: rdzen warstwy danych (limit, retry z backoffem, cache, licencje, zapis) i adaptery."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from tests.samples import payloads
from typer.ingest.core import adapter as A
from typer.ingest.core.http import HttpClient, QuotaExhausted, SourceUnavailable
from typer.ingest.core.ratelimit import TokenBucket
from typer.ingest.core.records import MatchEvent, RefereeAssignment, TeamMatchStats
from typer.ingest.schema import ContractError

UTC = timezone.utc


# ---------------- limit zapytan ----------------
class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_token_bucket_trzyma_limit_na_minute():
    c = FakeClock()
    b = TokenBucket(10, 60, clock=c, sleep=c.sleep)
    for _ in range(10):
        assert b.acquire() == 0.0  # pojemnosc startowa
    w = b.acquire()
    assert w == pytest.approx(6.0)  # 10 na minute = 1 zeton co 6 s
    c.t += 60
    assert b.acquire() == 0.0  # po minucie zetony wracaja


# ---------------- klient HTTP ----------------
class FakeResp:
    def __init__(self, status, content=b"ok", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeSession:
    def __init__(self, seq):
        self.seq, self.calls = list(seq), 0

    def request(self, method, url, **kw):
        self.calls += 1
        x = self.seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


def _client(tmp_path, seq, **kw):
    sleeps = []
    c = HttpClient("test", session=FakeSession(seq), raw_dir=tmp_path, sleep=sleeps.append, jitter=0.1, **kw)
    return c, sleeps


def test_backoff_wykladniczy_z_rozrzutem(tmp_path):
    c, sleeps = _client(tmp_path, [FakeResp(500), FakeResp(502), requests.ConnectionError("x"), FakeResp(200, b"dane")])
    r = c.get("http://x", "a.bin")
    assert r.content == b"dane" and not r.from_cache
    assert len(sleeps) == 3
    for s, base in zip(sleeps, (2, 4, 8)):
        assert base * 0.9 <= s <= base * 1.1


def test_429_z_retry_after_czeka_tyle_ile_kaze_zrodlo(tmp_path):
    c, sleeps = _client(tmp_path, [FakeResp(429, headers={"Retry-After": "30"}), FakeResp(200)])
    c.get("http://x", "b.bin")
    assert sleeps and sleeps[0] >= 30


def test_bledy_trwale_bez_ponawiania(tmp_path):
    c, sleeps = _client(tmp_path, [FakeResp(404)])
    with pytest.raises(SourceUnavailable, match="404"):
        c.get("http://x", "c.bin")
    assert sleeps == [] and c.session.calls == 1


class JsonResp(FakeResp):
    def json(self):
        return json.loads(self.content)


def test_402_brak_tokenow_bez_ponawiania_i_bez_cache(tmp_path):
    body = b'{"error": {"code": "insufficient_tokens"}}'
    hdr = {"X-Tokens-Remaining": "0", "X-Tokens-Reset": "2026-12-01T00:00:00Z"}
    c, sleeps = _client(tmp_path, [JsonResp(402, body, hdr)])
    with pytest.raises(QuotaExhausted, match="insufficient_tokens.*zostalo 0"):
        c.get("http://x", "q.bin", max_age_hours=None)  # cache bezterminowy jak w archiwum zamkniec
    assert sleeps == [] and c.session.calls == 1
    assert not (tmp_path / "test" / "q.bin").exists()  # blad nie trafil do cache
    # po resecie tokenow kolejne wywolanie naprawde pyta zrodlo i dostaje dane
    c2, _ = _client(tmp_path, [FakeResp(200, b"kursy")])
    assert c2.get("http://x", "q.bin", max_age_hours=None).content == b"kursy"


@pytest.mark.parametrize("status", [400, 402, 405, 422])
def test_inne_4xx_trwale_i_bez_cache(tmp_path, status):
    c, sleeps = _client(tmp_path, [FakeResp(status, b"blad")])
    with pytest.raises(SourceUnavailable, match=str(status)):
        c.get("http://x", f"s{status}.bin")
    assert sleeps == [] and c.session.calls == 1
    assert not (tmp_path / "test" / f"s{status}.bin").exists()


def test_408_ponawiany(tmp_path):
    c, sleeps = _client(tmp_path, [FakeResp(408), FakeResp(200, b"ok")])
    assert c.get("http://x", "t.bin").content == b"ok" and len(sleeps) == 1


def test_odmowa_proxy_bez_ponawiania_i_stary_cache(tmp_path):
    c, sleeps = _client(tmp_path, [requests.exceptions.ProxyError("403 CONNECT")])
    with pytest.raises(SourceUnavailable, match="proxy"):
        c.get("http://x", "d.bin")
    assert sleeps == []
    (tmp_path / "test").mkdir(exist_ok=True)
    (tmp_path / "test" / "e.bin").write_bytes(b"stare")
    c2, _ = _client(tmp_path, [requests.exceptions.ProxyError("403")])
    r = c2.get("http://x", "e.bin", max_age_hours=0)
    assert r.content == b"stare" and r.from_cache and "proxy" in c2.audit[-1]["status"]


def test_cache_bez_drugiego_zapytania_i_fetched_at_z_pierwszego_pobrania(tmp_path):
    c, _ = _client(tmp_path, [FakeResp(200, b"raz")])
    r1 = c.get("http://x", "f.bin")
    r2 = c.get("http://x", "f.bin")
    assert c.session.calls == 1 and r2.from_cache and r2.content == b"raz"
    assert abs((r2.fetched_at - r1.fetched_at).total_seconds()) < 5  # mtime, nie "teraz"
    assert [a["status"] for a in c.audit] == ["http 200", "cache"]


def test_limiter_uzywany_przy_kazdym_zapytaniu(tmp_path):
    clock = FakeClock()
    lim = TokenBucket(1, 60, clock=clock, sleep=clock.sleep)
    c, _ = _client(tmp_path, [FakeResp(200), FakeResp(200)], limiter=lim)
    c.get("http://x", "g.bin", max_age_hours=0)
    c.get("http://x", "h.bin", max_age_hours=0)
    assert clock.slept and clock.slept[0] == pytest.approx(60)


# ---------------- licencje i wylaczone zrodla ----------------
def test_zrodlo_niekomercyjne_blokuje_sie_przy_uzyciu_komercyjnym(monkeypatch):
    reg = A.load_all()
    monkeypatch.setattr(A, "license_mode", lambda: "komercyjne")
    with pytest.raises(A.LicenseError):
        reg["tennis_mcp"]().check_license()
    reg["xgabora"]().check_license()  # licencja bez ograniczen: OK


def test_betfair_domyslnie_wylaczony():
    with pytest.raises(A.AdapterDisabled):
        A.load_all()["betfair"]().records()


# ---------------- kontrakty nowych adapterow ----------------
@pytest.mark.parametrize("name,psuj", [
    ("api_football", lambda b: b"{}"),
    ("telegram", lambda b: json.dumps({"channel": "x", "messages": [{"id": 1}]}).encode()),
    ("betfair", lambda b: b'{"op": "mcm", "mc": []}'),
    ("open_meteo", lambda b: json.dumps({"latitude": 1, "longitude": 1, "hourly": {"time": ["2024-01-01T00:00"]}}).encode()),
    ("tennis_mcp", lambda b: b"match_id,Pt\nx,1\n"),
])
def test_pole_zniklo_to_blad_kontraktu(name, psuj):
    a = A.load_all()[name]()
    p = payloads(name)[0]
    p.content = psuj(p.content)
    with pytest.raises(ContractError):
        a.parse(p)


# ---------------- zapis do bazy ----------------
def test_zapis_rekordow_idempotentny_z_available_at(tmp_engine):
    from typer.ingest.core.store import store_records
    from typer.store import db
    a = A.load_all()["api_football"]()
    recs = [r for p in payloads("api_football") for r in a.parse(p)]
    store_records(tmp_engine, recs)
    store_records(tmp_engine, recs)
    n = db.read_df(tmp_engine, "SELECT count(*) AS n, min(available_at) AS a FROM team_match_stats")
    assert n["n"][0] == 2 and n["a"][0] is not None
    ev = db.read_df(tmp_engine, "SELECT type FROM match_events ORDER BY minute")
    assert list(ev["type"]) == ["goal", "penalty_scored", "yellow", "second_yellow"]


# ---------------- sedziowie "as of" ----------------
def _ref_data():
    def ko(d):
        return datetime(2024, 8, d, 14, tzinfo=UTC)
    base = dict(source="t", league="E0", home="A", away="B", fetched_at=datetime(2025, 1, 1, tzinfo=UTC))
    asg, st, ev = [], [], []
    for i, (d, y) in enumerate(((3, 2), (10, 6), (17, 4))):
        k = dict(base, kickoff_utc=ko(d))
        asg.append(RefereeAssignment(**k, source_key=f"r{i}", available_at=ko(d) - timedelta(days=1), referee="Sedzia X"))
        for side in ("home", "away"):
            st.append(TeamMatchStats(**k, source_key=f"s{i}{side}", available_at=ko(d) + timedelta(hours=2, minutes=15),
                                     team=side, side=side, yellow=y // 2, fouls=10, red=0))
        if d == 10:
            ev.append(MatchEvent(**k, source_key=f"e{i}", available_at=ko(d) + timedelta(hours=2, minutes=15),
                                 minute=40, type="penalty_scored", team="A"))
    return asg, st, ev


def test_historia_sedziego_tylko_z_przeszlosci():
    from typer.features.referees import referee_history
    asg, st, ev = _ref_data()
    h = referee_history(asg, st, ev, as_of=datetime(2024, 8, 12, tzinfo=UTC))
    assert h.loc[0, "mecze"] == 2 and h.loc[0, "zolte_na_mecz"] == pytest.approx(4.0)
    assert h.loc[0, "karne_na_mecz"] == pytest.approx(0.5)
    # w trakcie meczu z 17.08 jego dane nie sa jeszcze dostepne
    h2 = referee_history(asg, st, ev, as_of=datetime(2024, 8, 17, 15, tzinfo=UTC))
    assert h2.loc[0, "mecze"] == 2


def test_historia_sedziego_podroz_w_czasie():
    from typer.features.referees import referee_history
    asg, st, ev = _ref_data()
    cut = datetime(2024, 8, 12, tzinfo=UTC)
    a = referee_history(asg, st, ev, as_of=cut)
    st2 = [s.model_copy(update=dict(yellow=9)) if s.kickoff_utc > cut else s for s in st]
    b = referee_history(asg, st2, ev, as_of=cut)
    assert a.equals(b)


# ---------------- Telegram i pogoda ----------------
def test_telegram_wersje_i_tagi():
    a = A.load_all()["telegram"]()
    recs = a.parse(payloads("telegram")[0])
    by_id = {r.message_id: r for r in recs}
    assert by_id[102].version == 2 and by_id[102].available_at == by_id[102].edited_at
    assert by_id[101].url == "https://t.me/testowy_kanal_newsowy/101"
    assert "sklad" in by_id[101].tags and "kontuzja" in by_id[102].tags and by_id[103].tags == ["trener"]


def test_pogoda_prognoza_tylko_na_przyszlosc_a_archiwalna_z_wyprzedzeniem():
    a = A.load_all()["open_meteo"]()
    p_fc, p_prev, p_obs = payloads("open_meteo")
    fc = a.parse(p_fc)
    assert all(r.valid_time >= p_fc.fetched_at and r.kind == "forecast" for r in fc) and len(fc) == 3
    prev = a.parse(p_prev)
    assert all(r.valid_time - r.available_at == timedelta(hours=18) for r in prev)
    obs = a.parse(p_obs)
    assert all(r.kind == "observed" and r.available_at > r.valid_time for r in obs)


def test_mcp_uszkodzony_wiersz_pominiety_jawnie_a_reszta_dziala():
    """Regresja: prawdziwy plik MCP mial wiersz z przesunietymi kolumnami (Date='RR')."""
    a = A.load_all()["tennis_mcp"]()
    p = payloads("tennis_mcp")[0]
    p.content += b"20240915-M-Davis_Cup-RR-A_B-C_D,A B,C D,R,R,RR,15:15,Arena,,,,,,,\n"
    recs = a.parse(p)
    assert len(recs) == 2 and a.skipped == ["20240915-M-Davis_Cup-RR-A_B-C_D"]
