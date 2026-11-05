"""Opcjonalny komentarz LLM do raportu dziennego (endpoint zgodny z OpenAI, np. z All API Hub).

Jak podlaczyc (All API Hub lub dowolny serwis zgodny z OpenAI):
  1. W rozszerzeniu All API Hub wybierz konto i skopiuj "Base URL" oraz klucz API.
  2. Wpisz je do .env (NIGDY do repo):  LLM_BASE_URL=https://.../v1  LLM_API_KEY=...  LLM_MODEL=...
  3. Raport dzienny dopisze sekcje "Komentarz" (python cli.py report).

Zasady bezpieczenstwa i uczciwosci (sekcja 1 i 13 skilla: zadnych wymyslonych liczb):
  * LLM dostaje TYLKO payload raportu (liczby juz policzone przez evaluate.py i baze), bez kluczy,
    bez danych osobowych, bez historii kont.
  * Kazda liczba w odpowiedzi LLM musi wystepowac w payloadzie (straznik `numbers_ok`). Jesli LLM
    wymysli liczbe, komentarz jest odrzucany, a raport idzie bez niego.
  * Brak konfiguracji, timeout albo blad serwisu = raport bez komentarza, nigdy awaria cyklu dziennego.
  * Komentarz niczego nie decyduje: typy, stawki i werdykt licza sie bez LLM.
Uwaga: serwisy-posrednicy (relay) czesto odsprzedaja dostep do modeli wbrew regulaminom dostawcow.
Uzywaj klucza o niskim limicie wydatkow i tylko do tego komentarza.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from typer import config

log = logging.getLogger("typer.report.llm")

SYSTEM = (
    "Jestes analitykiem typera sportowego. Piszesz po polsku, krotko (3-5 zdan), rzeczowo, bez myslnikow. "
    "Opisujesz WYLACZNIE to, co jest w danych JSON: werdykt, typy, alarmy, wnioski. "
    "Nie podajesz zadnej liczby, ktorej nie ma w danych. Nie obiecujesz zysku, nie zachecasz do gry, "
    "nie dajesz 'pewniakow'. Gdy brak typow lub danych, mowisz to wprost."
)
NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def configured() -> bool:
    return bool(config.env("LLM_BASE_URL") and config.env("LLM_API_KEY") and config.env("LLM_MODEL"))


def _numbers_in(obj) -> set[float]:
    out: set[float] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, bool):
            return
        elif isinstance(x, (int, float)):
            out.add(round(float(x), 6))
        elif isinstance(x, str):
            for m in NUM.findall(x):
                out.add(round(float(m.replace(",", ".")), 6))
    walk(obj)
    return out


def numbers_ok(text: str, payload: dict, tol: float = 0.0051) -> tuple[bool, list[str]]:
    """Kazda liczba z tekstu musi byc w payloadzie: dokladnie, po zaokragleniu albo jako procent ulamka."""
    known = _numbers_in(payload)
    bad = []
    for m in NUM.findall(text):
        v = float(m.replace(",", ".").lstrip("+"))
        cands = {abs(v), abs(v) / 100}
        if any(abs(c - abs(k)) <= max(tol, abs(k) * 0.005) for c in cands for k in known):
            continue
        bad.append(m)
    return not bad, bad


def comment(payload: dict, *, session: requests.Session | None = None) -> str | None:
    """Komentarz LLM albo None (brak konfiguracji, blad, odrzucony przez straznika liczb)."""
    if not configured():
        return None
    data = {k: v for k, v in payload.items() if k != "tekst"}
    body = {
        "model": config.env("LLM_MODEL"),
        "temperature": 0.2,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Dane raportu (JSON):\n" + json.dumps(data, ensure_ascii=False, default=str)},
        ],
    }
    url = config.env("LLM_BASE_URL").rstrip("/") + "/chat/completions"
    try:
        r = (session or requests).post(url, json=body, timeout=45,
                                       headers={"Authorization": f"Bearer {config.env('LLM_API_KEY')}"})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001 - komentarz jest opcjonalny, raport musi wyjsc
        log.warning("LLM niedostepny (%s): raport bez komentarza", type(e).__name__)
        return None
    ok, bad = numbers_ok(text, data)
    if not ok:
        log.warning("komentarz LLM odrzucony: liczby spoza danych %s", bad[:5])
        return None
    return text.replace("—", ",").replace("–", ",")
