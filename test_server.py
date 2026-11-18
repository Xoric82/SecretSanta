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

    def make_request(self, method: str, endpoint: str, data: dict = None, cookie: str = None) -> tuple:
        url = f"{BASE_URL}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", f"session_token={cookie}")

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read().decode("utf-8")
                cookie_header = resp.headers.get("Set-Cookie", "")
                token = None
                if "session_token=" in cookie_header:
                    token = cookie_header.split("session_token=")[1].split(";")[0]
                return resp.status, json.loads(resp_body) if resp_body else {}, token, dict(resp.headers)
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


if __name__ == "__main__":
    unittest.main()
