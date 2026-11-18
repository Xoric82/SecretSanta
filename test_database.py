import unittest
import os
import threading
from datetime import datetime, timezone, timedelta
import database as db

TEST_DB = "test_secretsanta.db"

class TestSecretSantaDatabase(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        db.init_db(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_user_roles_and_auth(self):
        # 1. First user should become organiser
        alice = db.create_user("alice", "Alice Smith", "password123", db_path=TEST_DB)
        self.assertEqual(alice["role"], "organiser")

        # 2. Second user should be standard user
        bob = db.create_user("bob", "Bob Jones", "secret456", db_path=TEST_DB)
        self.assertEqual(bob["role"], "user")

        # 3. Duplicate username should fail
        with self.assertRaises(ValueError):
            db.create_user("Alice", "Another Alice", "pass", db_path=TEST_DB)

        # 4. Authentication
        auth_alice = db.authenticate_user("alice", "password123", db_path=TEST_DB)
        self.assertIsNotNone(auth_alice)
        self.assertEqual(auth_alice["id"], alice["id"])

        auth_fail = db.authenticate_user("alice", "wrongpass", db_path=TEST_DB)
        self.assertIsNone(auth_fail)

        # 5. Session creation & retrieval
        token = db.create_session(alice["id"], db_path=TEST_DB)
        user_sess = db.get_user_from_session(token, db_path=TEST_DB)
        self.assertIsNotNone(user_sess)
        self.assertEqual(user_sess["username"], "alice")

        db.delete_session(token, db_path=TEST_DB)
        self.assertIsNone(db.get_user_from_session(token, db_path=TEST_DB))

    def test_wishlist_and_secret_purchase_privacy(self):
        alice = db.create_user("alice", "Alice", "pass123", db_path=TEST_DB)
        bob = db.create_user("bob", "Bob", "pass123", db_path=TEST_DB)
        charlie = db.create_user("charlie", "Charlie", "pass123", db_path=TEST_DB)

        # Alice creates wishlist items
        item1 = db.add_wishlist_item(alice["id"], "Cozy Slippers", "Size 8, wool", "https://example.com/slippers", "$30", 2, db_path=TEST_DB)
        item2 = db.add_wishlist_item(alice["id"], "Coffee Beans", "Dark roast", "", "$15", 1, db_path=TEST_DB)

        # Alice cannot mark her own item as purchased
        with self.assertRaises(ValueError):
            db.toggle_purchase_item(item1["id"], alice["id"], db_path=TEST_DB)

        # Bob marks Alice's slippers as purchased
        res = db.toggle_purchase_item(item1["id"], bob["id"], db_path=TEST_DB)
        self.assertEqual(res["status"], "purchased")
        self.assertTrue(res["is_purchased"])

        # CRITICAL TEST: Alice (the owner) views her own wishlist
        alice_view = db.get_wishlist(alice["id"], viewer_user_id=alice["id"], db_path=TEST_DB)
        self.assertEqual(len(alice_view), 2)
        for item in alice_view:
            # Owner must NEVER see purchase status or buyer
            self.assertIsNone(item["is_purchased"])
            self.assertFalse(item["is_bought_by_viewer"])
            self.assertIsNone(item["buyer_name"])

        # Bob views Alice's wishlist
        bob_view = db.get_wishlist(alice["id"], viewer_user_id=bob["id"], db_path=TEST_DB)
        slippers_bob = next(i for i in bob_view if i["id"] == item1["id"])
        self.assertTrue(slippers_bob["is_purchased"])
        self.assertTrue(slippers_bob["is_bought_by_viewer"])

        coffee_bob = next(i for i in bob_view if i["id"] == item2["id"])
        self.assertFalse(coffee_bob["is_purchased"])
        self.assertFalse(coffee_bob["is_bought_by_viewer"])

        # Charlie views Alice's wishlist
        charlie_view = db.get_wishlist(alice["id"], viewer_user_id=charlie["id"], db_path=TEST_DB)
        slippers_charlie = next(i for i in charlie_view if i["id"] == item1["id"])
        self.assertTrue(slippers_charlie["is_purchased"])
        self.assertFalse(slippers_charlie["is_bought_by_viewer"])
        self.assertEqual(slippers_charlie["buyer_name"], "Bob")

        # Charlie tries to buy an item Bob already bought -> should raise ValueError
        with self.assertRaises(ValueError):
            db.toggle_purchase_item(item1["id"], charlie["id"], db_path=TEST_DB)

        # Bob unmarks the purchase
        res_unmark = db.toggle_purchase_item(item1["id"], bob["id"], db_path=TEST_DB)
        self.assertEqual(res_unmark["status"], "unmarked")
        self.assertFalse(res_unmark["is_purchased"])

        # Now Charlie can purchase it
        res_charlie = db.toggle_purchase_item(item1["id"], charlie["id"], db_path=TEST_DB)
        self.assertEqual(res_charlie["status"], "purchased")

    def test_secret_santa_draw(self):
        # Fail with 1 user
        alice = db.create_user("alice", "Alice", "pass123", db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.perform_secret_santa_draw(db_path=TEST_DB)

        # Add family members
        users = [alice]
        for name in ["Bob", "Charlie", "Diana", "Evan"]:
            u = db.create_user(name.lower(), name, "pass123", db_path=TEST_DB)
            users.append(u)

        # Perform draw
        result = db.perform_secret_santa_draw(db_path=TEST_DB)
        self.assertEqual(result["participant_count"], 5)

        # Check event state
        event = db.get_event_settings(db_path=TEST_DB)
        self.assertEqual(event["is_drawn"], 1)

        # Verify each user has an assignment and nobody is assigned to themselves
        givers = set()
        receivers = set()
        for u in users:
            assign = db.get_user_assignment(u["id"], db_path=TEST_DB)
            self.assertIsNotNone(assign)
            self.assertNotEqual(u["id"], assign["receiver_id"], f"User {u['display_name']} was assigned themselves!")
            givers.add(u["id"])
            receivers.add(assign["receiver_id"])

        self.assertEqual(len(givers), 5, "Every user must give a gift")
        self.assertEqual(len(receivers), 5, "Every user must receive a gift")

        # Test reset
        db.reset_secret_santa_draw(db_path=TEST_DB)
        event_after_reset = db.get_event_settings(db_path=TEST_DB)
        self.assertEqual(event_after_reset["is_drawn"], 0)
        self.assertIsNone(db.get_user_assignment(alice["id"], db_path=TEST_DB))

        # Test 100 random draws to prove derangement never self-assigns
        for _ in range(100):
            db.perform_secret_santa_draw(db_path=TEST_DB)
            for u in users:
                assign = db.get_user_assignment(u["id"], db_path=TEST_DB)
                self.assertNotEqual(u["id"], assign["receiver_id"])


    def test_child_profiles(self):
        alice = db.create_user("alice", "Alice", "pass123", db_path=TEST_DB)
        bob = db.create_user("bob", "Bob", "pass123", db_path=TEST_DB)

        emma = db.create_child(alice["id"], "Emma", db_path=TEST_DB)
        leo = db.create_child(alice["id"], "Leo", in_draw=False, db_path=TEST_DB)
        self.assertTrue(emma["is_child"])
        self.assertTrue(emma["in_draw"])
        self.assertFalse(leo["in_draw"])
        self.assertIsNone(emma["username"], "Child placeholder usernames must not be exposed")
        self.assertEqual(emma["parent_display_name"], "Alice")
        self.assertEqual([c["display_name"] for c in db.get_children(alice["id"], db_path=TEST_DB)], ["Emma", "Leo"])
        self.assertEqual(db.get_children(bob["id"], db_path=TEST_DB), [])

        # Children are never organisers and can never log in
        self.assertEqual(emma["role"], "user")
        conn = db.get_db_connection(TEST_DB)
        raw_username = conn.execute("SELECT username FROM users WHERE id = ?", (emma["id"],)).fetchone()[0]
        conn.close()
        self.assertIsNone(db.authenticate_user(raw_username, "", db_path=TEST_DB))

        # Children can't have children; empty names rejected
        with self.assertRaises(ValueError):
            db.create_child(emma["id"], "Grandkid", db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.create_child(alice["id"], "   ", db_path=TEST_DB)

        # Management rights
        self.assertTrue(db.can_manage(alice["id"], emma["id"], db_path=TEST_DB))
        self.assertFalse(db.can_manage(bob["id"], emma["id"], db_path=TEST_DB))

        # Parent manages the child's wishlist; others cannot edit it
        item = db.add_wishlist_item(emma["id"], "Lego Set", db_path=TEST_DB)
        self.assertTrue(db.update_wishlist_item(item["id"], alice["id"], "Big Lego Set", db_path=TEST_DB))
        self.assertFalse(db.update_wishlist_item(item["id"], bob["id"], "Hijacked", db_path=TEST_DB))
        self.assertFalse(db.delete_wishlist_item(item["id"], bob["id"], db_path=TEST_DB))

        # Bob buys for Emma; parent Alice can see it (Emma never logs in)
        db.toggle_purchase_item(item["id"], bob["id"], db_path=TEST_DB)
        alice_view = db.get_wishlist(emma["id"], viewer_user_id=alice["id"], db_path=TEST_DB)
        self.assertTrue(alice_view[0]["is_purchased"])

        # Rename / delete, scoped to the parent
        self.assertFalse(db.rename_child(bob["id"], emma["id"], "Nope", db_path=TEST_DB))
        self.assertTrue(db.rename_child(alice["id"], emma["id"], "Emma Rose", db_path=TEST_DB))
        self.assertFalse(db.delete_child(bob["id"], leo["id"], db_path=TEST_DB))
        self.assertTrue(db.delete_child(alice["id"], leo["id"], db_path=TEST_DB))
        self.assertIsNone(db.get_user(leo["id"], db_path=TEST_DB))

        # Draw inclusion permissions
        with self.assertRaises(PermissionError):
            db.set_draw_inclusion(bob, emma["id"], False, db_path=TEST_DB)
        self.assertFalse(db.set_draw_inclusion(alice, emma["id"], False, db_path=TEST_DB)["in_draw"])
        # alice is organiser (first user) so she can toggle adults too
        self.assertFalse(db.set_draw_inclusion(alice, bob["id"], False, db_path=TEST_DB)["in_draw"])

    def test_draw_with_children_respects_inclusion_and_households(self):
        alice = db.create_user("alice", "Alice", "pass123", db_path=TEST_DB)
        bob = db.create_user("bob", "Bob", "pass123", db_path=TEST_DB)
        carol = db.create_user("carol", "Carol", "pass123", db_path=TEST_DB)
        emma = db.create_child(alice["id"], "Emma", db_path=TEST_DB)
        leo = db.create_child(alice["id"], "Leo", in_draw=False, db_path=TEST_DB)
        sam = db.create_child(bob["id"], "Sam", db_path=TEST_DB)

        household = {alice["id"]: alice["id"], emma["id"]: alice["id"],
                     bob["id"]: bob["id"], sam["id"]: bob["id"], carol["id"]: carol["id"]}
        in_draw = set(household)

        for _ in range(50):
            res = db.perform_secret_santa_draw(db_path=TEST_DB)
            self.assertEqual(res["participant_count"], 5)
            self.assertIsNone(db.get_user_assignment(leo["id"], db_path=TEST_DB), "Excluded child must not be drawn")
            receivers = set()
            for uid in in_draw:
                a = db.get_user_assignment(uid, db_path=TEST_DB)
                self.assertIsNotNone(a)
                self.assertNotEqual(household[uid], household[a["receiver_id"]], "Matched within household")
                receivers.add(a["receiver_id"])
            self.assertEqual(receivers, in_draw)
            self.assertNotIn(leo["id"], receivers)

        # Parent can see their children's assignments
        kids = db.get_children_assignments(alice["id"], db_path=TEST_DB)
        self.assertEqual([k["child_id"] for k in kids], [emma["id"]])

        # Changing inclusion / adding drawn children is blocked while the draw is active
        with self.assertRaises(ValueError):
            db.set_draw_inclusion(alice, leo["id"], True, db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.delete_child(alice["id"], emma["id"], db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.create_child(alice["id"], "Newborn", db_path=TEST_DB)
        # ...but adding an excluded child or removing an excluded one is fine
        db.create_child(alice["id"], "Newborn", in_draw=False, db_path=TEST_DB)
        self.assertTrue(db.delete_child(alice["id"], leo["id"], db_path=TEST_DB))

    def test_draw_infeasible_household_and_toggle(self):
        alice = db.create_user("alice", "Alice", "pass123", db_path=TEST_DB)
        bob = db.create_user("bob", "Bob", "pass123", db_path=TEST_DB)
        k1 = db.create_child(alice["id"], "K1", db_path=TEST_DB)
        k2 = db.create_child(alice["id"], "K2", db_path=TEST_DB)

        # Alice's household is 3 of 4 participants -> can't keep households apart
        with self.assertRaises(ValueError):
            db.perform_secret_santa_draw(db_path=TEST_DB)

        # With the household rule off, the draw works but children never draw their parent
        db.update_event_settings("Family", "", "", "", avoid_household=False, db_path=TEST_DB)
        self.assertEqual(db.get_event_settings(db_path=TEST_DB)["avoid_household"], 0)
        for _ in range(50):
            db.perform_secret_santa_draw(db_path=TEST_DB)
            for kid in (k1, k2):
                self.assertNotEqual(db.get_user_assignment(kid["id"], db_path=TEST_DB)["receiver_id"], alice["id"])

        # Parent + single child only: impossible even without the household rule
        db.reset_secret_santa_draw(db_path=TEST_DB)
        db.set_draw_inclusion(alice, bob["id"], False, db_path=TEST_DB)
        db.set_draw_inclusion(alice, k2["id"], False, db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.perform_secret_santa_draw(db_path=TEST_DB)

    def test_migration_from_old_schema(self):
        os.remove(TEST_DB)
        conn = db.get_db_connection(TEST_DB)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL);
            CREATE TABLE event_settings (id INTEGER PRIMARY KEY CHECK (id = 1), event_name TEXT NOT NULL DEFAULT 'x',
                budget_limit TEXT, reveal_date TEXT, rules_note TEXT, is_drawn INTEGER NOT NULL DEFAULT 0, drawn_at TEXT);
            INSERT INTO users (username, display_name, password_hash, salt, role, created_at)
                VALUES ('old', 'Old Timer', 'h', 's', 'organiser', '2025-01-01');
        """)
        conn.close()
        db.init_db(TEST_DB)
        db.init_db(TEST_DB)  # idempotent
        old = db.get_all_users(db_path=TEST_DB)[0]
        self.assertTrue(old["in_draw"])
        self.assertFalse(old["is_child"])
        self.assertEqual(db.get_event_settings(db_path=TEST_DB)["avoid_household"], 1)


    def _set_locked_until(self, user_id, iso):
        conn = db.get_db_connection(TEST_DB)
        with conn:
            conn.execute("UPDATE users SET locked_until = ? WHERE id = ?", (iso, user_id))
        conn.close()

    def test_login_lockout_and_unlock(self):
        alice = db.create_user("alice", "Alice", "correct-pw", db_path=TEST_DB)

        # 4 failures, then a success resets the counter
        for _ in range(4):
            self.assertIsNone(db.authenticate_user("alice", "wrong", db_path=TEST_DB))
        self.assertIsNotNone(db.authenticate_user("alice", "correct-pw", db_path=TEST_DB))
        self.assertEqual(db.get_security_status(db_path=TEST_DB)[alice["id"]]["failed_logins"], 0)

        # 5 failures -> the 5th reports the lock
        for _ in range(4):
            self.assertIsNone(db.authenticate_user("alice", "wrong", db_path=TEST_DB))
        with self.assertRaises(db.AccountLockedError) as ctx:
            db.authenticate_user("alice", "wrong", db_path=TEST_DB)
        self.assertEqual(ctx.exception.minutes_remaining, 30)
        self.assertTrue(db.get_security_status(db_path=TEST_DB)[alice["id"]]["is_locked"])

        # Even the correct password is refused while locked
        with self.assertRaises(db.AccountLockedError):
            db.authenticate_user("alice", "correct-pw", db_path=TEST_DB)

        # Organiser unlock
        self.assertTrue(db.unlock_user(alice["id"], db_path=TEST_DB))
        self.assertIsNotNone(db.authenticate_user("alice", "correct-pw", db_path=TEST_DB))

        # Lock expires on its own after 30 minutes
        for _ in range(4):
            db.authenticate_user("alice", "wrong", db_path=TEST_DB)
        with self.assertRaises(db.AccountLockedError):
            db.authenticate_user("alice", "wrong", db_path=TEST_DB)
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self._set_locked_until(alice["id"], past)
        self.assertFalse(db.get_security_status(db_path=TEST_DB)[alice["id"]]["is_locked"])
        # A fresh window: one wrong attempt doesn't re-lock
        self.assertIsNone(db.authenticate_user("alice", "wrong", db_path=TEST_DB))
        self.assertIsNotNone(db.authenticate_user("alice", "correct-pw", db_path=TEST_DB))

        # Unknown usernames just fail
        self.assertIsNone(db.authenticate_user("nobody", "x", db_path=TEST_DB))

    def test_concurrent_guesses_cannot_exceed_limit(self):
        db.create_user("alice", "Alice", "correct-pw", db_path=TEST_DB)
        results = []

        def attempt():
            try:
                results.append("ok" if db.authenticate_user("alice", "wrong", db_path=TEST_DB) else "fail")
            except db.AccountLockedError:
                results.append("locked")
            except Exception as e:  # e.g. sqlite busy
                results.append(f"error:{e}")

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly 5 attempts get a password check (4 plain failures + the 5th that triggers the lock)
        self.assertEqual(results.count("fail"), 4, results)
        self.assertEqual(results.count("locked"), 16, results)

    def test_admin_reset_and_change_password(self):
        alice = db.create_user("alice", "Alice", "old-pw", db_path=TEST_DB)
        bob = db.create_user("bob", "Bob", "bob-pw", db_path=TEST_DB)
        bob_session = db.create_session(bob["id"], db_path=TEST_DB)

        # Lock Bob out, then reset: clears lock, kills sessions, forces change
        for _ in range(4):
            db.authenticate_user("bob", "wrong", db_path=TEST_DB)
        with self.assertRaises(db.AccountLockedError):
            db.authenticate_user("bob", "wrong", db_path=TEST_DB)
        temp = db.admin_reset_password(bob["id"], db_path=TEST_DB)
        self.assertRegex(temp, r"^[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$")
        self.assertIsNone(db.get_user_from_session(bob_session, db_path=TEST_DB))
        self.assertIsNone(db.authenticate_user("bob", "bob-pw", db_path=TEST_DB))
        logged_in = db.authenticate_user("bob", temp, db_path=TEST_DB)
        self.assertTrue(logged_in["must_change_password"])

        # Can't "change" to the same temporary password; too-short rejected
        new_session = db.create_session(bob["id"], db_path=TEST_DB)
        other_session = db.create_session(bob["id"], db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.change_password(bob["id"], temp, db_path=TEST_DB)
        with self.assertRaises(ValueError):
            db.change_password(bob["id"], "abc", db_path=TEST_DB)
        db.change_password(bob["id"], "bob-new-pw", keep_session_token=new_session, db_path=TEST_DB)
        self.assertFalse(db.get_user_from_session(new_session, db_path=TEST_DB)["must_change_password"])
        self.assertIsNone(db.get_user_from_session(other_session, db_path=TEST_DB), "Other sessions are signed out")
        self.assertIsNotNone(db.authenticate_user("bob", "bob-new-pw", db_path=TEST_DB))

        # Voluntary change requires the right current password
        with self.assertRaises(PermissionError):
            db.change_password(alice["id"], "newer-pw", current_password="nope", db_path=TEST_DB)
        db.change_password(alice["id"], "newer-pw", current_password="old-pw", db_path=TEST_DB)
        self.assertIsNotNone(db.authenticate_user("alice", "newer-pw", db_path=TEST_DB))

        # Child profiles can't be reset
        kid = db.create_child(alice["id"], "Kid", db_path=TEST_DB)
        with self.assertRaises(LookupError):
            db.admin_reset_password(kid["id"], db_path=TEST_DB)

    def test_purge_expired_sessions(self):
        alice = db.create_user("alice", "Alice", "pw1234", db_path=TEST_DB)
        live = db.create_session(alice["id"], db_path=TEST_DB)
        db.create_session(alice["id"], days_valid=-1, db_path=TEST_DB)
        self.assertEqual(db.purge_expired_sessions(db_path=TEST_DB), 1)
        self.assertIsNotNone(db.get_user_from_session(live, db_path=TEST_DB))


if __name__ == "__main__":
    unittest.main()
