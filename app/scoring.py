"""Scoring-Modul.

Pro Produkt-Gruppe führen wir eine Beta-Verteilung Beta(α, β):
    α = Anzahl Klicks auf Deals dieser Gruppe
    β = Anzahl "verpasster" Impressionen (Deal wurde gezeigt, nicht geklickt)

Daraus leitet sich die geschätzte Klick-Wahrscheinlichkeit ab.
"""
import math
import random
from typing import Iterable
from .db import connect


# ---------- Score-Berechnungen ----------

def laplace_score(alpha: float, beta: float) -> float:
    """Punkt-Schätzer mit Laplace-Smoothing (vermeidet 0/0 bei neuen Gruppen)."""
    return (alpha + 1.0) / (alpha + beta + 2.0)


def thompson_sample(alpha: float, beta: float) -> float:
    """Sample aus Beta(α+1, β+1). Erlaubt Exploration:
    unsichere Gruppen kriegen gelegentlich hohe Scores und werden durchgelassen."""
    return random.betavariate(alpha + 1.0, beta + 1.0)


# ---------- Gruppen-Lookup ----------

def get_group_stats(name: str) -> tuple[float, float, str | None]:
    with connect() as conn:
        row = conn.execute(
            "SELECT alpha, beta, manual_override FROM groups WHERE name = ?", (name,)
        ).fetchone()
    if not row:
        return 0.0, 0.0, None
    return row["alpha"], row["beta"], row["manual_override"]


def groups_for_deal(deal_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT group_name FROM deal_groups WHERE deal_id = ?", (deal_id,)
        ).fetchall()
    return [r["group_name"] for r in rows]


# ---------- Filter-Entscheidung ----------
#
# DAS IST DER KERN DES FILTERS — bitte selbst implementieren:
#
# Gegeben eine Liste der Gruppen eines Deals, entscheide ob er in den
# gefilterten Feed soll. Du kannst die folgenden Bausteine nutzen:
#
#   - get_group_stats(name) -> (alpha, beta, manual_override)
#       manual_override == "allow"  -> Gruppe immer durchlassen
#       manual_override == "block"  -> Gruppe immer aussortieren
#       manual_override is None     -> automatisch entscheiden
#   - laplace_score(alpha, beta)    -> Punkt-Schätzung der CTR
#   - thompson_sample(alpha, beta)  -> zufälliger Sample für Exploration
#
# Die User-Wahl: "Mild + Exploration", d.h. nur klar negative Gruppen cutten
# (Threshold ~0.10) und zusätzlich gelegentlich unsichere Gruppen durchlassen.
#
# Schreib unten deine Logik. Hinweis: Wenn ein Deal mehrere Gruppen hat —
# willst du UND (alle Gruppen müssen passen), ODER (eine reicht), oder ein
# gewichtetes Mittel? Das ist eine echte Design-Entscheidung.

MIN_SAMPLES_BEFORE_FILTERING = 15   # defensiv: erst ab N Datenpunkten filtern
DEFAULT_THRESHOLD = 0.08            # konservativ: nur klar negative cutten


def should_include(deal_id: int, *, threshold: float = DEFAULT_THRESHOLD,
                   exploration: bool = True) -> bool:
    """ODER-Logik: ein Deal kommt durch, wenn *mindestens eine* seiner Gruppen
    den Filter besteht. Defensiv: Gruppen mit wenig Daten werden nicht gefiltert.

    Reihenfolge der Prüfungen pro Gruppe:
      1. manual_override == 'allow'  -> Deal durchlassen (jede Allow-Gruppe reicht)
      2. manual_override == 'block'  -> diese Gruppe disqualifiziert sich, andere prüfen
      3. zu wenig Daten              -> Gruppe gilt als 'ok' (Unschuldsvermutung)
      4. score >= threshold          -> Gruppe gilt als 'ok'
    Wenn keine einzige Gruppe ok ist -> Deal raus.
    """
    groups = groups_for_deal(deal_id)
    if not groups:
        return True

    any_ok = False
    for g in groups:
        alpha, beta, override = get_group_stats(g)
        if override == "allow":
            return True
        if override == "block":
            continue
        if (alpha + beta) < MIN_SAMPLES_BEFORE_FILTERING:
            any_ok = True
            continue
        score = thompson_sample(alpha, beta) if exploration else laplace_score(alpha, beta)
        if score >= threshold:
            any_ok = True
    return any_ok


# ---------- Wartung: Decay & Reset ----------

def decay_all(factor: float = 0.97) -> None:
    """Wöchentlicher Hintergrund-Job: alle α und β leicht abklingen lassen.

    Warum? Damit alte Beobachtungen mit der Zeit weniger Gewicht haben und das
    System sich anpassen kann, wenn sich deine Interessen ändern. Mit
    factor=0.97 hat eine Beobachtung nach ~23 Wochen nur noch halbes Gewicht.
    """
    with connect() as conn:
        conn.execute(
            "UPDATE groups SET alpha = alpha * ?, beta = beta * ?, "
            "updated_at = CURRENT_TIMESTAMP",
            (factor, factor),
        )


def reset_group(name: str) -> None:
    """Setzt α und β einer Gruppe auf 0 zurück — Gruppe lernt komplett neu."""
    with connect() as conn:
        conn.execute(
            "UPDATE groups SET alpha = 0, beta = 0, manual_override = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )


# ---------- Updates aus Events ----------

CLICK_DEDUP_SECONDS = 60   # Mehrfach-Klicks innerhalb 60s zählen als einer


def register_click(deal_id: int) -> bool:
    """Klick → α++ für alle Gruppen des Deals. Außerdem werden offene
    Impressionen dieses Deals als 'geklickt' markiert (counted=1), damit sie
    nicht später nochmal als negativ verbucht werden.

    Dedup: RSS-Reader prefetchen Links oft → ein User-Klick erzeugt mehrere
    HTTP-Hits. Klicks auf denselben Deal innerhalb CLICK_DEDUP_SECONDS
    werden ignoriert. Returns True wenn der Klick verbucht wurde, False
    wenn er als Dup verworfen wurde.
    """
    with connect() as conn:
        dup = conn.execute(
            "SELECT 1 FROM clicks WHERE deal_id = ? "
            "AND clicked_at > datetime('now', ?)",
            (deal_id, f"-{CLICK_DEDUP_SECONDS} seconds"),
        ).fetchone()
        if dup:
            return False

        conn.execute("INSERT INTO clicks (deal_id) VALUES (?)", (deal_id,))
        conn.execute(
            "UPDATE impressions SET counted = 1 WHERE deal_id = ? AND counted = 0",
            (deal_id,),
        )
        for g in groups_for_deal(deal_id):
            conn.execute(
                "UPDATE groups SET alpha = alpha + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (g,),
            )
    return True


def record_impression(deal_id: int) -> None:
    """Wird beim Ausliefern des Feeds aufgerufen."""
    with connect() as conn:
        conn.execute("INSERT INTO impressions (deal_id) VALUES (?)", (deal_id,))


def settle_impressions(window_hours: int = 6, max_age_hours: int = 72) -> int:
    """Hintergrund-Job: alte Impressionen ohne Klick als 'verpasst' verbuchen.

    Wichtig: nur wenn der Feed in den letzten `window_hours` Stunden tatsächlich
    abgerufen wurde, zählen wir 'nicht geklickt' als negatives Signal. Sonst
    bestrafen wir Gruppen nur weil der User offline war.
    """
    with connect() as conn:
        recent_pull = conn.execute(
            "SELECT COUNT(*) AS c FROM feed_pulls "
            "WHERE pulled_at >= datetime('now', ?)",
            (f"-{window_hours} hours",),
        ).fetchone()["c"]

        if recent_pull == 0:
            return 0  # niemand hat den Feed gelesen → keine Bestrafung

        stale = conn.execute(
            "SELECT id, deal_id FROM impressions "
            "WHERE counted = 0 AND shown_at < datetime('now', ?) "
            "AND shown_at > datetime('now', ?)",
            (f"-{window_hours} hours", f"-{max_age_hours} hours"),
        ).fetchall()

        for row in stale:
            for g in groups_for_deal(row["deal_id"]):
                conn.execute(
                    "UPDATE groups SET beta = beta + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                    (g,),
                )
            conn.execute("UPDATE impressions SET counted = 1 WHERE id = ?",
                         (row["id"],))

        return len(stale)
