import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.synth import make_matches  # noqa: E402


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
