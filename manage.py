"""
Command-line admin tools for the Secret Santa server (run on the host / in the container).

Useful when the organiser themselves is locked out or has forgotten their password,
since those actions are otherwise only available to the organiser in the web UI.

    python3 manage.py list
    python3 manage.py reset-password <username>
    python3 manage.py unlock <username>

Uses SECRETSANTA_DB from the environment / .env, same as server.py.
"""

import sys
import database as db


def find_adult(username: str):
    clean = username.strip().lower()
    return next((u for u in db.get_all_users() if not u["is_child"] and u["username"] == clean), None)


def main(argv) -> int:
    if len(argv) < 2 or argv[1] not in ("list", "reset-password", "unlock"):
        print(__doc__.strip())
        return 2

    db.init_db()
    command = argv[1]

    if command == "list":
        security = db.get_security_status()
        for u in db.get_all_users():
            if u["is_child"]:
                continue
            sec = security.get(u["id"], {})
            flags = []
            if sec.get("is_locked"):
                flags.append(f"LOCKED until {sec['locked_until']}")
            if sec.get("must_change_password"):
                flags.append("must change password")
            print(f"{u['username']:<20} {u['display_name']:<24} {u['role']:<10} {', '.join(flags)}")
        return 0

    if len(argv) != 3:
        print(f"Usage: python3 manage.py {command} <username>")
        return 2

    user = find_adult(argv[2])
    if not user:
        print(f"No account with username '{argv[2]}'")
        return 1

    if command == "unlock":
        db.unlock_user(user["id"])
        print(f"Unlocked {user['username']}.")
    else:
        temp = db.admin_reset_password(user["id"])
        print(f"Temporary password for {user['username']}: {temp}")
        print("They will be asked to choose a new password when they sign in.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
