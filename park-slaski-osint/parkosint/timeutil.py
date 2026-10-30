"""Okno czasowe i konwersje stref. Wszystko wewnątrz kodu trzymamy jako aware datetime."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")

PL_MONTHS_GENITIVE = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "wrzesnia", "pazdziernika", "listopada", "grudnia",
]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    margin: timedelta = timedelta(minutes=30)

    @classmethod
    def from_local(cls, day: date, start: time, end: time, margin_min: int = 30, tz: ZoneInfo = TZ) -> "Window":
        return cls(
            start=datetime.combine(day, start, tzinfo=tz),
            end=datetime.combine(day, end, tzinfo=tz),
            margin=timedelta(minutes=margin_min),
        )

    @property
    def day(self) -> date:
        return self.start.astimezone(TZ).date()

    @property
    def query_start(self) -> datetime:
        return self.start - self.margin

    @property
    def query_end(self) -> datetime:
        return self.end + self.margin

    def classify(self, dt: datetime | None) -> str | None:
        """'in' = w oknie, 'margin' = tylko w marginesie, 'out' = poza, None = brak czasu."""
        if dt is None:
            return None
        if self.start <= dt <= self.end:
            return "in"
        if self.query_start <= dt <= self.query_end:
            return "margin"
        return "out"

    def classify_range(self, start: datetime, end: datetime | None) -> str:
        """Dla nagrań z czasem trwania (np. transmisja live): liczy się nakładanie z oknem."""
        end = end or start
        if start <= self.end and end >= self.start:
            return "in"
        if start <= self.query_end and end >= self.query_start:
            return "margin"
        return "out"

    def label(self) -> str:
        s, e = self.start.astimezone(TZ), self.end.astimezone(TZ)
        return f"{s:%d.%m.%Y}, {s:%H:%M} do {e:%H:%M} ({s.tzname()})"


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_naive_str(dt: datetime) -> str:
    """Format MySQL datetime w czasie lokalnym (tak Flickr trzyma date_taken)."""
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")


_NAIVE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)


def parse_local(value: str, offset: str | None = None) -> datetime | None:
    """Parsuje czas bez strefy (EXIF, Flickr). Brak offsetu = zakładamy Europe/Warsaw."""
    value = (value or "").strip()
    if not value:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    value = value[:19]
    for fmt in _NAIVE_FORMATS:
        try:
            naive = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if offset and re.match(r"^[+-]\d{2}:\d{2}$", offset.strip()):
            sign = 1 if offset.strip()[0] == "+" else -1
            hh, mm = offset.strip()[1:].split(":")
            return naive.replace(tzinfo=timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
        return naive.replace(tzinfo=TZ)
    return None


def parse_date_only(value: str) -> date | None:
    m = re.search(r"(\d{4})[-:](\d{2})[-:](\d{2})", value or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def from_epoch_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S")
