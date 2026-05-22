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
_remote_disabled_reason: str | None = None

# Diese Labels sind fuer das Lernsystem schaedlich: Sie beschreiben Deal-Mechanik
# oder Fehlerzustand, nicht die Produktart. Sie duerfen weder als Kontext ans LLM
# gehen noch als Ergebnis gespeichert werden, wenn es eine bessere Alternative gibt.
FORBIDDEN_GROUPS = {
    "Gutschein",
    "Payback",
    "Cashback",
    "keine passende Gruppe gefunden",
    "unklassifiziert",
}

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
- "Bluetooth-Lautsprecher" für JBL Go, Marshall Emberton, Bose SoundLink usw.
- "Gaming-PC" für Desktop-PCs, Handheld-Gaming-PCs, RTX/Ryzen Gaming-Rechner — NICHT "PC-Spiel"
- "Luftpumpe" für SUP-/Paddle-Board-Pumpen — NICHT "Luftreiniger"
- "Rasenmäher" für Akku-Rasenmäher — "Mähroboter" nur für autonome Mähroboter

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
- "PC-Spiel", "PS5-Spiel", "Nintendo Switch", "Xbox Series X|S", "Mobile-App"
- Spiele-Hardware/Zubehör nicht als Spiel klassifizieren: Joystick → "Gaming-Zubehör", Gaming-PC → "Gaming-PC"

Bei Gutscheinen/Cashback/Verträgen die zugrundeliegende Produktart, nicht "Gutschein", "Payback" oder "Cashback".

Antworte AUSSCHLIESSLICH mit den Gruppen-Namen, kommagetrennt, sonst NICHTS — kein JSON, keine Erklärung, keine Markdown.
Beispiele für korrekte Antworten:
iPhone
LEGO-Set, Klemmbausteine
KI-Abo
"""


def get_known_groups(limit: int = 200) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM groups "
            "ORDER BY (alpha + beta) DESC, name LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["name"] for r in rows if r["name"] not in FORBIDDEN_GROUPS]


def _extract_json(text: str) -> dict | None:
    """LLMs verpacken JSON manchmal in Markdown-Fences oder Prosa. Robust parsen."""
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _keyword_fallback(title: str, description: str = "") -> list[str]:
    """Kleine Sicherheitsleine fuer verbotene oder leere LLM-Antworten.

    Das ist bewusst keine Vollklassifikation. Sie deckt nur Muster ab, die im
    Audit wiederholt falsch liefen oder bei Gutschein/Cashback-Deals oft genug
    direkt aus dem Titel ableitbar sind.
    """
    text = f"{title} {description}".lower()
    rules = [
        (("chatgpt", "google ai pro", "gemini advanced", "claude pro", "perplexity pro"), "KI-Abo"),
        (("adobe", "office 365", "microsoft 365", "antivirus"), "Software-Abo"),
        (("google one", "icloud", "dropbox"), "Cloud-Speicher"),
        (("apple music", "spotify", "deezer"), "Musik-Abo"),
        (("blu-ray", "blu ray", "apple tv", "itunes", "amazon vod", "maxdome", "imdb"), "Film"),
        (("direktflug", "direktflüge", "flugticket", "airline"), "Flug"),
        (("privatleasing", "leasing"), "Auto-Leasing"),
        (("e-rocks", "elektroauto"), "Elektroauto"),
        (("gaming pc", "gaming-pc", "rtx ", "geforce rtx", "ryzen"), "Gaming-PC"),
        (("lautsprecher", "speaker", "soundlink", "jbl go", "emberton"), "Bluetooth-Lautsprecher"),
        (("sup-pumpe", "paddle-board-pumpe", "paddle board pumpe"), "Luftpumpe"),
        (("mähroboter", "maehroboter"), "Mähroboter"),
        (("rasenmäher", "rasenmaeher"), "Rasenmäher"),
        (("zahnbürste", "oral-b", "oneblade", "rasierer"), "Zahnbürste"),
        (("mundspülung", "mundspuelung", "listerine"), "Mundpflege"),
        (("parfüm", "parfum", "eau de parfum", "duft"), "Parfüm"),
        (("whisky", "whiskey", "malts"), "Whisky"),
        (("funkgerät", "walkie talkie"), "Funkgerät"),
        (("campingstuhl",), "Campingstuhl"),
        (("kuscheltier", "stofftier"), "Kuscheltier"),
        (("gesellschaftsspiel", "kinderspiel", "ravensburger"), "Gesellschaftsspiel"),
        (("netflix", "youtube premium", "disney+", "sky "), "Streaming-Abo"),
        (("mobilfunk", "allnet", "prepaid", "5g", "telekom netz"), "Mobilfunk-Vertrag"),
        (("lego", "klemmbaustein"), "LEGO-Set"),
        (("kino", "cinemaxx", "uci kino"), "Kino-Ticket"),
        (("google-play-gutschein", "google play gutschein"), "Google-Play-Guthaben"),
        (("appstore", "ios appstore", "lifetime kostenlos"), "Mobile-App"),
        (("netzwerktechnik", "netzwerk-switch", "switche"), "Netzwerk-Switch"),
        (("dhl", "paketversand", "versandmarke"), "Paketdienst"),
        (("otto up", "otto up plus"), "Shopping-Abo"),
        (("paypal",), "Zahlungsdienst"),
        (("trikot", "adidas", "c&a", "cund a", "c & a"), "Bekleidung"),
        (("fruchtsaft", "valensina"), "Saft"),
        (("gelschreiber", "rotring", "stift"), "Schreibgerät"),
        (("voelkner", "völkner"), "Werkzeug"),
        (("wera", "tool-check"), "Werkzeug"),
        (("krankenkasse",), "Bonusprogramm"),
    ]
    found = []
    for needles, group in rules:
        if any(needle in text for needle in needles):
            found.append(group)
    return list(dict.fromkeys(found))[:3]


def _sanitize_groups(groups: list[str], title: str, description: str) -> list[str]:
    text = title.lower()
    cleaned = []
    for group in groups:
        group = re.sub(r"\s+", " ", group).strip(" .:-")
        if not group or len(group) >= 60:
            continue
        if group in FORBIDDEN_GROUPS:
            continue
        if group == "PC-Spiel" and any(
            needle in text for needle in ("gaming pc", "gaming-pc", "geforce rtx", "rtx ", "ryzen")
        ):
            group = "Gaming-PC"
        elif group == "Bluetooth-Kopfhörer" and any(
            needle in text for needle in ("lautsprecher", "speaker", "soundlink", "jbl go", "emberton")
        ):
            group = "Bluetooth-Lautsprecher"
        elif group == "Mähroboter" and any(
            needle in text for needle in ("rasenmäher", "rasenmaeher")
        ):
            group = "Rasenmäher"
        elif group == "Luftreiniger" and any(
            needle in text for needle in ("sup-pumpe", "paddle-board-pumpe", "paddle board pumpe")
        ):
            group = "Luftpumpe"
        cleaned.append(group)

    cleaned = list(dict.fromkeys(cleaned))
    if cleaned:
        return cleaned[:3]

    fallback = _keyword_fallback(title, description)
    if fallback:
        return fallback
    return ["Sonstige Deals"]


def classify(title: str, description: str = "") -> list[str]:
    """Gibt eine Liste feiner Produkt-Gruppen für einen Deal zurück."""
    global _remote_disabled_reason
    if not OPENROUTER_KEY:
        log.warning("OPENROUTER_API_KEY nicht gesetzt — nutze lokale Fallback-Klassifikation")
        return _sanitize_groups([], title, description)
    if _remote_disabled_reason:
        log.warning("OpenRouter deaktiviert (%s) — nutze lokale Fallback-Klassifikation", _remote_disabled_reason)
        return _sanitize_groups([], title, description)

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
            if resp.status_code in (401, 403):
                _remote_disabled_reason = f"HTTP {resp.status_code}"
                log.error(
                    "OpenRouter-Key abgelehnt (%s) — deaktiviere Remote-Klassifikation bis zum Neustart",
                    _remote_disabled_reason,
                )
                return _sanitize_groups([], title, description)
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
            return _sanitize_groups([], title, description)

    if content is None:
        log.error("Nach 4 Versuchen immer noch 429 für '%s'", title[:60])
        return _sanitize_groups([], title, description)

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
        return _sanitize_groups([], title, description)

    return _sanitize_groups(groups, title, description)
