"""Wysylka prosto do Telegrama przez Bot API (bez n8n).

W .env: TELEGRAM_BOT_TOKEN (od @BotFather) i TELEGRAM_CHAT_ID (ustawia `cli.py telegram-setup`).
Wiadomosci ida jako zwykly tekst (bez parse_mode), wiec nazwy druzyn ze znakami * _ [ niczego nie psuja.
Blad Telegrama nigdy nie przerywa typowania: wolajacy dostaje komunikat, a alarm trafia do live/alerts.json."""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

from typer import config

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def token() -> str | None:
    return (config.env("TELEGRAM_BOT_TOKEN") or "").strip() or None


def chat_id() -> str | None:
    return (config.env("TELEGRAM_CHAT_ID") or "").strip() or None


def configured() -> bool:
    return bool(token() and chat_id())


def _call(method: str, tok: str, retries: int = 3, **params) -> dict:
    url = API.format(token=tok, method=method)
    for attempt in range(retries):
        try:
            r = requests.post(url, json=params, timeout=30)
        except requests.RequestException as e:  # brak sieci: krotka przerwa i ponowienie
            if attempt == retries - 1:
                raise TelegramError(f"brak polaczenia z Telegramem: {type(e).__name__}") from None
            time.sleep(2 * (attempt + 1))
            continue
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 429 and attempt < retries - 1:  # limit wysylki: Telegram mowi, ile czekac
            time.sleep(min(int((data.get("parameters") or {}).get("retry_after", 3)), 30))
            continue
        if not data.get("ok"):
            desc = data.get("description") or f"HTTP {r.status_code}"
            if r.status_code == 401:
                desc += " (zly TELEGRAM_BOT_TOKEN)"
            elif r.status_code in (400, 403) and method == "sendMessage":
                desc += " (sprawdz TELEGRAM_CHAT_ID i czy napisales do bota /start)"
            raise TelegramError(desc)
        return data
    raise TelegramError("Telegram nie odpowiada")  # pragma: no cover


def send_messages(messages: list[str], tok: str | None = None, chat: str | None = None) -> int:
    """Wysyla po kolei; zwraca liczbe wyslanych. Puste wiadomosci pomija."""
    tok, chat = tok or token(), chat or chat_id()
    if not (tok and chat):
        raise TelegramError("brak TELEGRAM_BOT_TOKEN albo TELEGRAM_CHAT_ID w .env")
    n = 0
    for m in messages:
        if not m or not m.strip():
            continue
        _call("sendMessage", tok, chat_id=chat, text=m, disable_web_page_preview=True)
        n += 1
    return n


def find_chat_id(tok: str) -> tuple[str, str] | None:
    """Ostatni czat prywatny, z ktorego ktos napisal do bota: (chat_id, imie)."""
    data = _call("getUpdates", tok)
    for u in reversed(data.get("result", [])):
        msg = u.get("message") or u.get("edited_message") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            name = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
            return str(chat["id"]), name
    return None


def set_env_value(path: Path, key: str, value: str) -> None:
    """Ustawia KEY=value w .env: podmienia istniejaca linie albo dopisuje na koncu. Reszty nie rusza."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    if pat.search(text):
        text = pat.sub(line, text, count=1)
    else:
        text = text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    path.write_text(text, encoding="utf-8")


def setup(env_path: Path | None = None) -> str:
    """Kreator: czyta token z .env, znajduje chat_id z wiadomosci do bota, zapisuje go i wysyla test."""
    env_path = env_path or config.ROOT / ".env"
    tok = token()
    if not tok:
        return ("Brak TELEGRAM_BOT_TOKEN w pliku .env. Otworz .env w Notatniku, dopisz linie\n"
                "TELEGRAM_BOT_TOKEN=token_od_BotFather i zapisz plik. Potem uruchom to polecenie jeszcze raz.")
    me = _call("getMe", tok)["result"]
    found = find_chat_id(tok)
    if not found:
        return (f"Token dziala (bot @{me.get('username')}), ale bot nie dostal jeszcze zadnej wiadomosci.\n"
                f"Otworz w Telegramie https://t.me/{me.get('username')} , nacisnij Start albo napisz cokolwiek,\n"
                "i uruchom to polecenie jeszcze raz.")
    cid, name = found
    set_env_value(env_path, "TELEGRAM_CHAT_ID", cid)
    send_messages([f"Typer polaczony z Telegramem. Czesc {name}! Tu beda przychodzic typy i poranny raport."],
                  tok=tok, chat=cid)
    return f"Gotowe: bot @{me.get('username')}, chat_id zapisany w .env, wyslalem wiadomosc testowa."
