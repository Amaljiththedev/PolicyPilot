"""Sync every Drive connection once, or keep doing it (the background worker).

    python scripts/drive_sync.py            # once (e.g. from cron)
    python scripts/drive_sync.py --loop     # every DRIVE_SYNC_INTERVAL_SECONDS (docker compose worker)
"""
import argparse
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import get_settings
from app.db.models import DriveConnection
from app.db.session import SessionLocal
from app.integrations.gdrive import DriveError, sync_connection


def run_once():
    db = SessionLocal()
    try:
        for conn in db.query(DriveConnection).filter(DriveConnection.folder_id.isnot(None)).all():
            try:
                r = sync_connection(db, conn)
                print(f"connection {conn.id}: +{len(r['added'])} ~{len(r['updated'])} "
                      f"-{len(r['removed'])} ={r['unchanged']} errors={len(r['errors'])}", flush=True)
            except DriveError as e:
                db.rollback()
                print(f"connection {conn.id}: {e}", file=sys.stderr, flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--loop", action="store_true")
    a = p.parse_args()
    while True:
        run_once()
        if not a.loop:
            break
        time.sleep(get_settings().DRIVE_SYNC_INTERVAL_SECONDS)
