"""Wspólne narzędzia testowe. Odpowiedzi API w testach to ręcznie przygotowane przykłady
w formacie z dokumentacji, nie prawdziwe wyniki wyszukiwania."""
from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parkosint.timeutil import Window  # noqa: E402


class FakeHttp:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict, dict | None]] = []
        self.count = 0

    def get_json(self, url, params=None, headers=None):
        self.count += 1
        params = dict(params or {})
        self.calls.append((url, params, headers))
        return self.handler(url, params, headers)

    def _sleep(self, s):
        pass


@pytest.fixture
def window():
    return Window.from_local(date(2026, 10, 17), time(16, 15), time(18, 0), margin_min=30)
