"""Local-only way in, for tests, evals and Swagger while developing.
Creates the user if needed and prints a token. Never exposed as an HTTP route.

    python scripts/dev_token.py --email you@example.com [--admin] [--organisation "Faversham Town Council"]
"""
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.security import create_access_token
from app.db.models import User
from app.db.session import SessionLocal

p = argparse.ArgumentParser()
p.add_argument("--email", required=True)
p.add_argument("--admin", action="store_true")
p.add_argument("--organisation", default=None)
a = p.parse_args()

db = SessionLocal()
u = db.query(User).filter(User.email == a.email.lower()).first()
if u is None:
    u = User(email=a.email.lower(), auth_provider="dev", hashed_password=None, is_active=True,
             role="admin" if a.admin else "staff", organisation=a.organisation)
    db.add(u)
else:
    if a.admin:
        u.role = "admin"
    if a.organisation:
        u.organisation = a.organisation
db.commit()
db.refresh(u)
print(f"user {u.id} {u.email} role={u.role} organisation={u.organisation}", file=sys.stderr)
print(create_access_token(u.id))
