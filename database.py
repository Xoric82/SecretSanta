"""
Database module for Secret Santa Application.
Uses Python's built-in sqlite3 with Write-Ahead Logging (WAL) for concurrency.
"""

import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

def load_env_file(filepath: Optional[str] = None):
    """Loads key-value pairs from a .env file into os.environ if not already present."""
    if filepath is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(base_dir, ".env")
        if os.path.isfile(candidate):
            filepath = candidate
        elif os.path.isfile(".env"):
            filepath = os.path.abspath(".env")
    if filepath and os.path.isfile(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key:
                        if key not in os.environ or os.environ[key] == "":
                            os.environ[key] = val
        except Exception:
            pass

load_env_file()

DB_PATH = os.environ.get("SECRETSANTA_DB", "secretsanta.db")


def resolve_db_path(db_path: Optional[str] = None) -> str:
    return db_path if db_path is not None else DB_PATH


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target = resolve_db_path(db_path)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency and foreign keys
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None):
    """Initializes the SQLite schema."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user', -- 'organiser' or 'user'
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                event_name TEXT NOT NULL DEFAULT 'Family Secret Santa',
                budget_limit TEXT DEFAULT '$25 - $50',
                reveal_date TEXT DEFAULT '',
                rules_note TEXT DEFAULT 'Keep gifts secret until Christmas/reveal day!',
                is_drawn INTEGER NOT NULL DEFAULT 0,
                drawn_at TEXT
            );

            CREATE TABLE IF NOT EXISTS assignments (
                giver_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                assigned_at TEXT NOT NULL,
                CONSTRAINT no_self_gift CHECK (giver_id != receiver_id)
            );

            CREATE TABLE IF NOT EXISTS wishlist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                url TEXT,
                price TEXT,
                priority INTEGER NOT NULL DEFAULT 1, -- 1=Normal, 2=High
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS purchases (
                item_id INTEGER PRIMARY KEY REFERENCES wishlist_items(id) ON DELETE CASCADE,
                buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purchased_at TEXT NOT NULL
            );

            -- Initialize default event settings row if not present
            INSERT OR IGNORE INTO event_settings (id, event_name, budget_limit, is_drawn)
            VALUES (1, 'Family Secret Santa', '$25 - $50', 0);
            """)
            _migrate(conn)
    finally:
        conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection):
    """Additive, idempotent schema migrations for databases created by earlier versions."""
    user_cols = _column_names(conn, "users")
    if "parent_id" not in user_cols:
        # NULL for adult accounts; set to the managing parent's id for child profiles.
        conn.execute("ALTER TABLE users ADD COLUMN parent_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
    if "in_draw" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN in_draw INTEGER NOT NULL DEFAULT 1")
    if "failed_logins" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0")
    if "locked_until" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    if "must_change_password" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_parent ON users(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")

    if "avoid_household" not in _column_names(conn, "event_settings"):
        conn.execute("ALTER TABLE event_settings ADD COLUMN avoid_household INTEGER NOT NULL DEFAULT 1")


MAX_CHILDREN_PER_PARENT = 20
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 30
MIN_PASSWORD_LENGTH = 4
# Unambiguous characters for temporary passwords (no 0/O, 1/l/I)
_TEMP_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_DUMMY_SALT = "0" * 32


class AccountLockedError(Exception):
    """Raised when a login is attempted on an account locked by too many failed attempts."""

    def __init__(self, locked_until: datetime):
        self.locked_until = locked_until
        remaining = max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
        self.minutes_remaining = min(remaining, LOCKOUT_MINUTES)
        super().__init__(
            f"This account is locked after {MAX_FAILED_LOGINS} failed sign-in attempts. "
            f"Try again in {self.minutes_remaining} minute{'s' if self.minutes_remaining != 1 else ''} "
            f"or ask the organiser to unlock it."
        )


def _validate_new_password(password: str):
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")


def _user_dict(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "must_change_password": bool(row["must_change_password"]),
    }


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes a password with PBKDF2-HMAC-SHA256 and a random salt."""
    if not salt:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100000
    ).hex()
    return pw_hash, salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, expected_hash)


def create_user(username: str, display_name: str, password: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Registers a new user. If this is the first user, they automatically get 'organiser' role."""
    clean_username = username.strip().lower()
    clean_display = display_name.strip()
    if not clean_username or len(clean_username) < 3:
        raise ValueError("Username must be at least 3 characters long")
    if not clean_display:
        raise ValueError("Display name cannot be empty")
    _validate_new_password(password)

    conn = get_db_connection(db_path)
    try:
        with conn:
            count = conn.execute("SELECT COUNT(*) FROM users WHERE parent_id IS NULL").fetchone()[0]
            role = 'organiser' if count == 0 else 'user'

            pw_hash, salt = hash_password(password)
            now = datetime.now(timezone.utc).isoformat()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, display_name, password_hash, salt, role, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (clean_username, clean_display, pw_hash, salt, role, now)
                )
                user_id = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(f"Username '{clean_username}' is already taken.")
    finally:
        conn.close()

    return {
        "id": user_id,
        "username": clean_username,
        "display_name": clean_display,
        "role": role,
        "must_change_password": False
    }


def authenticate_user(username: str, password: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Verifies credentials with per-account lockout.

    Each attempt is *reserved* (counter incremented, lock applied at the limit) inside an
    IMMEDIATE transaction before the password is checked, so a burst of concurrent guesses
    can't exceed MAX_FAILED_LOGINS. A correct password then clears the counter and any lock.

    Returns the user dict, None for bad credentials, or raises AccountLockedError.
    """
    clean_username = (username or "").strip().lower()
    now = datetime.now(timezone.utc)
    conn = get_db_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Child profiles are managed by a parent and can never log in directly.
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, salt, role,
                       failed_logins, locked_until, must_change_password
                FROM users WHERE username = ? AND parent_id IS NULL
                """,
                (clean_username,)
            ).fetchone()
            if not row:
                conn.rollback()
                hash_password(password or "", _DUMMY_SALT)  # equalise timing with real accounts
                return None

            failed = row["failed_logins"]
            if row["locked_until"]:
                locked_until = datetime.fromisoformat(row["locked_until"])
                if locked_until > now:
                    conn.rollback()
                    raise AccountLockedError(locked_until)
                failed = 0  # lock expired: start a fresh window

            failed += 1
            new_lock = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat() if failed >= MAX_FAILED_LOGINS else None
            conn.execute(
                "UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                (failed, new_lock, row["id"])
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

        if verify_password(password or "", row["salt"], row["password_hash"]):
            with conn:
                conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (row["id"],))
            return _user_dict(row)

        if new_lock:
            raise AccountLockedError(datetime.fromisoformat(new_lock))
        return None
    finally:
        conn.close()


def unlock_user(user_id: int, db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ? AND parent_id IS NULL",
                (user_id,)
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def generate_temporary_password() -> str:
    chars = "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(12))
    return f"{chars[0:4]}-{chars[4:8]}-{chars[8:12]}"


def admin_reset_password(user_id: int, db_path: Optional[str] = None) -> str:
    """
    Organiser action: assigns a temporary password, forces a change at next login,
    clears any lockout and signs the user out everywhere. Returns the temporary password.
    """
    temp_password = generate_temporary_password()
    pw_hash, salt = hash_password(temp_password)
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                UPDATE users
                SET password_hash = ?, salt = ?, must_change_password = 1,
                    failed_logins = 0, locked_until = NULL
                WHERE id = ? AND parent_id IS NULL
                """,
                (pw_hash, salt, user_id)
            )
            if cur.rowcount == 0:
                raise LookupError("User not found")
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    finally:
        conn.close()
    return temp_password


def change_password(user_id: int, new_password: str, current_password: Optional[str] = None,
                    keep_session_token: Optional[str] = None, db_path: Optional[str] = None):
    """
    Sets a new password and clears must_change_password.
    If current_password is given it must match. All other sessions are signed out.
    """
    _validate_new_password(new_password)
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT password_hash, salt FROM users WHERE id = ? AND parent_id IS NULL", (user_id,)
            ).fetchone()
            if not row:
                raise LookupError("User not found")
            if current_password is not None and not verify_password(current_password, row["salt"], row["password_hash"]):
                raise PermissionError("Current password is incorrect")
            if verify_password(new_password, row["salt"], row["password_hash"]):
                raise ValueError("New password must be different from your current password")
            pw_hash, salt = hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ?, must_change_password = 0 WHERE id = ?",
                (pw_hash, salt, user_id)
            )
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token IS NOT ?",
                (user_id, keep_session_token)
            )
    finally:
        conn.close()


def get_security_status(db_path: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """Organiser-only view of lockout / forced-change state for adult accounts."""
    now = datetime.now(timezone.utc)
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, failed_logins, locked_until, must_change_password FROM users WHERE parent_id IS NULL"
        ).fetchall()
    finally:
        conn.close()
    status = {}
    for r in rows:
        locked = bool(r["locked_until"]) and datetime.fromisoformat(r["locked_until"]) > now
        status[r["id"]] = {
            "is_locked": locked,
            "locked_until": r["locked_until"] if locked else None,
            "failed_logins": r["failed_logins"] if (locked or not r["locked_until"]) else 0,
            "must_change_password": bool(r["must_change_password"]),
        }
    return status


def purge_expired_sessions(db_path: Optional[str] = None) -> int:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),)
            )
            return cur.rowcount
    finally:
        conn.close()


def create_session(user_id: int, days_valid: int = 30, db_path: Optional[str] = None) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days_valid)).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires)
            )
    finally:
        conn.close()
    return token


def get_user_from_session(token: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.must_change_password, s.expires_at
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    return _user_dict(row)


def delete_session(token: str, db_path: Optional[str] = None):
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    finally:
        conn.close()


def get_all_users(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.created_at,
                   u.parent_id, u.in_draw, p.display_name as parent_display_name,
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM users u
            LEFT JOIN users p ON u.parent_id = p.id
            ORDER BY u.display_name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return [_public_user(r) for r in rows]


def _public_user(row) -> Dict[str, Any]:
    d = dict(row)
    d["is_child"] = d.get("parent_id") is not None
    d["in_draw"] = bool(d.get("in_draw", 1))
    if d["is_child"]:
        # Child usernames are internal placeholders; never surface them.
        d["username"] = None
    return d


def get_user(user_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.created_at,
                   u.parent_id, u.in_draw, p.display_name as parent_display_name,
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM users u
            LEFT JOIN users p ON u.parent_id = p.id
            WHERE u.id = ?
            """,
            (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return _public_user(row) if row else None


def can_manage(actor_id: int, target_user_id: int, db_path: Optional[str] = None) -> bool:
    """True if actor owns the target account or is the parent managing that child profile."""
    if actor_id == target_user_id:
        return True
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND parent_id = ?", (target_user_id, actor_id)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


# ==========================================
# Child Profiles (managed by a parent account)
# ==========================================

def _ensure_draw_not_active(conn: sqlite3.Connection, action: str):
    row = conn.execute("SELECT is_drawn FROM event_settings WHERE id = 1").fetchone()
    if row and row["is_drawn"]:
        raise ValueError(f"Names have already been drawn. Ask the organiser to reset the draw before you {action}.")


def get_children(parent_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.created_at,
                   u.parent_id, u.in_draw, p.display_name as parent_display_name,
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM users u
            JOIN users p ON u.parent_id = p.id
            WHERE u.parent_id = ?
            ORDER BY u.display_name ASC
            """,
            (parent_id,)
        ).fetchall()
    finally:
        conn.close()
    return [_public_user(r) for r in rows]


def create_child(parent_id: int, display_name: str, in_draw: bool = True, db_path: Optional[str] = None) -> Dict[str, Any]:
    clean_display = (display_name or "").strip()
    if not clean_display:
        raise ValueError("Child's name cannot be empty")
    if len(clean_display) > 60:
        raise ValueError("Child's name must be 60 characters or fewer")

    conn = get_db_connection(db_path)
    try:
        with conn:
            parent = conn.execute("SELECT id, parent_id FROM users WHERE id = ?", (parent_id,)).fetchone()
            if not parent:
                raise ValueError("Parent account not found")
            if parent["parent_id"] is not None:
                raise ValueError("Child profiles cannot have children of their own")

            count = conn.execute("SELECT COUNT(*) FROM users WHERE parent_id = ?", (parent_id,)).fetchone()[0]
            if count >= MAX_CHILDREN_PER_PARENT:
                raise ValueError(f"You can manage at most {MAX_CHILDREN_PER_PARENT} children")

            if in_draw:
                _ensure_draw_not_active(conn, "add a child to the draw")

            # Child profiles get an unguessable placeholder username and an unusable
            # password; authenticate_user() also refuses any row with a parent_id.
            pw_hash, salt = hash_password(secrets.token_urlsafe(32))
            now = datetime.now(timezone.utc).isoformat()
            for _ in range(5):
                username = f"~child-{parent_id}-{secrets.token_hex(6)}"
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO users (username, display_name, password_hash, salt, role, created_at, parent_id, in_draw)
                        VALUES (?, ?, ?, ?, 'user', ?, ?, ?)
                        """,
                        (username, clean_display, pw_hash, salt, now, parent_id, 1 if in_draw else 0)
                    )
                    child_id = cur.lastrowid
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise ValueError("Could not create child profile, please try again")
    finally:
        conn.close()

    return get_user(child_id, db_path=db_path)


def rename_child(parent_id: int, child_id: int, display_name: str, db_path: Optional[str] = None) -> bool:
    clean_display = (display_name or "").strip()
    if not clean_display:
        raise ValueError("Child's name cannot be empty")
    if len(clean_display) > 60:
        raise ValueError("Child's name must be 60 characters or fewer")
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ? AND parent_id = ?",
                (clean_display, child_id, parent_id)
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def delete_child(parent_id: int, child_id: int, db_path: Optional[str] = None) -> bool:
    """Removes a child profile and (via cascade) their wishlist, purchases and assignments."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            child = conn.execute(
                "SELECT in_draw FROM users WHERE id = ? AND parent_id = ?", (child_id, parent_id)
            ).fetchone()
            if not child:
                return False
            if child["in_draw"]:
                _ensure_draw_not_active(conn, "remove a child who is in the draw")
            conn.execute("DELETE FROM users WHERE id = ?", (child_id,))
            return True
    finally:
        conn.close()


def set_draw_inclusion(actor: Dict[str, Any], target_user_id: int, in_draw: bool, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Include or exclude someone from the draw.
    Parents may toggle their own children; the organiser may toggle anyone.
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            target = conn.execute("SELECT id, parent_id FROM users WHERE id = ?", (target_user_id,)).fetchone()
            if not target:
                raise LookupError("Participant not found")
            is_parent = target["parent_id"] is not None and target["parent_id"] == actor["id"]
            if not (is_parent or actor.get("role") == "organiser"):
                raise PermissionError("You can only change draw inclusion for your own children")
            _ensure_draw_not_active(conn, "change who is in the draw")
            conn.execute("UPDATE users SET in_draw = ? WHERE id = ?", (1 if in_draw else 0, target_user_id))
    finally:
        conn.close()
    return get_user(target_user_id, db_path=db_path)


def get_event_settings(db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM event_settings WHERE id = 1").fetchone()
    finally:
        conn.close()
    return dict(row) if row else {
        "id": 1,
        "event_name": "Family Secret Santa",
        "budget_limit": "$25 - $50",
        "reveal_date": "",
        "rules_note": "",
        "is_drawn": 0,
        "drawn_at": None,
        "avoid_household": 1
    }


def update_event_settings(event_name: str, budget_limit: str, reveal_date: str, rules_note: str,
                          avoid_household: Optional[bool] = None, db_path: Optional[str] = None):
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE event_settings
                SET event_name = ?, budget_limit = ?, reveal_date = ?, rules_note = ?
                WHERE id = 1
                """,
                (event_name.strip(), budget_limit.strip(), reveal_date.strip(), rules_note.strip())
            )
            if avoid_household is not None:
                conn.execute(
                    "UPDATE event_settings SET avoid_household = ? WHERE id = 1",
                    (1 if avoid_household else 0,)
                )
    finally:
        conn.close()


class _SearchBudgetExceeded(Exception):
    pass


def _find_gift_cycle(participants: List[sqlite3.Row], avoid_household: bool,
                     rng: secrets.SystemRandom, max_steps: int = 200_000) -> Optional[List[int]]:
    """
    Randomised backtracking search for a single Hamiltonian cycle over the participants
    such that each giver -> receiver edge satisfies the draw rules:
      * a child never gives to the parent who manages them (the parent would see their own Santa)
      * if avoid_household: nobody gives to someone in their own household
        (household = a parent account plus the children it manages)
    Returns the ordered cycle of ids, or None if no valid cycle exists / was found.
    """
    household = {p["id"]: (p["parent_id"] if p["parent_id"] is not None else p["id"]) for p in participants}
    parent_of = {p["id"]: p["parent_id"] for p in participants}

    def allowed(giver: int, receiver: int) -> bool:
        if giver == receiver or parent_of[giver] == receiver:
            return False
        if avoid_household and household[giver] == household[receiver]:
            return False
        return True

    ids = [p["id"] for p in participants]
    rng.shuffle(ids)
    n = len(ids)
    start = ids[0]
    path = [start]
    unused = set(ids[1:])
    remaining_per_house: Dict[int, int] = {}
    for pid in unused:
        remaining_per_house[household[pid]] = remaining_per_house.get(household[pid], 0) + 1
    steps = 0

    def still_feasible() -> bool:
        # Each remaining member of a household needs a non-household separator
        # between them on the rest of the cycle: 2k <= |unused| + 1.
        if not avoid_household:
            return True
        size = len(unused)
        return all(2 * k <= size + 1 for k in remaining_per_house.values())

    def extend() -> bool:
        nonlocal steps
        steps += 1
        if steps > max_steps:
            raise _SearchBudgetExceeded()
        current = path[-1]
        if len(path) == n:
            return allowed(current, start)
        candidates = [c for c in unused if allowed(current, c)]
        rng.shuffle(candidates)
        for c in candidates:
            path.append(c)
            unused.discard(c)
            remaining_per_house[household[c]] -= 1
            if still_feasible() and extend():
                return True
            remaining_per_house[household[c]] += 1
            unused.add(c)
            path.pop()
        return False

    try:
        return path if extend() else None
    except _SearchBudgetExceeded:
        return None


def perform_secret_santa_draw(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Randomly assigns Secret Santa recipients in a single closed Hamiltonian cycle:
    User[0] -> User[1] -> User[2] -> ... -> User[n-1] -> User[0]
    Only users (adults and children) with in_draw = 1 take part.
    This guarantees:
    1. Perfect derangement: Nobody gets themselves.
    2. Exactly one gift given and one gift received per person.
    3. No isolated 2-person loops (unless n=2).
    4. A child is never assigned to their own parent (and, when the event's
       avoid_household setting is on, nobody is matched within their household).
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            participants = conn.execute(
                "SELECT id, display_name, parent_id FROM users WHERE in_draw = 1"
            ).fetchall()
            n = len(participants)
            if n < 2:
                raise ValueError("At least 2 participants are required to draw Secret Santa names.")

            settings = conn.execute("SELECT avoid_household FROM event_settings WHERE id = 1").fetchone()
            avoid_household = bool(settings["avoid_household"]) if settings else True

            if avoid_household:
                sizes: Dict[int, int] = {}
                for p in participants:
                    h = p["parent_id"] if p["parent_id"] is not None else p["id"]
                    sizes[h] = sizes.get(h, 0) + 1
                if max(sizes.values()) * 2 > n:
                    raise ValueError(
                        "One household makes up more than half of the draw, so households can't be kept apart. "
                        "Add more participants, exclude some children, or turn off 'Keep households apart'."
                    )

            # Cryptographically secure randomness; retry a few times with fresh shuffles
            rng = secrets.SystemRandom()
            cycle = None
            for _ in range(5):
                cycle = _find_gift_cycle(participants, avoid_household, rng)
                if cycle:
                    break
            if not cycle:
                raise ValueError(
                    "Couldn't find a valid draw with the current participants and rules "
                    "(children can't be assigned their own parent). Try including more people."
                )

            # Clear existing assignments if any
            conn.execute("DELETE FROM assignments")

            # Create cycle
            now = datetime.now(timezone.utc).isoformat()
            assignments = []
            for i in range(n):
                giver = cycle[i]
                receiver = cycle[(i + 1) % n]
                assignments.append((giver, receiver, now))

            conn.executemany(
                "INSERT INTO assignments (giver_id, receiver_id, assigned_at) VALUES (?, ?, ?)",
                assignments
            )

            conn.execute(
                "UPDATE event_settings SET is_drawn = 1, drawn_at = ? WHERE id = 1",
                (now,)
            )
    finally:
        conn.close()

    return {"status": "success", "participant_count": n, "drawn_at": now}


def reset_secret_santa_draw(db_path: Optional[str] = None):
    """Resets the draw so organiser can re-run if needed."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM assignments")
            conn.execute("UPDATE event_settings SET is_drawn = 0, drawn_at = NULL WHERE id = 1")
    finally:
        conn.close()


def get_user_assignment(user_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT a.assigned_at, u.id as receiver_id, u.username as receiver_username,
                   u.display_name as receiver_display_name,
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM assignments a
            JOIN users u ON a.receiver_id = u.id
            WHERE a.giver_id = ?
            """,
            (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_children_assignments(parent_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Assignments for every child a parent manages, so the parent can shop on their behalf."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.id as child_id, c.display_name as child_display_name,
                   a.assigned_at, u.id as receiver_id, u.display_name as receiver_display_name,
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM users c
            JOIN assignments a ON a.giver_id = c.id
            JOIN users u ON a.receiver_id = u.id
            WHERE c.parent_id = ?
            ORDER BY c.display_name ASC
            """,
            (parent_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ==========================================
# Wishlist & Secret Purchase Logic
# ==========================================

def get_wishlist(target_user_id: int, viewer_user_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    is_owner = (target_user_id == viewer_user_id)
    conn = get_db_connection(db_path)
    try:
        if is_owner:
            # Strict privacy: Owner never sees purchase table data
            rows = conn.execute(
                """
                SELECT id, user_id, title, description, url, price, priority, created_at, updated_at
                FROM wishlist_items
                WHERE user_id = ?
                ORDER BY priority DESC, created_at DESC
                """,
                (target_user_id,)
            ).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                d["is_purchased"] = None  # Hidden from owner
                d["is_bought_by_viewer"] = False
                d["buyer_name"] = None
                items.append(d)
            return items
        else:
            # Non-owners can see if an item is already purchased
            rows = conn.execute(
                """
                SELECT w.id, w.user_id, w.title, w.description, w.url, w.price, w.priority,
                       w.created_at, w.updated_at,
                       (p.item_id IS NOT NULL) as is_purchased,
                       p.buyer_id,
                       p.purchased_at,
                       u.display_name as buyer_name
                FROM wishlist_items w
                LEFT JOIN purchases p ON w.id = p.item_id
                LEFT JOIN users u ON p.buyer_id = u.id
                WHERE w.user_id = ?
                ORDER BY priority DESC, w.created_at DESC
                """,
                (target_user_id,)
            ).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                d["is_purchased"] = bool(d["is_purchased"])
                d["is_bought_by_viewer"] = (d["buyer_id"] == viewer_user_id)
                items.append(d)
            return items
    finally:
        conn.close()


def add_wishlist_item(user_id: int, title: str, description: str = "", url: str = "", price: str = "", priority: int = 1, db_path: Optional[str] = None) -> Dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Title is required for wishlist item")

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO wishlist_items (user_id, title, description, url, price, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, clean_title, description.strip(), url.strip(), price.strip(), int(priority), now, now)
            )
            item_id = cur.lastrowid
    finally:
        conn.close()

    return {
        "id": item_id,
        "user_id": user_id,
        "title": clean_title,
        "description": description.strip(),
        "url": url.strip(),
        "price": price.strip(),
        "priority": int(priority),
        "created_at": now,
        "updated_at": now,
        "is_purchased": None,
        "is_bought_by_viewer": False
    }


def update_wishlist_item(item_id: int, user_id: int, title: str, description: str = "", url: str = "", price: str = "", priority: int = 1, db_path: Optional[str] = None) -> bool:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Title is required")

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                UPDATE wishlist_items
                SET title = ?, description = ?, url = ?, price = ?, priority = ?, updated_at = ?
                WHERE id = ? AND user_id IN (SELECT id FROM users WHERE id = ? OR parent_id = ?)
                """,
                (clean_title, description.strip(), url.strip(), price.strip(), int(priority), now, item_id, user_id, user_id)
            )
            updated = (cur.rowcount > 0)
    finally:
        conn.close()
    return updated


def delete_wishlist_item(item_id: int, user_id: int, db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM wishlist_items WHERE id = ? AND user_id IN (SELECT id FROM users WHERE id = ? OR parent_id = ?)",
                (item_id, user_id, user_id)
            )
            deleted = (cur.rowcount > 0)
    finally:
        conn.close()
    return deleted


def toggle_purchase_item(item_id: int, buyer_user_id: int, db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    try:
        with conn:
            item = conn.execute("SELECT id, user_id, title FROM wishlist_items WHERE id = ?", (item_id,)).fetchone()
            if not item:
                raise ValueError("Wishlist item not found")

            if item['user_id'] == buyer_user_id:
                raise ValueError("You cannot mark your own wishlist items as purchased!")

            existing = conn.execute("SELECT item_id, buyer_id FROM purchases WHERE item_id = ?", (item_id,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()

            if existing:
                if existing['buyer_id'] != buyer_user_id:
                    buyer = conn.execute("SELECT display_name FROM users WHERE id = ?", (existing['buyer_id'],)).fetchone()
                    buyer_name = buyer['display_name'] if buyer else "someone else"
                    raise ValueError(f"This item has already been marked as purchased by {buyer_name}.")
                else:
                    conn.execute("DELETE FROM purchases WHERE item_id = ?", (item_id,))
                    status = "unmarked"
                    is_purchased = False
            else:
                conn.execute(
                    "INSERT INTO purchases (item_id, buyer_id, purchased_at) VALUES (?, ?, ?)",
                    (item_id, buyer_user_id, now)
                )
                status = "purchased"
                is_purchased = True
    finally:
        conn.close()

    return {
        "status": status,
        "item_id": item_id,
        "is_purchased": is_purchased
    }
