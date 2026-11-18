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
    finally:
        conn.close()


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
    if not password or len(password) < 4:
        raise ValueError("Password must be at least 4 characters long")

    conn = get_db_connection(db_path)
    try:
        with conn:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
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
        "role": role
    }


def authenticate_user(username: str, password: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    clean_username = username.strip().lower()
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, username, display_name, password_hash, salt, role FROM users WHERE username = ?",
            (clean_username,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    if verify_password(password, row['salt'], row['password_hash']):
        return {
            "id": row['id'],
            "username": row['username'],
            "display_name": row['display_name'],
            "role": row['role']
        }
    return None


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
            SELECT u.id, u.username, u.display_name, u.role, s.expires_at
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

    return {
        "id": row['id'],
        "username": row['username'],
        "display_name": row['display_name'],
        "role": row['role']
    }


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
                   (SELECT COUNT(*) FROM wishlist_items w WHERE w.user_id = u.id) as wishlist_count
            FROM users u
            ORDER BY u.display_name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


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
        "drawn_at": None
    }


def update_event_settings(event_name: str, budget_limit: str, reveal_date: str, rules_note: str, db_path: Optional[str] = None):
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
    finally:
        conn.close()


def perform_secret_santa_draw(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Randomly assigns Secret Santa recipients in a single closed Hamiltonian cycle:
    User[0] -> User[1] -> User[2] -> ... -> User[n-1] -> User[0]
    This guarantees:
    1. Perfect derangement: Nobody gets themselves.
    2. Exactly one gift given and one gift received per person.
    3. No isolated 2-person loops (unless n=2).
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            users = conn.execute("SELECT id, display_name FROM users").fetchall()
            user_ids = [u['id'] for u in users]
            n = len(user_ids)
            if n < 2:
                raise ValueError("At least 2 participants are required to draw Secret Santa names.")

            # Cryptographically secure shuffle
            rng = secrets.SystemRandom()
            shuffled = list(user_ids)
            rng.shuffle(shuffled)

            # Clear existing assignments if any
            conn.execute("DELETE FROM assignments")

            # Create cycle
            now = datetime.now(timezone.utc).isoformat()
            assignments = []
            for i in range(n):
                giver = shuffled[i]
                receiver = shuffled[(i + 1) % n]
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
                WHERE id = ? AND user_id = ?
                """,
                (clean_title, description.strip(), url.strip(), price.strip(), int(priority), now, item_id, user_id)
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
                "DELETE FROM wishlist_items WHERE id = ? AND user_id = ?",
                (item_id, user_id)
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
