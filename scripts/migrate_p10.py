"""Google sign-in, Drive sync and Slack columns. Safe to run twice.
New tables (drive_connections, drive_files) are created by create_tables.py.

    python scripts/migrate_p10.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text

from app.db.session import engine

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
    for name, t in {"auth_provider": "VARCHAR(32) NOT NULL DEFAULT 'password'",
                    "google_sub": "VARCHAR(64)", "organisation": "VARCHAR(120)"}.items():
        conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {t}"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)"))
    for name, t in {"source": "VARCHAR(16) NOT NULL DEFAULT 'api'", "slack_channel": "VARCHAR(32)",
                    "slack_ts": "VARCHAR(32)"}.items():
        conn.execute(text(f"ALTER TABLE queries ADD COLUMN IF NOT EXISTS {name} {t}"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_queries_slack_ts ON queries (slack_ts)"))
print("users/queries: P10 columns ok")
