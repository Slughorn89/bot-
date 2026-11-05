"""Warstwa LLM: brak konfiguracji = brak komentarza, wymyslone liczby = odrzucenie, blad = raport bez komentarza."""
import requests

from typer.report import llm

PAYLOAD = {"data": "2026-11-05", "typy": [{"mecz": "A - B", "p": 0.54, "kurs": 2.1, "przewaga": 0.134}],
           "okna": {"30": {"n": 412, "ll": 0.9758, "ece": 0.004}}, "alarmy": [], "werdykt": "tylko typowanie"}


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.status_code)

    def json(self):
        return {"choices": [{"message": {"content": self.text}}]}


class _Sess:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc:
            raise self.exc
        return self.resp


def _env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://relay.example/v1/")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_bez_konfiguracji_nic_nie_wysyla(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = _Sess(_Resp("x"))
    assert llm.comment(PAYLOAD, session=s) is None and not s.calls


def test_komentarz_z_liczbami_z_danych_przechodzi(monkeypatch):
    _env(monkeypatch)
    s = _Sess(_Resp("Jeden typ: A - B, p 0.54 przy kursie 2.10, przewaga +13.4%. Okno 30 dni: n 412, ECE 0.004."))
    out = llm.comment(PAYLOAD, session=s)
    assert out and "412" in out
    url, kw = s.calls[0]
    assert url == "https://relay.example/v1/chat/completions"
    assert "sk-test" not in kw["json"]["messages"][1]["content"]   # klucz tylko w naglowku


def test_wymyslona_liczba_odrzuca_komentarz(monkeypatch):
    _env(monkeypatch)
    s = _Sess(_Resp("Model ma 87% skutecznosci i przewage 0.54."))
    assert llm.comment(PAYLOAD, session=s) is None


def test_blad_serwisu_nie_wywraca_raportu(monkeypatch):
    _env(monkeypatch)
    assert llm.comment(PAYLOAD, session=_Sess(exc=requests.ConnectionError())) is None
    assert llm.comment(PAYLOAD, session=_Sess(_Resp("x", status=500))) is None
