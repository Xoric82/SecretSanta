"""
Secret Santa Application Web Server.
Zero-dependency, multi-threaded HTTP server using Python standard library.
Serves modern web frontend and provides secure REST API.
"""

import os
import sys
import json
import secrets
import urllib.parse
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
import database as db

db.load_env_file()

PORT = int(os.environ.get("PORT", "8082"))
HOST = os.environ.get("HOST", "0.0.0.0")
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "public"))


def get_registration_passphrase() -> str:
    return os.environ.get("REGISTRATION_PASSPHRASE", "").strip()


SESSION_MAX_AGE = 30 * 24 * 60 * 60

# While must_change_password is set, a session may only use these endpoints.
PASSWORD_CHANGE_ALLOWED_PATHS = {"/api/me", "/api/logout", "/api/account/password"}


def cookie_secure_mode() -> str:
    """COOKIE_SECURE: 'auto' (default) = Secure when the request arrived over HTTPS
    (X-Forwarded-Proto from Caddy / Nginx Proxy Manager); 'true' = always; 'false' = never."""
    return os.environ.get("COOKIE_SECURE", "auto").strip().lower()

def parse_priority(value) -> int:
    try:
        return 2 if int(value) == 2 else 1
    except (TypeError, ValueError):
        return 1


def parse_id_path(path: str, prefix: str, suffix: str = ""):
    """Returns the integer id from paths like '<prefix><id><suffix>', else None."""
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    middle = path[len(prefix):len(path) - len(suffix)] if suffix else path[len(prefix):]
    return int(middle) if middle.isdigit() else None


MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
}


class SecretSantaRequestHandler(BaseHTTPRequestHandler):
    server_version = "SecretSanta/1.0"

    def end_headers(self):
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def get_session_token(self) -> str:
        # Check Cookie header
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            cookie = SimpleCookie()
            try:
                cookie.load(cookie_header)
                if "session_token" in cookie:
                    return cookie["session_token"].value
            except Exception:
                pass

        # Check Authorization header (Bearer token)
        auth_header = self.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        return ""

    def get_current_user(self):
        token = self.get_session_token()
        if not token:
            return None
        return db.get_user_from_session(token)

    def read_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return {}
            body = self.rfile.read(content_length)
            parsed = json.loads(body.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def is_https_request(self) -> bool:
        mode = cookie_secure_mode()
        if mode in ("true", "1", "yes"):
            return True
        if mode in ("false", "0", "no"):
            return False
        proto = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        return proto == "https"

    def cookie_attributes(self) -> str:
        attrs = "Path=/; HttpOnly; SameSite=Lax"
        if self.is_https_request():
            attrs += "; Secure"
        return attrs

    def send_json(self, data, status=HTTPStatus.OK, cookie_token=None, delete_cookie=False):
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        # API responses carry per-user secrets (assignments, purchases): never cache
        self.send_header("Cache-Control", "no-store")

        if cookie_token:
            self.send_header(
                "Set-Cookie",
                f"session_token={cookie_token}; {self.cookie_attributes()}; Max-Age={SESSION_MAX_AGE}"
            )
        elif delete_cookie:
            self.send_header(
                "Set-Cookie",
                f"session_token=; {self.cookie_attributes()}; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )

        self.end_headers()
        self.wfile.write(response_bytes)

    def send_error_json(self, message: str, status=HTTPStatus.BAD_REQUEST, **extra):
        self.send_json({"error": message, **extra}, status=status)

    def require_user(self, path: str):
        """Returns the signed-in user, or sends 401/403 and returns None."""
        user = self.get_current_user()
        if not user:
            self.send_error_json("Authentication required", HTTPStatus.UNAUTHORIZED)
            return None
        if user.get("must_change_password") and path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            self.send_error_json(
                "You must choose a new password before continuing.",
                HTTPStatus.FORBIDDEN, code="password_change_required"
            )
            return None
        return user

    def require_organiser(self, user) -> bool:
        if user["role"] != "organiser":
            self.send_error_json("Only the organiser can do that", HTTPStatus.FORBIDDEN)
            return False
        return True

    def serve_static(self, file_path: str):
        # Resolve normalized path
        rel_path = file_path.lstrip("/")
        if not rel_path or rel_path == "":
            rel_path = "index.html"

        full_path = os.path.abspath(os.path.join(PUBLIC_DIR, rel_path))

        # Prevent directory traversal attacks
        if not full_path.startswith(PUBLIC_DIR):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return

        if os.path.isdir(full_path):
            full_path = os.path.join(full_path, "index.html")

        if not os.path.isfile(full_path):
            # For SPA navigation fallback: if file not found and doesn't look like static asset, serve index.html
            ext = os.path.splitext(rel_path)[1]
            if not ext:
                index_path = os.path.join(PUBLIC_DIR, "index.html")
                if os.path.isfile(index_path):
                    full_path = index_path
                else:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

        ext = os.path.splitext(full_path)[1].lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            # Do not cache HTML, JS, or CSS to ensure client updates are applied immediately
            if ext in (".html", ".js", ".css"):
                self.send_header("Cache-Control", "no-cache, must-revalidate")
            else:
                self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    # ==========================================
    # HTTP METHOD DISPATCHERS
    # ==========================================

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        if path.startswith("/api/"):
            self.handle_api_get(path, urllib.parse.parse_qs(parsed.query))
        else:
            self.serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/"):
            self.handle_api_post(path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/"):
            self.handle_api_put(path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/"):
            self.handle_api_delete(path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    # ==========================================
    # API ROUTE HANDLERS
    # ==========================================

    def handle_api_get(self, path: str, query_params: dict):
        # /api/me
        if path == "/api/me":
            requires_code = bool(get_registration_passphrase())
            user = self.get_current_user()
            if not user:
                self.send_json({
                    "user": None,
                    "assignment": None,
                    "event": db.get_event_settings(),
                    "requires_registration_code": requires_code
                })
                return

            event = db.get_event_settings()
            assignment = db.get_user_assignment(user["id"]) if event["is_drawn"] else None
            children_assignments = db.get_children_assignments(user["id"]) if event["is_drawn"] else []
            self.send_json({
                "user": user,
                "assignment": assignment,
                "children": db.get_children(user["id"]),
                "children_assignments": children_assignments,
                "event": event,
                "requires_registration_code": requires_code
            })
            return

        # /api/event (participant list only for signed-in family members)
        if path == "/api/event":
            current_user = self.get_current_user()
            participants = []
            if current_user and not current_user.get("must_change_password"):
                participants = db.get_all_users()
                if current_user["role"] == "organiser":
                    security = db.get_security_status()
                    for p in participants:
                        if p["id"] in security:
                            p["security"] = security[p["id"]]
            self.send_json({
                "event": db.get_event_settings(),
                "participants": participants,
                "requires_registration_code": bool(get_registration_passphrase())
            })
            return

        # Authentication required for remaining endpoints
        current_user = self.require_user(path)
        if not current_user:
            return

        # /api/wishlists (List all participants for wishlist navigation)
        if path == "/api/wishlists":
            self.send_json({"users": db.get_all_users()})
            return

        # /api/children (Child profiles managed by the current user)
        if path == "/api/children":
            self.send_json({"children": db.get_children(current_user["id"])})
            return

        # /api/wishlist/<user_id>
        target_user_id = parse_id_path(path, "/api/wishlist/")
        if target_user_id is not None:
            viewer_id = current_user["id"]
            target_user = db.get_user(target_user_id)
            if not target_user:
                self.send_error_json("User not found", HTTPStatus.NOT_FOUND)
                return

            items = db.get_wishlist(target_user_id, viewer_user_id=viewer_id)
            self.send_json({
                "user": {
                    "id": target_user["id"],
                    "username": target_user["username"],
                    "display_name": target_user["display_name"],
                    "role": target_user["role"],
                    "is_child": target_user["is_child"],
                    "parent_id": target_user["parent_id"],
                    "parent_display_name": target_user["parent_display_name"],
                    "in_draw": target_user["in_draw"]
                },
                "is_owner": (viewer_id == target_user_id),
                # Parents can add/edit/delete items on their children's lists
                "can_manage": (target_user["parent_id"] == viewer_id) or (viewer_id == target_user_id),
                "items": items
            })
            return

        self.send_error_json("Not Found", HTTPStatus.NOT_FOUND)

    def handle_api_post(self, path: str):
        data = self.read_json_body()
        if data is None:
            self.send_error_json("Invalid JSON request body")
            return

        # /api/register
        if path == "/api/register":
            required_passphrase = get_registration_passphrase()
            if required_passphrase:
                provided_code = str(data.get("registration_code", "")).strip()
                if not secrets.compare_digest(provided_code, required_passphrase):
                    self.send_error_json(
                        "Invalid family registration passcode. Please ask the organiser for the invite code.",
                        HTTPStatus.FORBIDDEN
                    )
                    return

            username = data.get("username", "")
            display_name = data.get("display_name", "")
            password = data.get("password", "")
            try:
                user = db.create_user(username, display_name, password)
                token = db.create_session(user["id"])
                # The token travels only in the HttpOnly cookie, never in a JS-readable body
                self.send_json({
                    "status": "success",
                    "user": user
                }, status=HTTPStatus.CREATED, cookie_token=token)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/login
        if path == "/api/login":
            username = data.get("username", "")
            password = data.get("password", "")
            if not isinstance(username, str) or not isinstance(password, str):
                self.send_error_json("Invalid username or password", HTTPStatus.UNAUTHORIZED)
                return
            try:
                user = db.authenticate_user(username, password)
            except db.AccountLockedError as e:
                self.send_error_json(str(e), HTTPStatus.TOO_MANY_REQUESTS,
                                     code="account_locked", minutes_remaining=e.minutes_remaining)
                return
            if not user:
                self.send_error_json("Invalid username or password", HTTPStatus.UNAUTHORIZED)
                return
            token = db.create_session(user["id"])
            db.purge_expired_sessions()
            self.send_json({
                "status": "success",
                "user": user
            }, cookie_token=token)
            return

        # /api/logout
        if path == "/api/logout":
            token = self.get_session_token()
            if token:
                db.delete_session(token)
            self.send_json({"status": "success"}, delete_cookie=True)
            return

        # Authentication required for remaining endpoints
        current_user = self.require_user(path)
        if not current_user:
            return

        # /api/account/password (Change own password; forced after an organiser reset)
        if path == "/api/account/password":
            new_password = data.get("new_password", "")
            current_password = data.get("current_password")
            if not isinstance(new_password, str) or (current_password is not None and not isinstance(current_password, str)):
                self.send_error_json("Invalid request")
                return
            # After an organiser reset the user has just signed in with the temporary
            # password, so we don't ask for it again. Otherwise the current password is required.
            if not current_user["must_change_password"] and current_password is None:
                self.send_error_json("Current password is required")
                return
            try:
                db.change_password(
                    current_user["id"], new_password,
                    current_password=None if current_user["must_change_password"] else current_password,
                    keep_session_token=self.get_session_token()
                )
                self.send_json({"status": "success", "user": db.get_user_from_session(self.get_session_token())})
            except PermissionError as e:
                self.send_error_json(str(e), HTTPStatus.FORBIDDEN)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/admin/users/<id>/reset-password and /unlock (Organiser only)
        reset_id = parse_id_path(path, "/api/admin/users/", "/reset-password")
        unlock_id = parse_id_path(path, "/api/admin/users/", "/unlock")
        if reset_id is not None or unlock_id is not None:
            if not self.require_organiser(current_user):
                return
            target_id = reset_id if reset_id is not None else unlock_id
            target = db.get_user(target_id)
            if not target or target["is_child"]:
                self.send_error_json("User not found", HTTPStatus.NOT_FOUND)
                return
            if reset_id is not None:
                if target_id == current_user["id"]:
                    self.send_error_json("Use 'Change password' on your account page to change your own password")
                    return
                temp = db.admin_reset_password(target_id)
                self.send_json({
                    "status": "success",
                    "user_id": target_id,
                    "display_name": target["display_name"],
                    "username": target["username"],
                    "temporary_password": temp
                })
            else:
                db.unlock_user(target_id)
                self.send_json({"status": "success", "user_id": target_id})
            return

        # /api/event/update (Organiser only)
        if path == "/api/event/update":
            if current_user["role"] != "organiser":
                self.send_error_json("Only organisers can update event settings", HTTPStatus.FORBIDDEN)
                return
            event_name = data.get("event_name", "Family Secret Santa")
            budget_limit = data.get("budget_limit", "")
            reveal_date = data.get("reveal_date", "")
            rules_note = data.get("rules_note", "")
            avoid_household = data.get("avoid_household")
            db.update_event_settings(
                event_name, budget_limit, reveal_date, rules_note,
                avoid_household=None if avoid_household is None else bool(avoid_household)
            )
            self.send_json({"status": "success", "event": db.get_event_settings()})
            return

        # /api/draw (Organiser only)
        if path == "/api/draw":
            if current_user["role"] != "organiser":
                self.send_error_json("Only the organiser can trigger the Secret Santa draw", HTTPStatus.FORBIDDEN)
                return
            if db.get_event_settings()["is_drawn"]:
                self.send_error_json("Names have already been drawn. Reset the draw first to re-shuffle.", HTTPStatus.CONFLICT)
                return
            try:
                res = db.perform_secret_santa_draw()
                self.send_json(res)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/draw/reset (Organiser only)
        if path == "/api/draw/reset":
            if current_user["role"] != "organiser":
                self.send_error_json("Only the organiser can reset the draw", HTTPStatus.FORBIDDEN)
                return
            db.reset_secret_santa_draw()
            self.send_json({"status": "success", "message": "Draw has been reset."})
            return

        # /api/children (Create a child profile under the current login)
        if path == "/api/children":
            try:
                child = db.create_child(
                    current_user["id"],
                    str(data.get("display_name", "")),
                    in_draw=bool(data.get("in_draw", True))
                )
                self.send_json(child, status=HTTPStatus.CREATED)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/users/<id>/draw (Include/exclude from draw: parent for own children, organiser for anyone)
        target_id = parse_id_path(path, "/api/users/", "/draw")
        if target_id is not None:
            if not isinstance(data.get("in_draw"), bool):
                self.send_error_json("'in_draw' must be true or false")
                return
            try:
                user = db.set_draw_inclusion(current_user, target_id, data["in_draw"])
                self.send_json({"status": "success", "user": user})
            except LookupError as e:
                self.send_error_json(str(e), HTTPStatus.NOT_FOUND)
            except PermissionError as e:
                self.send_error_json(str(e), HTTPStatus.FORBIDDEN)
            except ValueError as e:
                self.send_error_json(str(e), HTTPStatus.CONFLICT)
            return

        # /api/wishlist (Add item to own wishlist, or to a managed child's wishlist via user_id)
        if path == "/api/wishlist":
            title = str(data.get("title", ""))
            description = str(data.get("description", ""))
            url = str(data.get("url", ""))
            price = str(data.get("price", ""))
            priority = parse_priority(data.get("priority", 1))
            owner_id = data.get("user_id") or current_user["id"]
            if isinstance(owner_id, bool) or not isinstance(owner_id, int) or not db.can_manage(current_user["id"], owner_id):
                self.send_error_json("You can only add items to your own or your children's wishlists", HTTPStatus.FORBIDDEN)
                return
            try:
                item = db.add_wishlist_item(
                    owner_id, title, description, url, price, priority
                )
                self.send_json(item, status=HTTPStatus.CREATED)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/wishlist/<item_id>/purchase (Toggle purchase of someone else's item)
        if path.startswith("/api/wishlist/") and path.endswith("/purchase"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                item_id = int(parts[3])
                try:
                    res = db.toggle_purchase_item(item_id, current_user["id"])
                    self.send_json(res)
                except ValueError as e:
                    self.send_error_json(str(e))
                return

        self.send_error_json("Not Found", HTTPStatus.NOT_FOUND)

    def handle_api_put(self, path: str):
        current_user = self.require_user(path)
        if not current_user:
            return

        data = self.read_json_body()
        if data is None:
            self.send_error_json("Invalid JSON request body")
            return

        # /api/children/<id> (Rename a child profile)
        child_id = parse_id_path(path, "/api/children/")
        if child_id is not None:
            try:
                if db.rename_child(current_user["id"], child_id, str(data.get("display_name", ""))):
                    self.send_json({"status": "success", "child": db.get_user(child_id)})
                else:
                    self.send_error_json("Child not found", HTTPStatus.NOT_FOUND)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/wishlist/<item_id>
        if path.startswith("/api/wishlist/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                item_id = int(parts[3])
                title = str(data.get("title", ""))
                description = str(data.get("description", ""))
                url = str(data.get("url", ""))
                price = str(data.get("price", ""))
                priority = parse_priority(data.get("priority", 1))
                try:
                    updated = db.update_wishlist_item(
                        item_id, current_user["id"], title, description, url, price, priority
                    )
                    if updated:
                        self.send_json({"status": "success", "item_id": item_id})
                    else:
                        self.send_error_json("Item not found or you are not authorized to edit it", HTTPStatus.FORBIDDEN)
                except ValueError as e:
                    self.send_error_json(str(e))
                return

        self.send_error_json("Not Found", HTTPStatus.NOT_FOUND)

    def handle_api_delete(self, path: str):
        current_user = self.require_user(path)
        if not current_user:
            return

        # /api/children/<id> (Remove a child profile and their wishlist)
        child_id = parse_id_path(path, "/api/children/")
        if child_id is not None:
            try:
                if db.delete_child(current_user["id"], child_id):
                    self.send_json({"status": "success", "deleted_child_id": child_id})
                else:
                    self.send_error_json("Child not found", HTTPStatus.NOT_FOUND)
            except ValueError as e:
                self.send_error_json(str(e), HTTPStatus.CONFLICT)
            return

        # /api/wishlist/<item_id>
        if path.startswith("/api/wishlist/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                item_id = int(parts[3])
                deleted = db.delete_wishlist_item(item_id, current_user["id"])
                if deleted:
                    self.send_json({"status": "success", "deleted_item_id": item_id})
                else:
                    self.send_error_json("Item not found or you are not authorized to delete it", HTTPStatus.FORBIDDEN)
                return

        self.send_error_json("Not Found", HTTPStatus.NOT_FOUND)


def run_server(host=HOST, port=PORT):
    db.init_db()
    purged = db.purge_expired_sessions()
    if purged:
        print(f"Removed {purged} expired session(s)")
    server = ThreadingHTTPServer((host, port), SecretSantaRequestHandler)
    print(f"🎄 Secret Santa server running at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
