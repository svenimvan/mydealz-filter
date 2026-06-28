import os
import sys
import tempfile
import unittest

if "httpx" in sys.modules and not hasattr(sys.modules["httpx"], "Response"):
    del sys.modules["httpx"]

from fastapi.testclient import TestClient

import app.db as db
import app.main as main


class BulkOverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmpdir.name, "test.db")
        db.init_db()
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO groups (name, manual_override) VALUES (?, ?)",
                [
                    ("Akkuschrauber", None),
                    ("KI-Abo", "allow"),
                    ("LEGO-Set", "block"),
                    ("Kaffeemaschine", None),
                ],
            )
        self.client = TestClient(main.app)

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.tmpdir.cleanup()

    def _overrides(self):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT name, manual_override FROM groups ORDER BY name"
            ).fetchall()
        return {row["name"]: row["manual_override"] for row in rows}

    def test_bulk_block_updates_only_selected_groups(self):
        resp = self.client.post(
            "/groups/bulk/override",
            data={"groups[]": ["Akkuschrauber", "KI-Abo"], "mode": "block"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated"], 2)
        self.assertEqual(
            self._overrides(),
            {
                "Akkuschrauber": "block",
                "KI-Abo": "block",
                "Kaffeemaschine": None,
                "LEGO-Set": "block",
            },
        )

    def test_bulk_allow_and_clear_selected_groups(self):
        allow_resp = self.client.post(
            "/groups/bulk/override",
            data={"groups[]": ["Akkuschrauber", "LEGO-Set"], "mode": "allow"},
        )
        self.assertEqual(allow_resp.status_code, 200)
        self.assertEqual(self._overrides()["Akkuschrauber"], "allow")
        self.assertEqual(self._overrides()["LEGO-Set"], "allow")

        clear_resp = self.client.post(
            "/groups/bulk/override",
            data={"groups[]": ["Akkuschrauber", "LEGO-Set"], "mode": "clear"},
        )
        self.assertEqual(clear_resp.status_code, 200)
        self.assertIsNone(self._overrides()["Akkuschrauber"])
        self.assertIsNone(self._overrides()["LEGO-Set"])

    def test_invalid_mode_is_rejected(self):
        resp = self.client.post(
            "/groups/bulk/override",
            data={"groups[]": ["Akkuschrauber"], "mode": "reset"},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(self._overrides()["Akkuschrauber"])


if __name__ == "__main__":
    unittest.main()
