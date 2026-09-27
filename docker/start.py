"""Container entrypoint: wait for Postgres, create/migrate tables, start the API.

Python rather than a shell script so Windows line endings can't break it.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/app")
from sqlalchemy import create_engine, text  # noqa: E402

url = os.environ["DATABASE_URL"]
for attempt in range(30):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        print("database is up")
        break
    except Exception as e:
        print(f"waiting for database ({attempt + 1}/30): {type(e).__name__}")
        time.sleep(2)
else:
    sys.exit("database never came up")

subprocess.run([sys.executable, "scripts/create_tables.py"], check=True)
subprocess.run([sys.executable, "scripts/migrate_p8.py"], check=True)

os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
                      "--workers", os.environ.get("WEB_WORKERS", "1")])
