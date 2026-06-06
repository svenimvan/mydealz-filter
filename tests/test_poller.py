import os
import sys
import tempfile
import types
import unittest

sys.modules.setdefault("httpx", types.SimpleNamespace(get=None))
sys.modules.setdefault("feedparser", types.SimpleNamespace(parse=None))

from app import db
import app.poller as poller


class _Response:
    content = b"feed"

    def raise_for_status(self):
        return None


class _Feed:
    def __init__(self, entries):
        self.entries = entries


class PollerContentTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = db.DB_PATH
        self._connect = poller.connect
        self._httpx = poller.httpx
        self._feedparser = poller.feedparser
        self._classify = poller.classify

        db.DB_PATH = os.path.join(self._tmpdir.name, "mydealz.db")
        poller.connect = db.connect
        poller.httpx = types.SimpleNamespace()
        poller.feedparser = types.SimpleNamespace()
        poller.httpx.get = lambda *args, **kwargs: _Response()
        poller.classify = lambda title, description: ["Testgruppe"]
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._db_path
        poller.connect = self._connect
        poller.httpx = self._httpx
        poller.feedparser = self._feedparser
        poller.classify = self._classify
        self._tmpdir.cleanup()

    def test_extract_content_prefers_content_value(self):
        entry = {
            "content": [{"value": "<p>vollstaendiger Dealtext mit Details</p>"}],
            "summary": "kurz",
        }

        self.assertEqual(
            poller.extract_content(entry),
            "<p>vollstaendiger Dealtext mit Details</p>",
        )

    def test_extract_content_falls_back_to_summary(self):
        self.assertEqual(
            poller.extract_content({"summary": "Zusammenfassung"}),
            "Zusammenfassung",
        )

    def test_existing_deal_is_updated_only_when_new_content_is_better(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO deals (mydealz_id, title, description, url, published) "
                "VALUES (?, ?, ?, ?, ?)",
                ("12345", "Alter Deal", "kurz", "https://www.mydealz.de/deals/test-12345", ""),
            )

        poller.feedparser.parse = lambda content: _Feed([
            {
                "title": "Alter Deal",
                "summary": "<p>laengerer vollstaendiger Dealtext</p>",
                "link": "https://www.mydealz.de/deals/test-12345",
                "published": "",
            }
        ])
        self.assertEqual(poller.poll_once(), 0)
        with db.connect() as conn:
            row = conn.execute("SELECT description FROM deals WHERE mydealz_id = '12345'").fetchone()
        self.assertEqual(row["description"], "<p>laengerer vollstaendiger Dealtext</p>")

        poller.feedparser.parse = lambda content: _Feed([
            {
                "title": "Alter Deal",
                "summary": "kurz",
                "link": "https://www.mydealz.de/deals/test-12345",
                "published": "",
            }
        ])
        self.assertEqual(poller.poll_once(), 0)
        with db.connect() as conn:
            row = conn.execute("SELECT description FROM deals WHERE mydealz_id = '12345'").fetchone()
        self.assertEqual(row["description"], "<p>laengerer vollstaendiger Dealtext</p>")


if __name__ == "__main__":
    unittest.main()
