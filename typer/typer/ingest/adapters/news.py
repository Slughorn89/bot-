"""Adapter: Telegram, tylko publiczne kanaly newsowe z bialej listy, przez oficjalne API klienta
(MTProto, biblioteka Telethon). Bot API nie czyta cudzych kanalow, a scrapowanie stron t.me
nie jest oficjalnym API, wiec go nie uzywamy.

Kazda wiadomosc ma znacznik zrodla (kanal, link t.me) i czasu. available_at = data publikacji z serwera
Telegrama; edycja = nowa wersja z data edycji (stary tekst zostaje w bazie). Wydobywanie skladow
i kontuzji z tekstu to osobny modul: tutaj tylko zapis i proste tagi slow kluczowych.

Wymaga w .env: TELEGRAM_API_ID, TELEGRAM_API_HASH (my.telegram.org) i jednorazowego logowania
(sesja w data/telegram.session). Kanaly: config/sources.yaml -> telegram.kanaly.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.http import SourceUnavailable
from typer.ingest.core.records import NewsMessage
from typer.ingest.schema import ContractError

TAGS = {
    "sklad": r"\b(sk[łl]ad|lineup|line-up|starting xi|xi\b|aufstellung|alineaci[oó]n|formazione)",
    "kontuzja": r"(kontuzj|uraz|injur|verletz|lesi[oó]n|infortun)",
    "zawieszenie": r"(zawiesz|pauzuj|suspend|gesperrt|sancion|squalific)",
    "trener": r"(trener|coach|manager|entrenador|allenatore)",
}
_RX = {k: re.compile(v, re.IGNORECASE) for k, v in TAGS.items()}


def tag(text: str) -> list[str]:
    return [k for k, rx in _RX.items() if rx.search(text or "")]


@register
class TelegramNews(Adapter):
    name = "telegram"
    license = "Telegram API ToS; tresci naleza do autorow kanalow (podajemy zrodlo)"
    record_types = (NewsMessage,)

    def fetch(self, channels: list[str] | None = None, since: datetime | None = None, limit: int = 200,
              client_factory=None) -> list[RawPayload]:
        channels = channels if channels is not None else (config.sources().get("telegram", {}).get("kanaly") or [])
        if not channels:
            return []
        client = (client_factory or _telethon_client)()
        out = []
        for ch in channels:
            msgs = client.messages(ch, since=since, limit=limit)  # lista slownikow, patrz _telethon_client
            raw = json.dumps(dict(channel=ch, messages=msgs), ensure_ascii=False, default=str).encode()
            fetched = datetime.now(timezone.utc)
            path = self.client.raw_dir / self.name / f"{ch}_{fetched:%Y%m%dT%H%M%S}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)  # surowa odpowiedz do cache, jak przy HTTP
            out.append(RawPayload(path.name, raw, fetched, dict(channel=ch)))
        return out

    def parse(self, payload: RawPayload) -> list:
        body = json.loads(payload.content)
        if "channel" not in body or "messages" not in body:
            raise ContractError("Telegram: brak pol channel/messages")
        ch = body["channel"]
        out = []
        for m in body["messages"]:
            missing = {"id", "date", "text"} - set(m)
            if missing:
                raise ContractError(f"Telegram: brak pol {sorted(missing)}")
            pub = pd.Timestamp(m["date"]).tz_convert("UTC").to_pydatetime()
            ed = pd.Timestamp(m["edit_date"]).tz_convert("UTC").to_pydatetime() if m.get("edit_date") else None
            version = int(m.get("version") or (2 if ed else 1))
            out.append(NewsMessage(
                source=self.name, license=self.license,
                source_key=f"tg:{ch}:{m['id']}:{(ed or pub):%Y%m%dT%H%M%S}",
                available_at=ed or pub, fetched_at=payload.fetched_at, channel=ch, message_id=int(m["id"]),
                version=version, text=m["text"] or "", url=f"https://t.me/{ch}/{m['id']}", published_at=pub,
                edited_at=ed, tags=tag(m["text"] or "")))
        return out


class _Telethon:
    def __init__(self):
        try:
            from telethon.errors import FloodWaitError
            from telethon.sync import TelegramClient
        except ImportError as e:  # pragma: no cover - zalezy od srodowiska
            raise SourceUnavailable("brak biblioteki telethon (pip install telethon)") from e
        api_id, api_hash = config.env("TELEGRAM_API_ID"), config.env("TELEGRAM_API_HASH")
        if not api_id or not api_hash:
            raise SourceUnavailable("brak TELEGRAM_API_ID / TELEGRAM_API_HASH w .env")
        self.FloodWait = FloodWaitError
        self.client = TelegramClient(str(config.DATA_DIR / "telegram"), int(api_id), api_hash)
        self.client.start()

    def messages(self, channel: str, since=None, limit: int = 200) -> list[dict]:  # pragma: no cover
        import time
        ent = self.client.get_entity(channel)
        if not getattr(ent, "broadcast", False) or not getattr(ent, "username", None):
            raise SourceUnavailable(f"{channel}: to nie jest publiczny kanal")
        for attempt in range(2):
            try:
                out = []
                for m in self.client.iter_messages(ent, limit=limit):
                    if since and m.date < since:
                        break
                    out.append(dict(id=m.id, date=m.date.isoformat(), text=m.message or "",
                                    edit_date=m.edit_date.isoformat() if m.edit_date else None))
                return out
            except self.FloodWait as e:  # Telegram mowi, ile czekac: czekamy dokladnie tyle
                time.sleep(e.seconds + 1)
        raise SourceUnavailable(f"{channel}: FloodWait dwa razy z rzedu")


def _telethon_client():  # pragma: no cover
    return _Telethon()
