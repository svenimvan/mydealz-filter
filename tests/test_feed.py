import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from app import db
import app.feed as feed


class FeedFullContentTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = db.DB_PATH
        self._feed_connect = feed.connect
        self._should_include = feed.should_include
        self._record_impression = feed.record_impression
        self._public_base_url = feed.PUBLIC_BASE_URL

        db.DB_PATH = os.path.join(self._tmpdir.name, "mydealz.db")
        feed.connect = db.connect
        feed.should_include = lambda deal_id: True
        feed.record_impression = lambda deal_id: None
        feed.PUBLIC_BASE_URL = "http://example.test"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._db_path
        feed.connect = self._feed_connect
        feed.should_include = self._should_include
        feed.record_impression = self._record_impression
        feed.PUBLIC_BASE_URL = self._public_base_url
        self._tmpdir.cleanup()

    def test_feed_contains_content_encoded_after_description(self):
        description = "<p>Kompletter Dealtext & Details</p><ul><li>offline lesbar</li></ul>"
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO deals (mydealz_id, title, description, url, published) "
                "VALUES (?, ?, ?, ?, ?)",
                ("12345", "Deal <Test>", description, "https://www.mydealz.de/deals/test-12345", "Sat, 06 Jun 2026 15:00:00 +0200"),
            )

        xml = feed.build_feed()

        self.assertIn('xmlns:content="http://purl.org/rss/1.0/modules/content/"', xml)
        self.assertLess(xml.index("<description><![CDATA["), xml.index("<content:encoded><![CDATA["))
        self.assertIn(description, xml)
        self.assertIn("http://example.test/click/1", xml)

        root = ET.fromstring(xml)
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        content = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        self.assertIsNotNone(content)
        self.assertIn("Originaldeal auf MyDealz", content.text)


if __name__ == "__main__":
    unittest.main()
