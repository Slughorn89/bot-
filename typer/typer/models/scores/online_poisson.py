"""Oceny online: sila ataku i obrony druzyn + przewaga gospodarza per liga.

log lambda_dom  = mu_L + h_L + atk[dom] - obr[gosc]
log lambda_gosc = mu_L       + atk[gosc] - obr[dom]

Po kazdym meczu jeden krok gradientu logarytmu wiarygodnosci Poissona (y - lambda), gdzie
y = (1 - w_xg) * gole + w_xg * proxy_xG (proxy z celnych i niecelnych strzalow; lepiej mierzy
forme niz same gole). Przewaga gospodarza ma wlasne tempo nauki: w danych widac, ze to ona
sie rozjezdza (np. mecze bez kibicow 2020/21). To najprostsza forma uczenia sie dzien po dniu.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


@dataclass
class Params:
    lr_team: float = 0.035          # tempo nauki ataku/obrony
    lr_home: float = 0.004          # tempo nauki przewagi gospodarza (per liga)
    lr_mu: float = 0.002            # tempo nauki poziomu goli w lidze
    w_xg: float = 0.5               # waga proxy xG w celu aktualizacji (0 = same gole)
    season_regress: float = 0.25    # o ile sciagamy oceny do sredniej miedzy sezonami
    promoted_atk: float = -0.18     # start beniaminka (atak)
    promoted_obr: float = -0.15     # start beniaminka (obrona)
    new_team_boost: float = 1.5     # szybsza nauka nowych druzyn: lr * (1 + boost * exp(-n/tau))
    new_team_tau: float = 8.0
    red_card_weight: float = 1.0    # mnoznik kroku dla meczow z czerwona kartka
    rho: float = -0.06              # korekta Dixona-Colesa niskich wynikow
    init_mu: float = 0.15           # log sredniej goli goscia na starcie
    init_home: float = 0.25         # log przewagi gospodarza na starcie
    xg_sot: float = 0.27            # proxy xG: gole na celny strzal (MNK na rozgrzewce)
    xg_off: float = 0.006           # proxy xG: gole na niecelny strzal
    home_overrides: dict = field(default_factory=dict)  # celowane poprawki: {liga: lr_home}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TeamState:
    atk: float
    obr: float
    n: int = 0             # mecze w tej lidze od wejscia
    season: str = ""


class OnlinePoisson:
    def __init__(self, params: Params | None = None):
        self.p = params or Params()
        self.teams: dict[tuple[str, str], TeamState] = {}
        self.mu: dict[str, float] = {}
        self.home: dict[str, float] = {}
        self.season: dict[str, str] = {}

    # ---------- stan ligi i druzyn ----------
    def _league(self, lg: str):
        if lg not in self.mu:
            self.mu[lg] = self.p.init_mu
            self.home[lg] = self.p.init_home

    def start_season(self, lg: str, season: str) -> None:
        """Nowy sezon: oceny sciagniete do sredniej. Druzyny, ktore nie graly w poprzednim sezonie,
        przy pierwszym meczu dostana start beniaminka."""
        self._league(lg)
        if self.season.get(lg) == season:
            return
        prev = self.season.get(lg)
        r = 1 - self.p.season_regress
        for (l, t), s in self.teams.items():
            if l == lg:
                s.atk *= r
                s.obr *= r
        self.season[lg] = season
        self._prev_season = getattr(self, "_prev_season", {})
        self._prev_season[lg] = prev

    def _team(self, lg: str, team: str) -> TeamState:
        key = (lg, team)
        s = self.teams.get(key)
        cur = self.season.get(lg, "")
        prev = getattr(self, "_prev_season", {}).get(lg)
        if s is None or (s.season not in (cur, prev) and s.season != ""):
            # nowa druzyna albo powrot po co najmniej sezonie przerwy = beniaminek
            s = TeamState(self.p.promoted_atk, self.p.promoted_obr, 0, cur)
            self.teams[key] = s
        return s

    def is_new(self, lg: str, team: str) -> bool:
        s = self.teams.get((lg, team))
        return s is None or s.n < 5

    # ---------- predykcja i nauka ----------
    def rates(self, lg: str, home: str, away: str) -> tuple[float, float]:
        self._league(lg)
        h, a = self._team(lg, home), self._team(lg, away)
        lh = math.exp(self.mu[lg] + self.home[lg] + h.atk - a.obr)
        la = math.exp(self.mu[lg] + a.atk - h.obr)
        return lh, la

    def xg_proxy(self, shots: float | None, sot: float | None) -> float | None:
        if shots is None or sot is None or shots != shots or sot != sot:
            return None
        return self.p.xg_sot * sot + self.p.xg_off * max(shots - sot, 0.0)

    def update(self, lg: str, home: str, away: str, gh: float, ga: float,
               hs=None, as_=None, hst=None, ast=None, red: bool = False) -> None:
        lh, la = self.rates(lg, home, away)
        xh, xa = self.xg_proxy(hs, hst), self.xg_proxy(as_, ast)
        w = self.p.w_xg if (xh is not None and xa is not None) else 0.0
        yh = (1 - w) * gh + w * (xh or 0.0)
        ya = (1 - w) * ga + w * (xa or 0.0)
        eh, ea = yh - lh, ya - la
        mult = self.p.red_card_weight if red else 1.0
        h, a = self._team(lg, home), self._team(lg, away)
        cur = self.season.get(lg, "")

        def lr(s: TeamState) -> float:
            return self.p.lr_team * mult * (1 + self.p.new_team_boost * math.exp(-s.n / self.p.new_team_tau))

        lrh, lra = lr(h), lr(a)
        h.atk += lrh * eh
        a.obr -= lra * eh
        a.atk += lra * ea
        h.obr -= lrh * ea
        lr_home = self.p.home_overrides.get(lg, self.p.lr_home)
        self.home[lg] += lr_home * mult * (eh - ea) / 2
        self.mu[lg] += self.p.lr_mu * mult * (eh + ea)
        h.n += 1
        a.n += 1
        h.season = a.season = cur

    def recenter(self, lg: str) -> None:
        """Srednia ataku i obrony aktywnych druzyn = 0 (poziom ligi siedzi w mu). Bez tego oceny
        dryfuja i przestaja byc porownywalne miedzy sezonami."""
        cur = self.season.get(lg, "")
        act = [s for (l, _), s in self.teams.items() if l == lg and s.season == cur]
        if len(act) < 16:  # na poczatku sezonu (czesc druzyn jeszcze nie grala) srednia bylaby szumem
            return
        ma = sum(s.atk for s in act) / len(act)
        mo = sum(s.obr for s in act) / len(act)
        for s in act:
            s.atk -= ma
            s.obr -= mo
        self.mu[lg] += ma - mo

    def snapshot(self, lg: str) -> list[dict]:
        cur = self.season.get(lg, "")
        return [dict(league=l, team=t, attack=s.atk, defense=s.obr, n=s.n)
                for (l, t), s in self.teams.items() if l == lg and s.season == cur]
