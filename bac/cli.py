import argparse, getpass, os
from bac.core.services import Services
from bac.core.auth import create_user

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["bootstrap", "migrate"])
    p.add_argument("--email")
    p.add_argument("--name", default="المالك")
    args = p.parse_args()
    s = Services()
    if args.action == "bootstrap":
        if s.db.one("SELECT 1 FROM users WHERE role='owner'"):
            raise SystemExit("Owner already exists; refusing to create another")
        if not args.email:
            raise SystemExit("--email is required")
        password = os.environ.get("OWNER_PASSWORD") or getpass.getpass(
            "Owner password (12+ chars): "
        )
        id = create_user(s.db, args.email, password, args.name, "owner")
        print("Created owner account:", id)
    else:
        print("Database migrations applied")
