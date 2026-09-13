"""Pins test-only environment settings before anything else imports api.config.

FAKE_DATA in particular must never leak in from a developer's local .env — api/config.py
calls load_dotenv(), which by default won't override an already-set env var, so setting
it here first keeps the suite deterministic and free regardless of whatever a developer
has locally set for manual browser testing.
"""

import os

os.environ["FAKE_DATA"] = "1"
