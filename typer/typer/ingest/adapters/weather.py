"""Adapter: Open-Meteo (pogoda). Darmowe API tylko do uzytku niekomercyjnego (dane CC BY 4.0).

Trzy tryby, trzy reguly available_at:
  forecast       prognoza pobrana teraz: available_at = fetched_at, tylko godziny w przyszlosci
                 (godziny juz minione w odpowiedzi to analiza modelu, czyli prawie obserwacja)
  previous_runs  prognozy archiwalne sprzed N dni (zmienne *_previous_dayN): available_at =
                 czas waznosci - N*24h + 6h (zapas na publikacje przebiegu modelu), szacunek.
                 Tylko tego trybu wolno uzywac w backteście jako cechy przedmeczowej.
  archive        obserwacje (reanaliza): available_at = czas waznosci + 1h. Do cech przedmeczowych
                 NIE wolno, walidator i test pilnuja, zeby nie udawaly prognozy.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from typer import config
from typer.ingest.core.adapter import Adapter, RawPayload, register
from typer.ingest.core.records import WeatherRecord
from typer.ingest.schema import ContractError

VARS = ["temperature_2m", "precipitation", "wind_speed_10m", "relative_humidity_2m"]
PUBLISH_DELAY = timedelta(hours=6)
URLS = {"forecast": "https://api.open-meteo.com/v1/forecast",
        "previous_runs": "https://previous-runs-api.open-meteo.com/v1/forecast",
        "archive": "https://archive-api.open-meteo.com/v1/archive",
        "geocoding": "https://geocoding-api.open-meteo.com/v1/search"}


@register
class OpenMeteo(Adapter):
    name = "open_meteo"
    license = "Open-Meteo: darmowe API niekomercyjnie, dane CC BY 4.0"
    non_commercial = True
    record_types = (WeatherRecord,)

    def fetch(self, latitude: float, longitude: float, mode: str = "forecast", start_date: str | None = None,
              end_date: str | None = None, previous_day: int = 1, event_id: str | None = None) -> list[RawPayload]:
        if mode not in ("forecast", "previous_runs", "archive"):
            raise ValueError(mode)
        hourly = VARS if mode != "previous_runs" else [f"{v}_previous_day{previous_day}" for v in VARS]
        params = dict(latitude=latitude, longitude=longitude, hourly=",".join(hourly), timezone="UTC",
                      wind_speed_unit="kmh")
        if start_date:
            params.update(start_date=start_date, end_date=end_date or start_date)
        name = f"{mode}_{latitude:.3f}_{longitude:.3f}_{start_date or 'now'}_{previous_day}.json"
        r = self.client.get(URLS[mode], name, params=params, max_age_hours=1 if mode == "forecast" else None)
        return [RawPayload(name, r.content, r.fetched_at, dict(mode=mode, previous_day=previous_day,
                                                               event_id=event_id))]

    def parse(self, payload: RawPayload) -> list:
        body = json.loads(payload.content)
        if body.get("error"):
            raise ContractError(f"Open-Meteo: {body.get('reason')}")
        h = body.get("hourly")
        if not h or "time" not in h:
            raise ContractError("Open-Meteo: brak pola hourly.time")
        mode, n = payload.ctx.get("mode", "forecast"), int(payload.ctx.get("previous_day", 1))
        suffix = f"_previous_day{n}" if mode == "previous_runs" else ""
        for v in VARS:
            if v + suffix not in h:
                raise ContractError(f"Open-Meteo: brak zmiennej {v + suffix}")
        lat, lon = float(body["latitude"]), float(body["longitude"])
        fetched = payload.fetched_at
        out = []
        for i, t in enumerate(h["time"]):
            vt = pd.Timestamp(t).tz_localize("UTC").to_pydatetime()
            vals = {v: h[v + suffix][i] for v in VARS}
            if all(x is None for x in vals.values()):
                continue
            if mode == "forecast":
                if vt < fetched:
                    continue
                at, est, kind, lead = fetched, False, "forecast", (vt - fetched).total_seconds() / 3600
            elif mode == "previous_runs":
                at, est, kind, lead = vt - timedelta(days=n) + PUBLISH_DELAY, True, "forecast", 24.0 * n - 6
                if at > fetched:
                    continue
            else:
                at, est, kind, lead = vt + timedelta(hours=1), True, "observed", None
                if at > fetched:
                    continue
            out.append(WeatherRecord(
                source=self.name, license=self.license, source_key=f"om:{mode}{n if suffix else ''}:{lat:.3f}:{lon:.3f}:{t}",
                available_at=at, available_at_estimated=est, fetched_at=fetched, latitude=lat, longitude=lon,
                valid_time=vt, kind=kind, lead_hours=lead, temperature_c=vals["temperature_2m"],
                precipitation_mm=vals["precipitation"], wind_kmh=vals["wind_speed_10m"],
                humidity_pct=vals["relative_humidity_2m"], event_id=payload.ctx.get("event_id")))
        return out

    def geocode(self, city: str, country: str | None = None) -> tuple[float, float] | None:
        """Wspolrzedne miasta stadionu (do tabeli venues). Brak trafienia = None, nie zgadujemy."""
        r = self.client.get(URLS["geocoding"], f"geo_{city.replace(' ', '_')}_{country or ''}.json",
                            params=dict(name=city, count=5, language="en", format="json"), max_age_hours=None)
        res = json.loads(r.content).get("results") or []
        if country:
            res = [x for x in res if (x.get("country_code") or "").upper() == country.upper()] or res
        return (float(res[0]["latitude"]), float(res[0]["longitude"])) if res else None
