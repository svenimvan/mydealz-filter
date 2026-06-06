"""Feed-Generierung: liest gefilterte Deals und baut RSS-XML."""
import os
from email.utils import formatdate
from xml.sax.saxutils import escape, quoteattr
from .db import connect
from .scoring import should_include, record_impression

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5102")
MAX_FEED_ITEMS = 150


def cdata(value: str) -> str:
    return "<![CDATA[" + (value or "").replace("]]>", "]]]]><![CDATA[>") + "]]>"


def full_content(description: str | None, original_url: str) -> str:
    description = description or ""
    if not original_url:
        return description
    return (
        f"{description}"
        f"<p><a href={quoteattr(original_url)}>Originaldeal auf MyDealz öffnen</a></p>"
    )


def build_feed() -> str:
    with connect() as conn:
        deals = conn.execute(
            "SELECT id, mydealz_id, title, description, url, first_seen, published "
            "FROM deals ORDER BY first_seen DESC LIMIT ?",
            (MAX_FEED_ITEMS * 3,),  # Overfetch, da gefiltert wird
        ).fetchall()

        conn.execute("INSERT INTO feed_pulls (pulled_at) VALUES (CURRENT_TIMESTAMP)")

    included = []
    for d in deals:
        if should_include(d["id"]):
            included.append(d)
            record_impression(d["id"])
        if len(included) >= MAX_FEED_ITEMS:
            break

    items_xml = []
    for d in included:
        click_url = f"{PUBLIC_BASE_URL}/click/{d['id']}"
        pub = d["published"] or formatdate(localtime=True)
        description = d["description"] or ""
        content = full_content(description, d["url"])
        items_xml.append(
            f"<item>"
            f"<title>{escape(d['title'])}</title>"
            f"<link>{escape(click_url)}</link>"
            f"<guid isPermaLink=\"false\">mydealz-filter-{escape(d['mydealz_id'])}</guid>"
            f"<pubDate>{escape(pub)}</pubDate>"
            f"<description>{cdata(description)}</description>"
            f"<content:encoded>{cdata(content)}</content:encoded>"
            f"</item>"
        )

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        '<channel>'
        '<title>MyDealz (gefiltert)</title>'
        f'<link>{escape(PUBLIC_BASE_URL)}</link>'
        '<description>Selbstlernender Filter für mydealz.de</description>'
        '<language>de-de</language>'
        + "".join(items_xml) +
        '</channel></rss>'
    )
    return rss
