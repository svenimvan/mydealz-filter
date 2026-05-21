"""LLM-Klassifikation der Deals via OpenRouter.

Aus Titel + Beschreibung extrahieren wir feine Produkt-Gruppen wie
"iPhone", "3D-Drucker", "Akkuschrauber". Bekannte Gruppen werden dem
Modell mitgegeben, damit es bevorzugt wiederverwendet statt zu fragmentieren.
"""
import json
import logging
import os
import re
import time
import httpx
from .db import connect

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("CLASSIFIER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# Throttling: free-Modelle haben oft 20 RPM. Mit 4s Pause = 15 RPM, sicher.
MIN_DELAY_SECONDS = float(os.environ.get("CLASSIFIER_MIN_DELAY", "4.0"))
_last_call_at = 0.0

SYSTEM_PROMPT = """Du klassifizierst deutsche Online-Deals von mydealz.de in spezifische Produkt-Gruppen.

Regeln:
- Verwende präzise, kompakte deutsche Begriffe.
- KEINE Oberkategorien wie "Elektronik", "Haushalt", "Gaming" — diese sind zu grob.
- 1 bis 3 Gruppen pro Deal, normalerweise nur 1.
- Bevorzugt bereits existierende Gruppen aus der Liste unten verwenden, wenn passend.
- Nur wenn nichts passt, eine neue präzise Gruppe vorschlagen.
- Bei Mehrfach-Bundles (z.B. "PS5 + 2 Spiele") nimm die wichtigste Komponente.
- IMMER eine konkrete Gruppe vergeben, NIE "unklassifiziert" oder leer.

WICHTIGE Klassifikations-Beispiele für häufige Deal-Typen:

Hardware/Geräte:
- "iPhone", "Android-Smartphone", "3D-Drucker", "Akkuschrauber", "Bohrhammer", "Laufschuhe", "Kaffeemaschine", "Bluetooth-Kopfhörer", "Gaming-Monitor", "Webcam"

Software/Abos/KI:
- "KI-Abo" (für ChatGPT Plus, Google AI Pro, Claude Pro, Gemini Advanced, Perplexity Pro)
- "Software-Abo" (für Adobe, Office 365, Antivirus)
- "Cloud-Speicher" (für Google One, iCloud, Dropbox)
- "Streaming-Abo" (für Netflix, Disney+, Sky)
- "Musik-Abo" (für Spotify, Apple Music)
- NIE "Büroartikel" für Software/Abos verwenden — "Büroartikel" ist nur für physische Büromaterialien (Stifte, Ordner, Papier)!

Verträge/Tarife:
- "Mobilfunk-Vertrag", "Prepaid-Tarif", "DSL-Vertrag"
- "Stromtarif", "Gastarif"
- "Girokonto", "Kreditkarte", "Tagesgeld"

Reisen:
- "Pauschalreise", "Hotel-Übernachtung", "Bahn-Ticket", "Flug"
- "Flug" für Flugtickets, Direktflüge, Airline-Deals
- "Bus" NUR für tatsächliche Bus-Tickets/ÖPNV, nicht für Sammelflug-Angebote

Fahrzeuge:
- "Elektroauto" (für Tesla, Kia EV, ID.3, ID.4 usw.)
- "Auto" (für Verbrenner-Neuwagen)
- "E-Bike", "Fahrrad", "E-Scooter"
- "Motorrad", "Roller"

Spiele:
- "PC-Spiel", "PS5-Spiel", "Switch-Spiel", "Mobile-App"

Bei Gutscheinen/Cashback/Verträgen die zugrundeliegende Produktart, nicht "Gutschein".

Antworte AUSSCHLIESSLICH mit den Gruppen-Namen, kommagetrennt, sonst NICHTS — kein JSON, keine Erklärung, keine Markdown.
Beispiele für korrekte Antworten:
iPhone
LEGO-Set, Klemmbausteine
KI-Abo
"""


def get_known_groups(limit: int = 200) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM groups WHERE name != 'unklassifiziert' "
            "ORDER BY (alpha + beta) DESC, name LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["name"] for r in rows]


def _extract_json(text: str) -> dict | None:
    """LLMs verpacken JSON manchmal in Markdown-Fences oder Prosa. Robust parsen."""
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def classify(title: str, description: str = "") -> list[str]:
    """Gibt eine Liste feiner Produkt-Gruppen für einen Deal zurück."""
    if not OPENROUTER_KEY:
        log.warning("OPENROUTER_API_KEY nicht gesetzt — Klassifikation übersprungen")
        return ["unklassifiziert"]

    known = get_known_groups()
    known_str = ", ".join(known) if known else "(noch keine)"

    user_msg = (
        f"Bekannte Gruppen: {known_str}\n\n"
        f"Titel: {title}\n"
        f"Beschreibung: {description[:600]}"
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": 80,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/mydealz-filter",
        "X-Title": "MyDealz Filter",
    }

    # Throttling: warte bis MIN_DELAY_SECONDS seit dem letzten Call vergangen sind
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < MIN_DELAY_SECONDS:
        time.sleep(MIN_DELAY_SECONDS - elapsed)

    content = None
    for attempt in range(4):
        _last_call_at = time.monotonic()
        try:
            resp = httpx.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30.0)
            if resp.status_code == 429:
                wait = 2 ** attempt * 5  # 5, 10, 20, 40 s
                log.warning("429 für '%s', warte %ds (Versuch %d)",
                            title[:60], wait, attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            break
        except Exception as e:
            log.error("OpenRouter-Call fehlgeschlagen für '%s': %s", title[:60], e)
            return ["unklassifiziert"]

    if content is None:
        log.error("Nach 4 Versuchen immer noch 429 für '%s'", title[:60])
        return ["unklassifiziert"]

    # Plain-Text-Output parsen: kommagetrennte Gruppen, eventuell mit
    # vorangestelltem Markdown/Bullets/etc. abräumen.
    text = content.strip()
    # Falls das Modell doch JSON ausgibt: erste-beste Liste extrahieren
    if text.startswith("{") or text.startswith("["):
        m = re.search(r'\[([^\]]+)\]', text)
        if m:
            text = m.group(1)
    # Quotes, Bullets, Code-Fences entfernen
    text = re.sub(r'[`\[\]"\']', '', text)
    text = re.sub(r'^\s*[-*•]\s*', '', text, flags=re.MULTILINE)

    # Split auf Komma oder Newline
    parts = re.split(r'[,;\n]+', text)
    groups = [p.strip() for p in parts if p.strip() and len(p.strip()) < 60]

    if not groups:
        log.warning("Keine Gruppen extrahiert aus: %r", content[:200])
        return ["unklassifiziert"]

    return groups[:3]
