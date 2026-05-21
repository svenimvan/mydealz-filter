"""FastAPI-Entry-Point + Scheduler."""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import Response, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler

from .db import init_db, connect
from .poller import poll_once
from .scoring import (register_click, settle_impressions, laplace_score,
                      decay_all, reset_group)
from .feed import build_feed

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mydealz-filter")

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_MINUTES", "15"))
IMPRESSION_WINDOW = int(os.environ.get("IMPRESSION_WINDOW_HOURS", "6"))

templates = Jinja2Templates(directory="app/templates")
scheduler = BackgroundScheduler(timezone="Europe/Berlin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("DB initialisiert")
    poll_once()  # initial pull
    scheduler.add_job(poll_once, "interval", minutes=POLL_INTERVAL,
                      id="poll", coalesce=True, max_instances=1)
    scheduler.add_job(lambda: settle_impressions(IMPRESSION_WINDOW),
                      "interval", minutes=30, id="settle",
                      coalesce=True, max_instances=1)
    scheduler.add_job(decay_all, "cron", day_of_week="sun", hour=3,
                      id="decay", coalesce=True, max_instances=1)
    scheduler.start()
    log.info("Scheduler gestartet: Poll alle %d min, Settle alle 30 min",
             POLL_INTERVAL)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="MyDealz Filter", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/feed.xml")
def feed(request: Request):
    xml = build_feed()
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/click/{deal_id}")
def click(deal_id: int):
    with connect() as conn:
        row = conn.execute("SELECT url FROM deals WHERE id = ?",
                           (deal_id,)).fetchone()
    if not row:
        return Response("Unbekannter Deal", status_code=404)
    register_click(deal_id)
    return RedirectResponse(url=row["url"], status_code=302)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with connect() as conn:
        groups = conn.execute(
            "SELECT g.name, g.alpha, g.beta, g.manual_override, "
            "       COUNT(dg.deal_id) AS deal_count "
            "FROM groups g LEFT JOIN deal_groups dg ON dg.group_name = g.name "
            "GROUP BY g.name "
            "ORDER BY (g.alpha + g.beta) DESC, g.name"
        ).fetchall()
        totals = conn.execute(
            "SELECT (SELECT COUNT(*) FROM deals) AS deals, "
            "(SELECT COUNT(*) FROM clicks) AS clicks, "
            "(SELECT COUNT(*) FROM impressions WHERE counted=1) AS impressions, "
            "(SELECT COUNT(*) FROM feed_pulls) AS pulls"
        ).fetchone()

    enriched = [
        {
            "name": g["name"],
            "alpha": g["alpha"],
            "beta": g["beta"],
            "score": laplace_score(g["alpha"], g["beta"]),
            "override": g["manual_override"],
            "deal_count": g["deal_count"],
        }
        for g in groups
    ]
    enriched.sort(key=lambda x: x["score"])

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "groups": enriched, "totals": dict(totals)},
    )


@app.post("/groups/{name}/override")
def set_override(name: str, mode: str = Form(...)):
    """mode: 'allow' | 'block' | 'clear'"""
    val = None if mode == "clear" else mode
    with connect() as conn:
        conn.execute(
            "UPDATE groups SET manual_override = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (val, name),
        )
    # Redirect mit Anker — Browser scrollt zur Gruppe (Fallback ohne JS)
    from urllib.parse import quote
    return RedirectResponse(url=f"/#group-{quote(name)}", status_code=303)


@app.post("/admin/reclassify-group/{group_name}")
def reclassify_group(group_name: str):
    """Klassifiziert alle Deals einer Gruppe neu. Nützlich bei systematischen
    Fehlklassifikationen (z.B. 'Büroartikel' für Software-Abos).
    Achtung: alpha/beta-Statistiken bleiben — nur die Deal→Gruppen-Zuordnung wird neu gemacht."""
    from .classifier import classify
    with connect() as conn:
        deals = conn.execute(
            "SELECT d.id, d.title, d.description FROM deals d "
            "JOIN deal_groups dg ON dg.deal_id = d.id WHERE dg.group_name = ?",
            (group_name,),
        ).fetchall()
    changed = 0
    for d in deals:
        new_groups = classify(d["title"], d["description"] or "")
        with connect() as conn:
            conn.execute("DELETE FROM deal_groups WHERE deal_id = ?", (d["id"],))
            for g in new_groups:
                conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (g,))
                conn.execute(
                    "INSERT OR IGNORE INTO deal_groups (deal_id, group_name) "
                    "VALUES (?, ?)", (d["id"], g),
                )
        changed += 1
    # Falls die alte Gruppe jetzt keine Deals mehr hat und keine Statistik → löschen
    with connect() as conn:
        conn.execute(
            "DELETE FROM groups WHERE name = ? AND alpha = 0 AND beta = 0 "
            "AND NOT EXISTS (SELECT 1 FROM deal_groups WHERE group_name = ?)",
            (group_name, group_name),
        )
    return {"group": group_name, "reclassified": changed}


@app.post("/admin/reclassify-unknown")
def reclassify_unknown():
    """Klassifiziert alle Deals neu, die nur in 'unklassifiziert' oder gar
    keiner Gruppe sind. Nützlich nach Rate-Limit-Fehlern."""
    from .classifier import classify
    with connect() as conn:
        deals = conn.execute(
            "SELECT d.id, d.title, d.description FROM deals d "
            "WHERE NOT EXISTS (SELECT 1 FROM deal_groups dg "
            "                  WHERE dg.deal_id = d.id "
            "                  AND dg.group_name != 'unklassifiziert')"
        ).fetchall()
    fixed = 0
    for d in deals:
        new_groups = classify(d["title"], d["description"] or "")
        if new_groups == ["unklassifiziert"]:
            continue
        with connect() as conn:
            conn.execute("DELETE FROM deal_groups WHERE deal_id = ?", (d["id"],))
            for g in new_groups:
                conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (g,))
                conn.execute(
                    "INSERT OR IGNORE INTO deal_groups (deal_id, group_name) "
                    "VALUES (?, ?)", (d["id"], g),
                )
        fixed += 1
    return {"reclassified": fixed, "total_checked": len(deals)}


@app.post("/groups/{name}/reset")
def reset(name: str):
    """Setzt eine Gruppe komplett zurück — α=0, β=0, kein Override.
    Sinnvoll wenn sich deine Interessen geändert haben und du eine Gruppe
    wieder von Null an lernen lassen willst."""
    reset_group(name)
    from urllib.parse import quote
    return RedirectResponse(url=f"/#group-{quote(name)}", status_code=303)
