"""
Secret Santa Application Web Server.
Zero-dependency, multi-threaded HTTP server using Python standard library.
Serves modern web frontend and provides secure REST API.
"""

import os
import sys
import json
import urllib.parse
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
import database as db

PORT = int(os.environ.get("PORT", "8082"))
HOST = os.environ.get("HOST", "0.0.0.0")
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "public"))

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
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def send_json(self, data, status=HTTPStatus.OK, cookie_token=None, delete_cookie=False):
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))

        if cookie_token:
            # 30 days expiration
            self.send_header(
                "Set-Cookie",
                f"session_token={cookie_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            )
        elif delete_cookie:
            self.send_header(
                "Set-Cookie",
                "session_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )

        self.end_headers()
        self.wfile.write(response_bytes)

    def send_error_json(self, message: str, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status=status)

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
            # Cache static assets slightly for performance, but no-cache for index.html
            if ext == ".html":
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "public, max-age=3600")
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
            user = self.get_current_user()
            if not user:
                self.send_json({"user": None, "assignment": None, "event": db.get_event_settings()})
                return

            event = db.get_event_settings()
            assignment = db.get_user_assignment(user["id"]) if event["is_drawn"] else None
            self.send_json({
                "user": user,
                "assignment": assignment,
                "event": event
            })
            return

        # /api/event
        if path == "/api/event":
            event = db.get_event_settings()
            users = db.get_all_users()
            self.send_json({
                "event": event,
                "participants": users
            })
            return

        # /api/wishlists (List all participants for wishlist navigation)
        if path == "/api/wishlists":
            users = db.get_all_users()
            self.send_json({"users": users})
            return

        # /api/wishlist/<user_id>
        if path.startswith("/api/wishlist/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                target_user_id = int(parts[3])
                current_user = self.get_current_user()
                viewer_id = current_user["id"] if current_user else 0

                # Find user display name
                all_users = db.get_all_users()
                target_user = next((u for u in all_users if u["id"] == target_user_id), None)
                if not target_user:
                    self.send_error_json("User not found", HTTPStatus.NOT_FOUND)
                    return

                items = db.get_wishlist(target_user_id, viewer_user_id=viewer_id)
                self.send_json({
                    "user": {
                        "id": target_user["id"],
                        "username": target_user["username"],
                        "display_name": target_user["display_name"],
                        "role": target_user["role"]
                    },
                    "is_owner": (viewer_id == target_user_id),
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
            username = data.get("username", "")
            display_name = data.get("display_name", "")
            password = data.get("password", "")
            try:
                user = db.create_user(username, display_name, password)
                token = db.create_session(user["id"])
                self.send_json({
                    "status": "success",
                    "user": user,
                    "token": token
                }, status=HTTPStatus.CREATED, cookie_token=token)
            except ValueError as e:
                self.send_error_json(str(e))
            return

        # /api/login
        if path == "/api/login":
            username = data.get("username", "")
            password = data.get("password", "")
            user = db.authenticate_user(username, password)
            if not user:
                self.send_error_json("Invalid username or password", HTTPStatus.UNAUTHORIZED)
                return
            token = db.create_session(user["id"])
            self.send_json({
                "status": "success",
                "user": user,
                "token": token
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
        current_user = self.get_current_user()
        if not current_user:
            self.send_error_json("Authentication required", HTTPStatus.UNAUTHORIZED)
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
            db.update_event_settings(event_name, budget_limit, reveal_date, rules_note)
            self.send_json({"status": "success", "event": db.get_event_settings()})
            return

        # /api/draw (Organiser only)
        if path == "/api/draw":
            if current_user["role"] != "organiser":
                self.send_error_json("Only the organiser can trigger the Secret Santa draw", HTTPStatus.FORBIDDEN)
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

        # /api/wishlist (Add item to own wishlist)
        if path == "/api/wishlist":
            title = data.get("title", "")
            description = data.get("description", "")
            url = data.get("url", "")
            price = data.get("price", "")
            priority = int(data.get("priority", 1))
            try:
                item = db.add_wishlist_item(
                    current_user["id"], title, description, url, price, priority
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
        current_user = self.get_current_user()
        if not current_user:
            self.send_error_json("Authentication required", HTTPStatus.UNAUTHORIZED)
            return

        data = self.read_json_body()
        if data is None:
            self.send_error_json("Invalid JSON request body")
            return

        # /api/wishlist/<item_id>
        if path.startswith("/api/wishlist/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                item_id = int(parts[3])
                title = data.get("title", "")
                description = data.get("description", "")
                url = data.get("url", "")
                price = data.get("price", "")
                priority = int(data.get("priority", 1))
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
        current_user = self.get_current_user()
        if not current_user:
            self.send_error_json("Authentication required", HTTPStatus.UNAUTHORIZED)
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
    server = ThreadingHTTPServer((host, port), SecretSantaRequestHandler)
    print(f"🎄 Secret Santa server running at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
