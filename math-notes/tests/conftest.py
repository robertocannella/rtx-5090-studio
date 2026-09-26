import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own DB file and plots dir, and matplotlib's config cache
    redirected somewhere writable -- nothing here should ever touch the real, live
    /app/data used by the running container.
    """
    monkeypatch.setenv("MATH_NOTES_DB_PATH", str(tmp_path / "math-notes.db"))
    monkeypatch.setenv("MATH_NOTES_PLOTS_DIR", str(tmp_path / "assets" / "plots"))
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / ".matplotlib"))

    import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "math-notes.db"))
    monkeypatch.setattr(db, "PLOTS_DIR", tmp_path / "assets" / "plots")
    db.init_db()
    yield
