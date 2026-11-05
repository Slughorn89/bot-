import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.synth_league import make_matches  # noqa: E402


@pytest.fixture(scope="session")
def synth():
    """Syntetyczna liga (DANE TESTOWE, nie prawdziwe mecze): znane sily druzyn, Poisson, kursy z marza."""
    return make_matches(seed=1)


@pytest.fixture
def tmp_engine(tmp_path):
    from typer.store import db
    eng = db.get_engine(f"sqlite:///{tmp_path / 't.db'}")
    db.init_db(eng)
    return eng


SLOW_IN_ANNEX_D = ("test_dryf_wykrywa_blad_danych", "test_dryf_rzadkie_falszywe_alarmy_na_uczciwym_modelu")


def pytest_collection_modifyitems(config, items):
    """Zalacznik D zostaje bez zmian; jego testy dryfu oznaczamy jako slow tutaj (CI < 1 min)."""
    for it in items:
        if it.name.split("[")[0] in SLOW_IN_ANNEX_D or it.fspath.basename == "test_e2e.py":
            it.add_marker(pytest.mark.slow)
