"""Test isolation: every pytest session runs against a COPY of the demo database.

The demo database (data/control_tower.sqlite) must stay pristine so the
interview demo (FSU replay → auto-resolve) always works. Tests get a throwaway
copy via the DB_PATH environment variable, which pydantic-settings maps onto
Settings.db_path before any app module is imported.
"""

import os
import shutil
import tempfile
from pathlib import Path

_REAL_DB = Path(__file__).resolve().parents[2] / "data" / "control_tower.sqlite"

_tmp_dir = tempfile.mkdtemp(prefix="hkg-ct-tests-")
_test_db = os.path.join(_tmp_dir, "control_tower_test.sqlite")

if _REAL_DB.exists():
    shutil.copy2(_REAL_DB, _test_db)
else:
    # CI builds the DB before pytest; a missing file would fail loudly anyway.
    open(_test_db, "wb").close()

os.environ["DB_PATH"] = _test_db

# Business-logic tests run without auth bookkeeping; a dedicated test covers
# the 401/cookie paths by flipping this back on.
from app import auth as _auth  # noqa: E402

_auth.AUTH_ENABLED = False
