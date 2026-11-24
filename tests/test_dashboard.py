import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard  # noqa: E402


class _FakeExchange:
    def __init__(self):
        self.calls = []

    def fetch_ohlcv(self, pair, timeframe, limit):
        self.calls.append((pair, timeframe, limit))
        idx = pd.date_range("2024-01-01", periods=3, freq="h")
        return pd.DataFrame({"open": [1.0, 2.0, 3.0], "high": [2.0, 3.0, 4.0], "low": [0.5, 1.5, 2.5],
                             "close": [2.0, 3.0, 3.5], "volume": [10.0, 11.0, 12.0]}, index=idx)


def _client(monkeypatch):
    fake = _FakeExchange()
    monkeypatch.setattr(dashboard, "_get_exchange", lambda: fake)
    return dashboard.app.test_client(), fake


def test_index_serves_dashboard_without_cache(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/")
    assert r.status_code == 200
    assert "Trading Bot" in r.get_data(as_text=True)
    assert r.headers["Cache-Control"] == "no-cache"


def test_candles_rejects_non_integer_limit(monkeypatch):
    client, fake = _client(monkeypatch)
    r = client.get("/api/candles?limit=abc")
    assert r.status_code == 400
    assert "error" in r.get_json()
    assert fake.calls == []


def test_candles_limit_is_clamped(monkeypatch):
    client, fake = _client(monkeypatch)
    assert client.get("/api/candles?limit=999999").status_code == 200
    assert client.get("/api/candles?limit=-5").status_code == 200
    assert [c[2] for c in fake.calls] == [dashboard.MAX_CANDLES, 1]


def test_candles_payload_shape(monkeypatch):
    client, _ = _client(monkeypatch)
    data = client.get("/api/candles?limit=3").get_json()
    assert len(data["candles"]) == 3
    assert set(data["candles"][0]) == {"time", "open", "high", "low", "close", "volume"}
    assert data["candles"][0]["time"] < data["candles"][1]["time"]


def test_health_reports_no_bot_thread(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(dashboard, "_bot_thread", None)
    assert client.get("/api/health").get_json() == {"status": "ok", "bot_running": False}


def test_chart_library_is_pinned_with_integrity():
    html_path = os.path.join(os.path.dirname(dashboard.__file__), "static", "dashboard.html")
    html = open(html_path, encoding="utf-8").read()
    assert "lightweight-charts@4.2.0" in html
    assert 'integrity="sha384-' in html
