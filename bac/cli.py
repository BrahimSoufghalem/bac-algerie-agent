import argparse, getpass, os
from pathlib import Path
from bac.core.config import Settings
from bac.core.services import Services
from bac.core.auth import create_user, hash_password


def main():
    p = argparse.ArgumentParser(
        description="Masar administration; backup/restore require stopped API+worker"
    )
    p.add_argument(
        "action",
        choices=[
            "bootstrap",
            "migrate",
            "backup",
            "restore",
            "reset-password",
            "verify-email",
        ],
    )
    p.add_argument("--email")
    p.add_argument("--name", default="المالك")
    p.add_argument("--output", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--destination", type=Path)
    args = p.parse_args()
    cfg = Settings.from_env()
    if args.action == "backup":
        from bac.ops.backup import backup

        if not args.output:
            p.error("--output is required")
        print(backup(cfg.data_dir, args.output))
        return
    if args.action == "restore":
        from bac.ops.backup import restore

        if not args.archive or not args.destination:
            p.error("--archive and --destination are required")
        print(restore(args.archive, args.destination))
        return
    s = Services(cfg)
    try:
        if args.action == "bootstrap":
            if s.db.one("SELECT 1 FROM users WHERE role='owner'"):
                raise SystemExit("Owner already exists; refusing to create another")
            if not args.email:
                p.error("--email is required")
            password = os.environ.get("OWNER_PASSWORD") or getpass.getpass(
                "Owner password (12+ chars): "
            )
            id = create_user(s.db, args.email, password, args.name, "owner")
            # Bootstrap is a trusted operator action, not public registration.
            s.db.execute("UPDATE users SET email_verified=1 WHERE id=?", (id,))
            print("Created owner account:", id)
        elif args.action in ("reset-password", "verify-email"):
            if not args.email:
                p.error("--email is required")
            u = s.db.one(
                "SELECT id FROM users WHERE email=?", (args.email.casefold().strip(),)
            )
            if not u:
                raise SystemExit("Account not found")
            if args.action == "reset-password":
                password = getpass.getpass("New password (12–256 chars): ")
                if not 12 <= len(password) <= 256:
                    raise SystemExit("Invalid password length")
                from bac.ops.lifecycle import invalidate

                with s.db.tx() as c:
                    c.execute(
                        "UPDATE users SET password_hash=? WHERE id=?",
                        (hash_password(password), u["id"]),
                    )
                    invalidate(c, u["id"])
            else:
                s.db.execute("UPDATE users SET email_verified=1 WHERE id=?", (u["id"],))
            s.db.audit("operator", "auth.operator." + args.action, u["id"])
            print("Updated account; operator action audited")
        else:
            print("Database migrations applied")
    finally:
        s.close()


if __name__ == "__main__":
    main()
