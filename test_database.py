import unittest
import os
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


if __name__ == "__main__":
    unittest.main()
