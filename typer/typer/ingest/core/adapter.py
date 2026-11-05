"""Klasa bazowa adaptera i rejestr. Adapter = fetch (surowe bajty, z cache/limitem/backoffem)
+ parse (bajty -> rekordy pydantic z available_at). Parsowanie jest czyste i deterministyczne,
wiec testy kontraktu i test available_at dzialaja na zapisanych probkach, bez sieci.

Licencje: zrodla niekomercyjne (np. Match Charting Project CC BY-NC-SA, darmowe Open-Meteo)
dzialaja, dopoki config/sources.yaml: licencja_uzycia != "komercyjne". Przy "nieustalone"
(domyslnie) ostrzegamy raz na przebieg.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from typer import config
from typer.ingest.core.http import HttpClient
from typer.ingest.core.ratelimit import limiter_for
from typer.ingest.core.records import BaseRecord

log = logging.getLogger("typer.ingest.adapter")
REGISTRY: dict[str, type["Adapter"]] = {}
_WARNED: set[str] = set()


class LicenseError(RuntimeError):
    """Uzycie zrodla niezgodne z jego licencja."""


class AdapterDisabled(RuntimeError):
    """Adapter wylaczony w konfiguracji (np. Betfair bez potwierdzonego legalnego dostepu)."""


@dataclass
class RawPayload:
    """Surowa odpowiedz zrodla + kontekst potrzebny do parsowania (np. start meczu, status)."""
    name: str
    content: bytes
    fetched_at: datetime
    ctx: dict = field(default_factory=dict)


def register(cls: type["Adapter"]) -> type["Adapter"]:
    if not getattr(cls, "name", None):
        raise ValueError("adapter bez nazwy")
    REGISTRY[cls.name] = cls
    return cls


def license_mode() -> str:
    return str(config.sources().get("licencja_uzycia", "nieustalone"))


class Adapter(ABC):
    name: ClassVar[str] = ""
    license: ClassVar[str] = ""
    non_commercial: ClassVar[bool] = False
    enabled_by_default: ClassVar[bool] = True
    record_types: ClassVar[tuple[type[BaseRecord], ...]] = ()

    def __init__(self, client: HttpClient | None = None):
        self.client = client or HttpClient(self.name, limiter=limiter_for(self.name))

    # ---- kontrola uzycia ----
    def check_license(self) -> None:
        mode = license_mode()
        if self.non_commercial and mode == "komercyjne":
            raise LicenseError(f"{self.name}: licencja '{self.license}' zabrania uzycia komercyjnego")
        if self.non_commercial and mode != "prywatne" and self.name not in _WARNED:
            _WARNED.add(self.name)
            log.warning("%s: licencja %s tylko do uzytku niekomercyjnego; licencja_uzycia=%s",
                        self.name, self.license, mode)

    def check_enabled(self) -> None:
        cfg = config.sources().get(self.name) or {}
        if not cfg.get("wlaczony", self.enabled_by_default):
            raise AdapterDisabled(f"{self.name} wylaczony (config/sources.yaml: {self.name}.wlaczony)")

    # ---- interfejs ----
    @abstractmethod
    def fetch(self, **params) -> list[RawPayload]:
        """Pobiera surowe odpowiedzi (przez self.client: cache, limit, backoff)."""

    @abstractmethod
    def parse(self, payload: RawPayload) -> list[BaseRecord]:
        """Czyste parsowanie bajtow w rekordy. Brak pola wymaganego = ContractError, nie cisza."""

    def records(self, **params) -> list[BaseRecord]:
        self.check_enabled()
        self.check_license()
        out: list[BaseRecord] = []
        for p in self.fetch(**params):
            out.extend(self.validated(self.parse(p)))
        return out

    def validated(self, recs: list) -> list[BaseRecord]:
        """Twarda kontrola: kazdy rekord to model pydantic z available_at (walidacja juz przy tworzeniu)."""
        for r in recs:
            if not isinstance(r, BaseRecord):
                raise TypeError(f"{self.name}: parse zwrocil {type(r).__name__} zamiast rekordu")
            if self.record_types and not isinstance(r, self.record_types):
                raise TypeError(f"{self.name}: nieoczekiwany typ rekordu {type(r).__name__}")
            if getattr(r, "available_at", None) is None:
                raise ValueError(f"{self.name}: rekord bez available_at")
        return recs


def load_all() -> dict[str, type[Adapter]]:
    """Import wszystkich adapterow (rejestracja przy imporcie)."""
    import typer.ingest.adapters  # noqa: F401
    return dict(REGISTRY)
