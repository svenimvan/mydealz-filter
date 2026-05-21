"""Poller: holt regelmäßig den MyDealz-RSS-Feed und speichert neue Deals."""
import logging
import hashlib
import httpx
import feedparser
from datetime import datetime
from .db import connect
from .classifier import classify

log = logging.getLogger(__name__)

MYDEALZ_RSS = "https://www.mydealz.de/rss/alles"


def extract_groups(entry) -> list[str]:
    """Feine Produkt-Gruppen via LLM-Klassifikator (OpenRouter).
    Die groben MyDealz-Kategorien werden bewusst ignoriert — wir wollen
    feinere Granularität wie 'iPhone', '3D-Drucker', 'Akkuschrauber'.
    """
    title = entry.get("title", "").strip()
    desc = entry.get("summary", "").strip()
    return classify(title, desc)


def deal_id_from_link(link: str) -> str:
    """MyDealz-Link enthält die ID am Ende: .../irgendwas-12345. Sonst Hash."""
    if not link:
        return hashlib.sha1(b"").hexdigest()[:16]
    last = link.rstrip("/").split("-")[-1]
    if last.isdigit():
        return last
    return hashlib.sha1(link.encode()).hexdigest()[:16]


def poll_once() -> int:
    """Holt RSS, speichert neue Deals. Returns Anzahl neuer Deals."""
    try:
        resp = httpx.get(MYDEALZ_RSS, timeout=20.0, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (mydealz-filter/1.0)"})
        resp.raise_for_status()
    except Exception as e:
        log.error("Feed-Abruf fehlgeschlagen: %s", e)
        return 0

    feed = feedparser.parse(resp.content)
    new_count = 0

    with connect() as conn:
        for entry in feed.entries:
            md_id = deal_id_from_link(entry.get("link", ""))
            title = entry.get("title", "").strip()
            desc = entry.get("summary", "").strip()
            url = entry.get("link", "").strip()
            published = entry.get("published", "")

            try:
                cur = conn.execute(
                    "INSERT INTO deals (mydealz_id, title, description, url, published) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (md_id, title, desc, url, published),
                )
                deal_id = cur.lastrowid
                new_count += 1
            except __import__("sqlite3").IntegrityError:
                continue  # Deal kennen wir schon

            for group in extract_groups(entry):
                conn.execute(
                    "INSERT OR IGNORE INTO groups (name) VALUES (?)", (group,)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO deal_groups (deal_id, group_name) "
                    "VALUES (?, ?)",
                    (deal_id, group),
                )

    log.info("Poll: %d neue Deals (%d insgesamt im Feed)",
             new_count, len(feed.entries))
    return new_count
