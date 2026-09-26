"""Sets MATH_NOTES_DB_PATH/MATH_NOTES_PLOTS_DIR before anything under src/ is imported --
db.py and public_app.py both read these once, as module-level defaults, at import time
(public_app.py's StaticFiles mount in particular captures its directory permanently at
that point, so a monkeypatch applied *after* import has no effect on it). Setting them
here in conftest.py, which pytest loads before collecting any test module, is what
actually makes the whole app importable against an isolated, disposable database.
"""

import os
import sys
import tempfile
from pathlib import Path

_tmp_dir = tempfile.mkdtemp(prefix="math-notes-tests-")
os.environ["MATH_NOTES_DB_PATH"] = str(Path(_tmp_dir) / "test.db")
os.environ["MATH_NOTES_PLOTS_DIR"] = str(Path(_tmp_dir) / "assets" / "plots")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

import db  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def _clean_posts_table():
    """Every test starts with an empty posts table -- one shared database file for the
    whole test session (see above for why), isolated per-test by content instead of by
    file."""
    conn = db.get_connection()
    conn.execute("DELETE FROM posts")
    conn.commit()
    conn.close()
    yield
