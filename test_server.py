import unittest
import os
import threading
import urllib.request
import urllib.parse
import json
from http.server import ThreadingHTTPServer
import database as db
from server import SecretSantaRequestHandler

TEST_DB = "test_server.db"
TEST_PORT = 9998
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


class CustomHTTPHandler(SecretSantaRequestHandler):
    pass


class TestSecretSantaServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        db.DB_PATH = TEST_DB
        db.init_db(TEST_DB)

        cls.server = ThreadingHTTPServer(("127.0.0.1", TEST_PORT), CustomHTTPHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def setUp(self):
        # Fresh database per test so "first user becomes organiser" is deterministic
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(TEST_DB + suffix):
                os.remove(TEST_DB + suffix)
        db.init_db(TEST_DB)

    def make_request(self, method: str, endpoint: str, data: dict = None, cookie: str = None, headers: dict = None) -> tuple:
        url = f"{BASE_URL}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", f"session_token={cookie}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read().decode("utf-8")
                cookie_header = resp.headers.get("Set-Cookie", "")
                token = None
                if "session_token=" in cookie_header:
                    token = cookie_header.split("session_token=")[1].split(";")[0]
                return resp.status, json.loads(resp_body) if resp_body else {}, token, resp.headers
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            return e.code, json.loads(err_body) if err_body else {}, None, dict(e.headers)

    def test_full_flow(self):
        # 1. Register Alice (first user -> organiser)
        status, body, alice_token, headers = self.make_request(
            "POST", "/api/register",
            {"username": "alice", "display_name": "Alice", "password": "password123"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["user"]["role"], "organiser")
        self.assertIsNotNone(alice_token)
        self.assertIn("X-Content-Type-Options", headers)

        # 2. Register Bob (second user -> user)
        status, body, bob_token, _ = self.make_request(
            "POST", "/api/register",
            {"username": "bob", "display_name": "Bob", "password": "password123"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["user"]["role"], "user")
        self.assertIsNotNone(bob_token)

        # 3. Register Charlie (user)
        status, body, charlie_token, _ = self.make_request(
            "POST", "/api/register",
            {"username": "charlie", "display_name": "Charlie", "password": "password123"}
        )
        self.assertEqual(status, 201)

        # 4. Check /api/me as Alice
        status, me_alice, _, _ = self.make_request("GET", "/api/me", cookie=alice_token)
        self.assertEqual(status, 200)
        self.assertEqual(me_alice["user"]["username"], "alice")
        self.assertEqual(me_alice["user"]["role"], "organiser")

        # 5. Alice adds wishlist items
        status, item1, _, _ = self.make_request(
            "POST", "/api/wishlist",
            {"title": "Noise Cancelling Headphones", "description": "Over-ear, black", "price": "$70", "priority": 2},
            cookie=alice_token
        )
        self.assertEqual(status, 201)
        self.assertEqual(item1["title"], "Noise Cancelling Headphones")

        status, item2, _, _ = self.make_request(
            "POST", "/api/wishlist",
            {"title": "Scented Candle", "description": "Pine or cinnamon", "price": "$15", "priority": 1},
            cookie=alice_token
        )
        self.assertEqual(status, 201)

        # 6. Alice cannot mark her own item as purchased
        status, err, _, _ = self.make_request(
            "POST", f"/api/wishlist/{item1['id']}/purchase",
            cookie=alice_token
        )
        self.assertEqual(status, 400)
        self.assertIn("cannot mark your own", err["error"])

        # 7. Bob marks Alice's headphones as purchased
        status, purch_res, _, _ = self.make_request(
            "POST", f"/api/wishlist/{item1['id']}/purchase",
            cookie=bob_token
        )
        self.assertEqual(status, 200)
        self.assertEqual(purch_res["status"], "purchased")

        # 8. CRITICAL: Alice views her own wishlist (GET /api/wishlist/<alice_id>)
        # Must NOT reveal purchase status or buyer!
        alice_id = me_alice["user"]["id"]
        status, alice_list, _, _ = self.make_request(
            "GET", f"/api/wishlist/{alice_id}",
            cookie=alice_token
        )
        self.assertEqual(status, 200)
        self.assertTrue(alice_list["is_owner"])
        for item in alice_list["items"]:
            self.assertIsNone(item["is_purchased"], "Owner should never see item purchase state!")
            self.assertFalse(item["is_bought_by_viewer"])
            self.assertIsNone(item["buyer_name"])

        # 9. Bob views Alice's wishlist: sees it is purchased and bought by him
        status, bob_view, _, _ = self.make_request(
            "GET", f"/api/wishlist/{alice_id}",
            cookie=bob_token
        )
        self.assertEqual(status, 200)
        self.assertFalse(bob_view["is_owner"])
        headphones_bob = next(i for i in bob_view["items"] if i["id"] == item1["id"])
        self.assertTrue(headphones_bob["is_purchased"])
        self.assertTrue(headphones_bob["is_bought_by_viewer"])

        # 10. Charlie views Alice's wishlist: sees it is purchased by Bob
        status, charlie_view, _, _ = self.make_request(
            "GET", f"/api/wishlist/{alice_id}",
            cookie=charlie_token
        )
        self.assertEqual(status, 200)
        headphones_charlie = next(i for i in charlie_view["items"] if i["id"] == item1["id"])
        self.assertTrue(headphones_charlie["is_purchased"])
        self.assertFalse(headphones_charlie["is_bought_by_viewer"])
        self.assertEqual(headphones_charlie["buyer_name"], "Bob")

        # 11. Charlie cannot buy an item Bob already bought
        status, err, _, _ = self.make_request(
            "POST", f"/api/wishlist/{item1['id']}/purchase",
            cookie=charlie_token
        )
        self.assertEqual(status, 400)
        self.assertIn("already been marked as purchased by Bob", err["error"])

        # 12. Non-organiser Bob tries to trigger draw -> 403 Forbidden
        status, err, _, _ = self.make_request("POST", "/api/draw", cookie=bob_token)
        self.assertEqual(status, 403)

        # 13. Organiser Alice triggers draw -> 200 Success
        status, draw_res, _, _ = self.make_request("POST", "/api/draw", cookie=alice_token)
        self.assertEqual(status, 200)
        self.assertEqual(draw_res["participant_count"], 3)

        # 14. Check /api/me has assignment
        status, me_bob, _, _ = self.make_request("GET", "/api/me", cookie=bob_token)
        self.assertEqual(status, 200)
        self.assertIsNotNone(me_bob["assignment"])
        self.assertNotEqual(me_bob["user"]["id"], me_bob["assignment"]["receiver_id"])

        # 15. Check Static Assets
        url_root = f"{BASE_URL}/"
        with urllib.request.urlopen(url_root) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/html", r.headers.get("Content-Type"))
            html_content = r.read().decode("utf-8")
            self.assertIn("Family Secret Santa", html_content)
            self.assertIn("dialog id=\"item-dialog\"", html_content)

        url_css = f"{BASE_URL}/css/styles.css"
        with urllib.request.urlopen(url_css) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/css", r.headers.get("Content-Type"))

        url_js = f"{BASE_URL}/js/app.js"
        with urllib.request.urlopen(url_js) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("application/javascript", r.headers.get("Content-Type"))

        url_svg = f"{BASE_URL}/favicon.svg"
        with urllib.request.urlopen(url_svg) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("image/svg+xml", r.headers.get("Content-Type"))

    def test_children_api_and_privacy(self):
        _, p_body, parent_tok, _ = self.make_request(
            "POST", "/api/register", {"username": "pat", "display_name": "Pat", "password": "password123"})
        _, _, other_tok, _ = self.make_request(
            "POST", "/api/register", {"username": "olive", "display_name": "Olive", "password": "password123"})

        # Anonymous users can no longer read wishlists or the participant list
        status, _, _, _ = self.make_request("GET", f"/api/wishlist/{p_body['user']['id']}")
        self.assertEqual(status, 401)
        status, evt, _, _ = self.make_request("GET", "/api/event")
        self.assertEqual(evt["participants"], [])

        # Create children
        status, kid, _, _ = self.make_request(
            "POST", "/api/children", {"display_name": "Kiddo", "in_draw": False}, cookie=parent_tok)
        self.assertEqual(status, 201)
        self.assertTrue(kid["is_child"])
        self.assertFalse(kid["in_draw"])
        status, body, _, _ = self.make_request("GET", "/api/children", cookie=parent_tok)
        self.assertEqual([c["display_name"] for c in body["children"]], ["Kiddo"])
        status, me, _, _ = self.make_request("GET", "/api/me", cookie=parent_tok)
        self.assertEqual(len(me["children"]), 1)

        # Parent adds an item to the child's list; others can't
        status, item, _, _ = self.make_request(
            "POST", "/api/wishlist", {"title": "Bike", "user_id": kid["id"]}, cookie=parent_tok)
        self.assertEqual(status, 201)
        self.assertEqual(item["user_id"], kid["id"])
        status, _, _, _ = self.make_request(
            "POST", "/api/wishlist", {"title": "Spam", "user_id": kid["id"]}, cookie=other_tok)
        self.assertEqual(status, 403)
        status, _, _, _ = self.make_request(
            "PUT", f"/api/wishlist/{item['id']}", {"title": "Hijack"}, cookie=other_tok)
        self.assertEqual(status, 403)
        status, _, _, _ = self.make_request(
            "PUT", f"/api/wishlist/{item['id']}", {"title": "Red Bike", "priority": "oops"}, cookie=parent_tok)
        self.assertEqual(status, 200)

        status, view, _, _ = self.make_request("GET", f"/api/wishlist/{kid['id']}", cookie=parent_tok)
        self.assertTrue(view["can_manage"])
        self.assertFalse(view["is_owner"])
        self.assertTrue(view["user"]["is_child"])
        self.assertEqual(view["items"][0]["title"], "Red Bike")
        status, view, _, _ = self.make_request("GET", f"/api/wishlist/{kid['id']}", cookie=other_tok)
        self.assertFalse(view["can_manage"])

        # Draw inclusion: other user (not organiser, not parent) forbidden; parent allowed
        status, _, _, _ = self.make_request(
            "POST", f"/api/users/{kid['id']}/draw", {"in_draw": True}, cookie=other_tok)
        self.assertEqual(status, 403)
        status, res, _, _ = self.make_request(
            "POST", f"/api/users/{kid['id']}/draw", {"in_draw": True}, cookie=parent_tok)
        self.assertEqual(status, 200)
        self.assertTrue(res["user"]["in_draw"])

        # Rename and delete, scoped to the parent
        status, _, _, _ = self.make_request(
            "PUT", f"/api/children/{kid['id']}", {"display_name": "Nope"}, cookie=other_tok)
        self.assertEqual(status, 404)
        status, res, _, _ = self.make_request(
            "PUT", f"/api/children/{kid['id']}", {"display_name": "Kiddo Jr"}, cookie=parent_tok)
        self.assertEqual(res["child"]["display_name"], "Kiddo Jr")
        status, _, _, _ = self.make_request("DELETE", f"/api/children/{kid['id']}", cookie=other_tok)
        self.assertEqual(status, 404)
        status, _, _, _ = self.make_request("DELETE", f"/api/children/{kid['id']}", cookie=parent_tok)
        self.assertEqual(status, 200)

    def register(self, username):
        status, body, token, headers = self.make_request(
            "POST", "/api/register", {"username": username, "display_name": username.title(), "password": "password123"})
        self.assertEqual(status, 201)
        return body["user"], token, headers

    def test_session_cookie_attributes(self):
        user, token, headers = self.register("alice")
        cookie = headers.get("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie, "Plain-HTTP requests in auto mode must still work")

        # Token is no longer exposed to JavaScript via the response body
        status, body, _, headers = self.make_request(
            "POST", "/api/login", {"username": "alice", "password": "password123"},
            headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        self.assertNotIn("token", body)
        self.assertIn("; Secure", headers.get("Set-Cookie"))
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        # Logout clears the cookie with matching attributes
        status, _, _, headers = self.make_request(
            "POST", "/api/logout", cookie=token, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Max-Age=0", headers.get("Set-Cookie"))
        self.assertIn("; Secure", headers.get("Set-Cookie"))

        os.environ["COOKIE_SECURE"] = "true"
        try:
            _, _, _, headers = self.make_request("POST", "/api/login", {"username": "alice", "password": "password123"})
            self.assertIn("; Secure", headers.get("Set-Cookie"))
        finally:
            os.environ.pop("COOKIE_SECURE", None)

    def test_lockout_and_organiser_unlock(self):
        org, org_tok, _ = self.register("alice")
        bob, bob_tok, _ = self.register("bob")

        for i in range(4):
            status, _, _, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": "nope"})
            self.assertEqual(status, 401)
        status, err, _, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": "nope"})
        self.assertEqual(status, 429)
        self.assertEqual(err["code"], "account_locked")
        status, err, _, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": "password123"})
        self.assertEqual(status, 429)

        # Organiser sees the lock; Bob's own view doesn't include security data
        _, evt, _, _ = self.make_request("GET", "/api/event", cookie=org_tok)
        bob_row = next(p for p in evt["participants"] if p["id"] == bob["id"])
        self.assertTrue(bob_row["security"]["is_locked"])
        _, evt, _, _ = self.make_request("GET", "/api/event", cookie=bob_tok)
        self.assertNotIn("security", evt["participants"][0])

        # Only the organiser can unlock
        status, _, _, _ = self.make_request("POST", f"/api/admin/users/{bob['id']}/unlock", cookie=bob_tok)
        self.assertEqual(status, 403)
        status, _, _, _ = self.make_request("POST", f"/api/admin/users/{bob['id']}/unlock", cookie=org_tok)
        self.assertEqual(status, 200)
        status, _, _, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": "password123"})
        self.assertEqual(status, 200)

    def test_organiser_password_reset_forces_change(self):
        org, org_tok, _ = self.register("alice")
        bob, bob_tok, _ = self.register("bob")

        status, _, _, _ = self.make_request("POST", f"/api/admin/users/{org['id']}/reset-password", cookie=bob_tok)
        self.assertEqual(status, 403)
        status, _, _, _ = self.make_request("POST", f"/api/admin/users/{org['id']}/reset-password", cookie=org_tok)
        self.assertEqual(status, 400, "Organiser can't reset their own password this way")

        status, res, _, _ = self.make_request("POST", f"/api/admin/users/{bob['id']}/reset-password", cookie=org_tok)
        self.assertEqual(status, 200)
        temp = res["temporary_password"]

        # Bob's old session is gone; old password no longer works
        status, me, _, _ = self.make_request("GET", "/api/me", cookie=bob_tok)
        self.assertIsNone(me["user"])
        status, _, _, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": "password123"})
        self.assertEqual(status, 401)

        status, body, tok, _ = self.make_request("POST", "/api/login", {"username": "bob", "password": temp})
        self.assertEqual(status, 200)
        self.assertTrue(body["user"]["must_change_password"])

        # Everything except /api/me, logout and password change is blocked
        status, err, _, _ = self.make_request("GET", "/api/wishlists", cookie=tok)
        self.assertEqual(status, 403)
        self.assertEqual(err["code"], "password_change_required")
        status, _, _, _ = self.make_request("POST", "/api/wishlist", {"title": "x"}, cookie=tok)
        self.assertEqual(status, 403)
        _, evt, _, _ = self.make_request("GET", "/api/event", cookie=tok)
        self.assertEqual(evt["participants"], [])
        status, me, _, _ = self.make_request("GET", "/api/me", cookie=tok)
        self.assertTrue(me["user"]["must_change_password"])

        # Forced change doesn't need the temp password again
        status, res, _, _ = self.make_request(
            "POST", "/api/account/password", {"new_password": "bobs-new-pw"}, cookie=tok)
        self.assertEqual(status, 200)
        self.assertFalse(res["user"]["must_change_password"])
        status, _, _, _ = self.make_request("GET", "/api/wishlists", cookie=tok)
        self.assertEqual(status, 200)

        # Voluntary change requires the current password
        status, _, _, _ = self.make_request(
            "POST", "/api/account/password", {"new_password": "another-pw"}, cookie=tok)
        self.assertEqual(status, 400)
        status, _, _, _ = self.make_request(
            "POST", "/api/account/password", {"current_password": "wrong", "new_password": "another-pw"}, cookie=tok)
        self.assertEqual(status, 403)
        status, _, _, _ = self.make_request(
            "POST", "/api/account/password", {"current_password": "bobs-new-pw", "new_password": "another-pw"}, cookie=tok)
        self.assertEqual(status, 200)

    def test_registration_passphrase(self):
        # Set registration passphrase in environment
        os.environ["REGISTRATION_PASSPHRASE"] = "FamilySecret2026!"
        try:
            # 1. Check /api/event reports requires_registration_code = True
            status, evt_body, _, _ = self.make_request("GET", "/api/event")
            self.assertEqual(status, 200)
            self.assertTrue(evt_body.get("requires_registration_code"))

            # 2. Registration fails without code
            status, err, _, _ = self.make_request(
                "POST", "/api/register",
                {"username": "intruder", "display_name": "Intruder", "password": "password123"}
            )
            self.assertEqual(status, 403)
            self.assertIn("passcode", err["error"])

            # 3. Registration fails with wrong code
            status, err, _, _ = self.make_request(
                "POST", "/api/register",
                {"username": "intruder", "display_name": "Intruder", "password": "password123", "registration_code": "wrongcode"}
            )
            self.assertEqual(status, 403)
            self.assertIn("passcode", err["error"])

            # 4. Registration succeeds with correct code
            status, body, token, _ = self.make_request(
                "POST", "/api/register",
                {"username": "david", "display_name": "David", "password": "password123", "registration_code": "FamilySecret2026!"}
            )
            self.assertEqual(status, 201)
            self.assertEqual(body["user"]["username"], "david")
            self.assertIsNotNone(token)
        finally:
            os.environ.pop("REGISTRATION_PASSPHRASE", None)


if __name__ == "__main__":
    unittest.main()
