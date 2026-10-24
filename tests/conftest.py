"""
Keep the test suite away from the real/dev database.

pytest imports this file before any test module, so db.py (which initialises
on import) picks up this throw-away SQLite file instead of ./data/amverio.db.
If you run the tests another way (python -m unittest), set AMVERIO_DB_PATH yourself.
"""

import os
import tempfile

if not os.environ.get("AMVERIO_DB_PATH"):
    os.environ["AMVERIO_DB_PATH"] = os.path.join(
        tempfile.mkdtemp(prefix="amverio-pytest-"), "amverio.db"
    )
