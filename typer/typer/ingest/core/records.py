"""Rekordy warstwy danych (pydantic v2). Kazdy rekord MA znaczniki czasu:

  available_at  najwczesniejsza chwila, w ktorej informacja byla publicznie dostepna (UTC).
                Wedlug niej backtest filtruje dane "as of", wiec to ona chroni przed wyciekiem.
  fetched_at    kiedy MY ja pobralismy (UTC). Na zywo ceche wolno zbudowac tylko z rekordu,
                ktory faktycznie mielismy przed typem.

Niezmiennik: available_at <= fetched_at (nie da sie pobrac informacji, zanim sie pojawila).
Rozjazd zegarow zrodla i naszego do CLOCK_SKEW przycinamy, wiekszy jest bledem.
Kazdy rodzaj rekordu dokłada wlasna regule (np. statystyki meczu nie wczesniej niz 90 min po starcie).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

UTC = timezone.utc
CLOCK_SKEW = timedelta(minutes=5)
POST_MATCH_LAG = timedelta(hours=2, minutes=15)   # konserwatywny koniec meczu (z doliczonym czasem)
MIN_AFTER_KICKOFF = timedelta(minutes=90)         # dolna granica dla danych pomeczowych


def utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


class BaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_type: ClassVar[str] = "base"
    post_match: ClassVar[bool] = False  # dane powstajace dopiero po meczu

    source: str = Field(min_length=1)
    source_key: str = Field(min_length=1)       # unikalny klucz rekordu w zrodle (idempotentny zapis)
    available_at: AwareDatetime
    fetched_at: AwareDatetime
    available_at_estimated: bool = False        # True = szacunek konserwatywny, nie zapis zrodla
    license: str = ""

    @field_validator("available_at", "fetched_at", mode="after")
    @classmethod
    def _to_utc(cls, v: datetime) -> datetime:
        return utc(v)

    @model_validator(mode="after")
    def _available_not_after_fetch(self):
        if self.available_at > self.fetched_at + CLOCK_SKEW:
            raise ValueError(f"available_at {self.available_at} po fetched_at {self.fetched_at}: "
                             f"informacja nie mogla byc pobrana, zanim sie pojawila")
        if self.available_at > self.fetched_at:
            self.available_at = self.fetched_at  # drobny rozjazd zegarow
        return self


class EventRef(BaseRecord):
    """Odniesienie do meczu w nazwach zrodla. event_id (kanoniczny) uzupelnia mapowanie encji."""
    league: str
    kickoff_utc: AwareDatetime
    home: str
    away: str
    event_id: str | None = None

    @field_validator("kickoff_utc", mode="after")
    @classmethod
    def _k_utc(cls, v: datetime) -> datetime:
        return utc(v)

    @model_validator(mode="after")
    def _post_match_rule(self):
        if self.post_match and self.available_at < self.kickoff_utc + MIN_AFTER_KICKOFF:
            raise ValueError(f"{self.record_type}: dane pomeczowe dostepne przed koncem meczu "
                             f"({self.available_at} < start {self.kickoff_utc} + 90 min) = wyciek")
        return self


class MatchResult(EventRef):
    record_type: ClassVar[str] = "rec_match_results"
    post_match: ClassVar[bool] = True
    fthg: int = Field(ge=0)
    ftag: int = Field(ge=0)
    hthg: int | None = Field(default=None, ge=0)
    htag: int | None = Field(default=None, ge=0)


class OddsQuote(EventRef):
    record_type: ClassVar[str] = "rec_odds_quotes"
    bookmaker: str
    market: str
    selection: str
    line: float | None = None
    price: float = Field(gt=1.0)
    kind: Literal["taken", "prematch", "close", "bench"]

    @model_validator(mode="after")
    def _close_rule(self):
        # kurs zamkniecia istnieje dopiero tuz przed startem: nigdy nie moze trafic do typu "wczesniej"
        if self.kind == "close" and self.available_at < self.kickoff_utc - timedelta(minutes=15):
            raise ValueError("kurs zamkniecia dostepny wiecej niz 15 min przed startem: to nie zamkniecie")
        return self


class TeamMatchStats(EventRef):
    record_type: ClassVar[str] = "team_match_stats"
    post_match: ClassVar[bool] = True
    team: str
    side: Literal["home", "away"]
    xg: float | None = Field(default=None, ge=0)
    shots: int | None = Field(default=None, ge=0)
    shots_on_target: int | None = Field(default=None, ge=0)
    corners: int | None = Field(default=None, ge=0)
    fouls: int | None = Field(default=None, ge=0)
    yellow: int | None = Field(default=None, ge=0)
    red: int | None = Field(default=None, ge=0)
    possession_pct: float | None = Field(default=None, ge=0, le=100)


class PlayerMatchStats(EventRef):
    record_type: ClassVar[str] = "player_match_stats"
    post_match: ClassVar[bool] = True
    team: str
    player: str
    player_ref: str | None = None
    position: str | None = None
    minutes: int | None = Field(default=None, ge=0)
    goals: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    xg: float | None = Field(default=None, ge=0)
    xa: float | None = Field(default=None, ge=0)
    shots: int | None = Field(default=None, ge=0)
    shots_on_target: int | None = Field(default=None, ge=0)
    fouls_committed: int | None = Field(default=None, ge=0)
    fouls_drawn: int | None = Field(default=None, ge=0)
    yellow: int | None = Field(default=None, ge=0)
    red: int | None = Field(default=None, ge=0)


class MatchEvent(EventRef):
    record_type: ClassVar[str] = "match_events"
    post_match: ClassVar[bool] = True
    minute: int = Field(ge=0)
    extra_minute: int | None = Field(default=None, ge=0)
    # corner: team = druzyna WYKONUJACA rozny (TheStatsAPI podaje te, ktora go oddala; adapter odwraca)
    type: Literal["goal", "own_goal", "penalty_scored", "penalty_missed", "yellow", "second_yellow", "red", "corner"]
    team: str
    player: str | None = None


class RefereeAssignment(EventRef):
    record_type: ClassVar[str] = "referee_assignments"
    referee: str
    role: Literal["main", "var", "assistant", "fourth"] = "main"


class LineupEntry(EventRef):
    record_type: ClassVar[str] = "rec_lineups"
    team: str
    player: str
    status: Literal["start", "lawka", "nieobecny", "watpliwy", "zawieszenie"]
    position: str | None = None
    reason: str | None = None


class WeatherRecord(BaseRecord):
    record_type: ClassVar[str] = "weather"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    valid_time: AwareDatetime
    kind: Literal["forecast", "observed"]
    lead_hours: float | None = Field(default=None, ge=0)  # wyprzedzenie prognozy
    temperature_c: float | None = None
    precipitation_mm: float | None = Field(default=None, ge=0)
    wind_kmh: float | None = Field(default=None, ge=0)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    event_id: str | None = None

    @model_validator(mode="after")
    def _weather_rule(self):
        vt = utc(self.valid_time)
        if self.kind == "forecast" and self.available_at > vt:
            raise ValueError("prognoza wydana po chwili, ktorej dotyczy: to obserwacja, nie prognoza")
        if self.kind == "observed" and self.available_at < vt:
            raise ValueError("obserwacja pogody dostepna przed jej czasem = wyciek")
        return self


class ExchangeTick(BaseRecord):
    record_type: ClassVar[str] = "exchange_ticks"
    market_id: str
    selection_id: str
    ts: AwareDatetime
    market_type: str | None = None
    event_name: str | None = None
    back: float | None = Field(default=None, gt=1.0)
    lay: float | None = Field(default=None, gt=1.0)
    ltp: float | None = Field(default=None, gt=1.0)
    traded_volume: float | None = Field(default=None, ge=0)
    event_id: str | None = None

    @model_validator(mode="after")
    def _tick_rule(self):
        if self.available_at < utc(self.ts) - timedelta(seconds=1):
            raise ValueError("tick gieldy dostepny przed czasem publikacji")
        return self


class NewsMessage(BaseRecord):
    record_type: ClassVar[str] = "news_messages"
    channel: str
    message_id: int = Field(ge=1)
    version: int = Field(ge=1)       # kazda edycja = nowa wersja, stary tekst zostaje
    text: str
    url: str
    published_at: AwareDatetime
    edited_at: AwareDatetime | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _news_rule(self):
        expected = utc(self.edited_at or self.published_at)
        if self.available_at < expected - timedelta(seconds=1):
            raise ValueError("wiadomosc dostepna przed jej publikacja/edycja")
        return self


class TennisMatch(BaseRecord):
    record_type: ClassVar[str] = "tennis_matches"
    match_id: str
    tour: Literal["atp", "wta"]
    match_date: date
    tournament: str
    round: str | None = None
    surface: str | None = None
    best_of: int | None = Field(default=None, ge=1)
    player1: str
    player2: str
    hand1: str | None = None
    hand2: str | None = None

    @model_validator(mode="after")
    def _tennis_rule(self):
        start = datetime.combine(self.match_date, datetime.min.time(), tzinfo=UTC)
        if self.available_at < start:
            raise ValueError("mecz tenisowy dostepny przed swoja data")
        return self


class TennisServeStats(BaseRecord):
    record_type: ClassVar[str] = "tennis_serve_stats"
    match_id: str
    match_date: date
    player: str
    serve_pts: int = Field(ge=0)
    aces: int = Field(ge=0)
    dfs: int = Field(ge=0)
    first_in: int = Field(ge=0)
    first_won: int = Field(ge=0)
    second_in: int = Field(ge=0)
    second_won: int = Field(ge=0)
    bk_pts: int = Field(ge=0)
    bp_saved: int = Field(ge=0)
    return_pts: int = Field(ge=0)
    return_pts_won: int = Field(ge=0)

    @model_validator(mode="after")
    def _serve_rule(self):
        start = datetime.combine(self.match_date, datetime.min.time(), tzinfo=UTC)
        if self.available_at < start + timedelta(days=1):
            raise ValueError("statystyki meczu tenisowego dostepne przed jego koncem")
        if self.first_won > self.first_in or self.first_in > self.serve_pts:
            raise ValueError("niespojne statystyki serwisu")
        return self


class TennisPoint(BaseRecord):
    record_type: ClassVar[str] = "tennis_points"
    match_id: str
    match_date: date
    pt: int = Field(ge=1)
    set1: int = Field(ge=0)
    set2: int = Field(ge=0)
    gm1: int = Field(ge=0)
    gm2: int = Field(ge=0)
    pts: str
    tiebreak_set: bool | None = None
    server: Literal[1, 2]
    pt_winner: Literal[1, 2]

    @model_validator(mode="after")
    def _point_rule(self):
        start = datetime.combine(self.match_date, datetime.min.time(), tzinfo=UTC)
        if self.available_at < start + timedelta(days=1):
            raise ValueError("punkty meczu tenisowego dostepne przed jego koncem")
        return self


ALL_RECORD_TYPES: tuple[type[BaseRecord], ...] = (
    MatchResult, OddsQuote, TeamMatchStats, PlayerMatchStats, MatchEvent, RefereeAssignment,
    LineupEntry, WeatherRecord, ExchangeTick, NewsMessage, TennisMatch, TennisServeStats, TennisPoint)
