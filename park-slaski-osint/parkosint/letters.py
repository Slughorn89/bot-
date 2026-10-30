"""Wypełnianie szablonów z katalogu letters/ danymi z YAML. Pola {{KLUCZ}}."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import ROOT

TEMPLATES = ROOT / "letters"
PLACEHOLDER = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def fill(text: str, data: dict) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m):
        # brak klucza albo null = do uzupełnienia; pusty string "" = pole celowo puste
        key = m.group(1)
        value = data.get(key)
        if value is None:
            if key not in missing:
                missing.append(key)
            return f"[{key}]"
        return str(value).strip()

    return PLACEHOLDER.sub(sub, text), missing


def render_all(data_path: Path, out_dir: Path) -> list[tuple[Path, list[str]]]:
    if not data_path.exists():
        raise SystemExit(f"Brak pliku {data_path}. Skopiuj letters/dane.example.yaml do letters/dane.yaml i uzupełnij.")
    data = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for tpl in sorted(TEMPLATES.glob("[0-9][0-9]_*.md")):
        text, missing = fill(tpl.read_text(encoding="utf-8"), data)
        path = out_dir / tpl.name
        path.write_text(text, encoding="utf-8")
        written.append((path, missing))
    return written
