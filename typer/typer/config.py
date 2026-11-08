"""Ladowanie konfiguracji (YAML) i zmiennych srodowiskowych (.env)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"

try:  # .env jest opcjonalny
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def sports() -> dict:
    return load_yaml("sports.yaml")


def leagues(sport: str = "football", extra: bool = False) -> dict:
    """extra=True: plus ligi tylko do cyklu dziennego (extra_leagues), bez backtestu."""
    s = sports()[sport]
    return {**s["leagues"], **(s.get("extra_leagues") or {})} if extra else s["leagues"]


def sources() -> dict:
    return load_yaml("sources.yaml")


def gates() -> dict:
    return load_yaml("gates.yaml")


def model_params() -> dict:
    return load_yaml("model.yaml")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def database_url() -> str:
    """Wzgledna sciezka SQLite (np. sqlite:///data/typer.db z .env.example) liczy sie od katalogu typer/,
    a nie od biezacego katalogu: inaczej uruchomienie z innego miejsca tworzy nowa, pusta baze."""
    url = env("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'typer.db'}"
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        path = Path(url[len("sqlite:///"):])
        if not path.is_absolute():
            url = f"sqlite:///{(ROOT / path).as_posix()}"
    return url
