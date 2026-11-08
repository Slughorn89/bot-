"""Wysylka na Telegram przez Bot API: bez sieci (requests.post podmieniony)."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from typer.report import daily as rep
from typer.report import telegram


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


@pytest.fixture
def calls(monkeypatch):
    sent = []
    queue = []

    def post(url, json=None, timeout=None):
        sent.append((url, json))
        return queue.pop(0) if queue else FakeResp(200, {"ok": True, "result": {}})

    monkeypatch.setattr(telegram.requests, "post", post)
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    return sent, queue


def test_wysyla_kazda_wiadomosc_jako_zwykly_tekst(calls):
    sent, _ = calls
    assert telegram.send_messages(["a", "", "b"]) == 2
    assert [j["text"] for _, j in sent] == ["a", "b"]
    assert all(j["chat_id"] == "555" and "parse_mode" not in j for _, j in sent)
    assert sent[0][0] == "https://api.telegram.org/bot123:abc/sendMessage"


def test_limit_429_czeka_i_ponawia(calls):
    sent, queue = calls
    queue += [FakeResp(429, {"ok": False, "parameters": {"retry_after": 1}}), FakeResp(200, {"ok": True})]
    assert telegram.send_messages(["x"]) == 1
    assert len(sent) == 2


def test_zly_token_daje_czytelny_blad(calls):
    _, queue = calls
    queue.append(FakeResp(401, {"ok": False, "description": "Unauthorized"}))
    with pytest.raises(telegram.TelegramError, match="TELEGRAM_BOT_TOKEN"):
        telegram.send_messages(["x"])


def test_bez_konfiguracji_nic_nie_wysyla(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not telegram.configured()
    assert rep.notify_bets(None, pd.DataFrame([{"prediction_id": 1}])) == ""


def test_setup_zapisuje_chat_id_w_env(calls, tmp_path, monkeypatch):
    sent, queue = calls
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    env = tmp_path / ".env"
    env.write_text("ODDSRELAY_KEY=tajne\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")
    queue += [FakeResp(200, {"ok": True, "result": {"username": "moj_typer_bot"}}),
              FakeResp(200, {"ok": True, "result": [{"message": {"chat": {"id": 987, "first_name": "Ola"}}}]}),
              FakeResp(200, {"ok": True})]
    out = telegram.setup(env)
    assert "Gotowe" in out
    assert env.read_text(encoding="utf-8") == "ODDSRELAY_KEY=tajne\nTELEGRAM_CHAT_ID=987\n"
    assert sent[-1][1]["chat_id"] == "987"


def test_setup_bez_wiadomosci_do_bota_mowi_co_zrobic(calls, tmp_path):
    _, queue = calls
    queue += [FakeResp(200, {"ok": True, "result": {"username": "moj_typer_bot"}}),
              FakeResp(200, {"ok": True, "result": []})]
    out = telegram.setup(tmp_path / ".env")
    assert "t.me/moj_typer_bot" in out and not (tmp_path / ".env").exists()


def test_set_env_value_dopisuje_brakujacy_klucz(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")
    telegram.set_env_value(env, "TELEGRAM_CHAT_ID", "5")
    assert env.read_text(encoding="utf-8") == "A=1\nTELEGRAM_CHAT_ID=5\n"


def test_nowe_typy_trafiaja_na_telegram(calls, tmp_engine):
    from typer.store import db
    sent, _ = calls
    ko = datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc)
    db.append(tmp_engine, db.events, [dict(event_id="e1", sport="football", league="E0", kickoff_utc=ko,
                                           home="Arsenal", away="Chelsea")])
    pid = db.append(tmp_engine, db.predictions, [dict(event_id="e1", market="1x2", selection="H", p_model=0.5,
                                                      model_version="t", kickoff_utc=ko)])[0]
    bets = pd.DataFrame([dict(prediction_id=pid, event_id="e1", market="1x2", selection="H", odds=2.2,
                              edge=0.1, stake_frac=0.01, paper=True)])
    assert rep.notify_bets(tmp_engine, bets) == "Telegram: wyslano 1 nowych typow"
    text = sent[0][1]["text"]
    assert "Nowy typ" in text and "Arsenal - Chelsea" in text and "20:45" in text


def test_blad_telegrama_nie_przerywa_typowania(calls, tmp_engine, monkeypatch):
    _, queue = calls
    monkeypatch.setattr(rep, "bet_messages", lambda eng, b: ["x"])
    alerts = []
    monkeypatch.setattr("typer.pipeline.daily.alert", alerts.append)
    queue.append(FakeResp(400, {"ok": False, "description": "Bad Request: chat not found"}))
    out = rep.notify_bets(tmp_engine, pd.DataFrame([{"prediction_id": 1}]))
    assert out.startswith("Telegram: blad") and "chat not found" in alerts[0]
