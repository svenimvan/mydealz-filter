"""Rule-first-Klassifikation mit explizitem LLM-Provider.

Aus Titel + Beschreibung extrahieren wir feine Produkt-Gruppen wie
"iPhone", "3D-Drucker", "Akkuschrauber". Bekannte Gruppen werden dem
Modell mitgegeben, damit es bevorzugt wiederverwendet statt zu fragmentieren.
"""
import json
import logging
import os
import re
from collections import Counter
from threading import Lock
import time
import httpx
from .db import connect

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SCALEWAY_URL = os.environ.get(
    "SCALEWAY_API_URL", "https://api.scaleway.ai/v1/chat/completions"
)
SCALEWAY_KEY = os.environ.get("SCALEWAY_API_KEY", "")
PROVIDER = os.environ.get("CLASSIFIER_PROVIDER", "openrouter").strip().lower()
MODEL = os.environ.get("CLASSIFIER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

if PROVIDER == "scaleway":
    API_URL = SCALEWAY_URL
    API_KEY = SCALEWAY_KEY
elif PROVIDER == "openrouter":
    API_URL = OPENROUTER_URL
    API_KEY = OPENROUTER_KEY
else:
    API_URL = ""
    API_KEY = ""

# Throttling: free-Modelle haben oft 20 RPM. Mit 4s Pause = 15 RPM, sicher.
MIN_DELAY_SECONDS = float(os.environ.get("CLASSIFIER_MIN_DELAY", "4.0"))
_last_call_at = 0.0
_remote_disabled_reason: str | None = None
_decision_counts = Counter()
_decision_counts_lock = Lock()

# Diese Labels sind fuer das Lernsystem schaedlich: Sie beschreiben Deal-Mechanik
# oder Fehlerzustand, nicht die Produktart. Sie duerfen weder als Kontext ans LLM
# gehen noch als Ergebnis gespeichert werden, wenn es eine bessere Alternative gibt.
FORBIDDEN_GROUPS = {
    "Gutschein",
    "Payback",
    "Cashback",
    "keine passende Gruppe gefunden",
    "Sonstige Deals",
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


def _is_tv_deal(text: str) -> bool:
    if any(needle in text for needle in ("tv remote", "tv-remote", "fernbedienung", "remote app")):
        return False
    return any(needle in text for needle in ("oled tv", "qled tv", "ambilight tv", "smart tv", "fernseher"))


def _is_energy_drink_deal(text: str) -> bool:
    if any(needle in text for needle in ("red bull racing", "racing e-scooter")):
        return False
    return any(needle in text for needle in ("energy drink", "monster energy", "red bull"))


def _is_desktop_gaming_pc_deal(text: str) -> bool:
    if any(needle in text for needle in ("laptop", "notebook")):
        return False
    return any(needle in text for needle in ("gaming pc", "gaming-pc", "desktop pc"))


def _keyword_fallback(title: str, description: str = "") -> list[str]:
    """Kleine Sicherheitsleine fuer verbotene oder leere LLM-Antworten.

    Das ist bewusst keine Vollklassifikation. Sie deckt nur Muster ab, die im
    Audit wiederholt falsch liefen oder bei Gutschein/Cashback-Deals oft genug
    direkt aus dem Titel ableitbar sind.
    """
    text = f"{title} {description}".lower()
    if _is_energy_drink_deal(text):
        return ["Energy-Drink"]
    if any(needle in text for needle in ("fruchtsaft", "valensina", "granini")):
        return ["Saft"]
    if any(needle in text for needle in ("regallautsprecher", "passiver lautsprecher")):
        return ["HiFi-Lautsprecher"]
    if _is_tv_deal(text):
        groups = ["Fernseher"]
        if "soundbar" in text:
            groups.append("Soundbar")
        return groups
    if _is_desktop_gaming_pc_deal(text):
        return ["Gaming-PC"]
    if any(needle in text for needle in ("kühlbox", "kuehlbox")):
        return ["Kühlbox"]
    if any(needle in text for needle in ("katzenfutter", "hundefutter", "trockenfutter")):
        return ["Tiernahrung"]
    if any(needle in text for needle in ("getriebeöl", "getriebeoel", "motoröl", "motoroel", "scheibenwischer")):
        return ["Auto-Zubehör"]
    if "kabelkanal" in text:
        return ["Kabelmanagement"]
    if any(needle in text for needle in ("lippenpflegestift", "lippenpflege")):
        return ["Lippenpflege"]
    if "toilettenpapier" in text:
        return ["Toilettenpapier"]
    if any(needle in text for needle in ("femdisc", "menstruationsscheibe", "menstruationstasse")):
        return ["Menstruationsprodukt"]
    if any(needle in text for needle in ("rabatt auf alles", "rabatt auf den gesamten einkauf", "newsletter")):
        return ["Shopping-Rabatt"]
    if "netto" in text and any(needle in text for needle in ("gutschein", "coupon", "rabatt")):
        return ["Shopping-Rabatt"]
    if "lieferando" in text and any(needle in text for needle in ("gutschein", "guthaben")):
        return ["Lieferdienst-Gutschein"]
    if any(needle in text for needle in ("restaurantgutschein", "restaurantgutscheine", "bon bon")):
        return ["Restaurant-Gutschein"]
    if any(needle in text for needle in ("schlemmerblock", "freizeitblock", "gutscheinbuch.de")):
        return ["Erlebnisgutschein"]
    if any(needle in text for needle in ("mypostcard", "postkarte")):
        return ["Fotodruck"]
    if any(needle in text for needle in ("mydays", "smartbox")):
        return ["Erlebnisgutschein"]
    if "herpa" in text:
        return ["Modellbau"]
    if any(needle in text for needle in ("deutschlandfahne", "fahne")):
        return ["Fanartikel"]
    if any(needle in text for needle in ("vape", "vapes", "e-zigarette")):
        return ["Vape"]
    if "decathlon" in text and "gutschein" in text:
        return ["Sport-Gutschein"]
    if any(needle in text for needle in ("fressnapf", "katzenfutter", "hundefutter", "trockenfutter")):
        return ["Tiernahrung"]

    rules = [
        (("chatgpt", "google ai pro", "gemini advanced", "claude pro", "perplexity pro"), "KI-Abo"),
        (("adobe", "office 365", "microsoft 365", "antivirus"), "Software-Abo"),
        (("google one", "icloud", "dropbox"), "Cloud-Speicher"),
        (("apple music", "spotify", "deezer"), "Musik-Abo"),
        (("blu-ray", "blu ray", "apple tv", "itunes", "amazon vod", "maxdome", "imdb"), "Film"),
        (("direktflug", "direktflüge", "flugticket", "airline"), "Flug"),
        (("privatleasing", "leasing"), "Auto-Leasing"),
        (("e-rocks", "elektroauto"), "Elektroauto"),
        (("soundbar",), "Soundbar"),
        (("regallautsprecher", "passiver lautsprecher"), "HiFi-Lautsprecher"),
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
        if _is_tv_deal(text):
            group = "Fernseher"
        elif _is_energy_drink_deal(text):
            group = "Energy-Drink"
        elif any(needle in text for needle in ("fruchtsaft", "valensina", "granini")):
            group = "Saft"
        elif any(needle in text for needle in ("regallautsprecher", "passiver lautsprecher")):
            group = "HiFi-Lautsprecher"
        elif _is_desktop_gaming_pc_deal(text):
            group = "Gaming-PC"
        elif any(needle in text for needle in ("kühlbox", "kuehlbox")):
            group = "Kühlbox"
        elif any(needle in text for needle in ("katzenfutter", "hundefutter", "trockenfutter")):
            group = "Tiernahrung"
        elif any(needle in text for needle in ("getriebeöl", "getriebeoel", "motoröl", "motoroel", "scheibenwischer")):
            group = "Auto-Zubehör"
        elif "kabelkanal" in text:
            group = "Kabelmanagement"
        elif any(needle in text for needle in ("lippenpflegestift", "lippenpflege")):
            group = "Lippenpflege"
        elif "toilettenpapier" in text:
            group = "Toilettenpapier"
        elif any(needle in text for needle in ("femdisc", "menstruationsscheibe", "menstruationstasse")):
            group = "Menstruationsprodukt"
        elif any(needle in text for needle in ("rabatt auf alles", "rabatt auf den gesamten einkauf", "newsletter")):
            group = "Shopping-Rabatt"
        elif "lieferando" in text and any(needle in text for needle in ("gutschein", "guthaben")):
            group = "Lieferdienst-Gutschein"
        elif any(needle in text for needle in ("restaurantgutschein", "restaurantgutscheine", "bon bon")):
            group = "Restaurant-Gutschein"
        elif any(needle in text for needle in ("mydays", "smartbox")):
            group = "Erlebnisgutschein"
        elif "herpa" in text:
            group = "Modellbau"
        elif any(needle in text for needle in ("deutschlandfahne", "fahne")):
            group = "Fanartikel"
        elif any(needle in text for needle in ("vape", "vapes", "e-zigarette")):
            group = "Vape"
        elif "decathlon" in text and "gutschein" in text:
            group = "Sport-Gutschein"
        elif any(needle in text for needle in ("fressnapf", "katzenfutter", "hundefutter", "trockenfutter")):
            group = "Tiernahrung"
        elif group == "PC-Spiel" and any(
            needle in text for needle in ("gaming pc", "gaming-pc")
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


def _rule_decision(title: str, description: str = "") -> list[str] | None:
    """Liefert nur eine eindeutige Entscheidung der bestehenden Regeln."""
    groups = _sanitize_groups([], title, description)
    return None if groups == ["Sonstige Deals"] else groups


def _record_decision(decision: str) -> None:
    with _decision_counts_lock:
        _decision_counts[decision] += 1


def get_decision_metrics() -> dict[str, int]:
    """Gibt Prozessmetriken ohne Deal-Inhalte oder Providerdaten zurück."""
    with _decision_counts_lock:
        return {
            "rule_decision": _decision_counts["rule_decision"],
            "llm_decision": _decision_counts["llm_decision"],
            "fallback_decision": _decision_counts["fallback_decision"],
        }


def _fallback_decision(title: str, description: str, reason: str) -> list[str]:
    _record_decision("fallback_decision")
    log.warning("classification route=fallback_decision provider=%s reason=%s",
                PROVIDER or "unsupported", reason)
    return _sanitize_groups([], title, description)


def _parse_remote_groups(content: object) -> tuple[list[str], str | None]:
    """Parst nur den bestehenden Textvertrag und meldet Contractfehler."""
    if not isinstance(content, str) or not content.strip():
        return [], "empty_output"

    text = content.strip()
    if text.startswith("{") or text.startswith("["):
        match = re.search(r"\[([^\]]+)\]", text)
        if not match:
            return [], "invalid_output"
        text = match.group(1)

    text = re.sub(r"[`\[\]\"']", "", text)
    text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.MULTILINE)
    parts = re.split(r"[,;\n]+", text)
    groups = [part.strip() for part in parts if part.strip() and len(part.strip()) < 60]
    if not groups:
        return [], "invalid_output"
    return groups, None


def classify(title: str, description: str = "") -> list[str]:
    """Gibt eine Liste feiner Produkt-Gruppen für einen Deal zurück."""
    global _remote_disabled_reason
    local_decision = _rule_decision(title, description)
    if local_decision is not None:
        _record_decision("rule_decision")
        log.info("classification route=rule_decision provider=local")
        return local_decision

    if not API_KEY:
        return _fallback_decision(title, description, "missing_api_key")
    if _remote_disabled_reason:
        return _fallback_decision(title, description, f"remote_disabled:{_remote_disabled_reason}")

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
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    if PROVIDER == "openrouter":
        headers.update({
            "HTTP-Referer": "https://github.com/mydealz-filter",
            "X-Title": "MyDealz Filter",
        })

    # Throttling: warte bis MIN_DELAY_SECONDS seit dem letzten Call vergangen sind
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < MIN_DELAY_SECONDS:
        time.sleep(MIN_DELAY_SECONDS - elapsed)

    content = None
    for attempt in range(4):
        _last_call_at = time.monotonic()
        try:
            resp = httpx.post(API_URL, json=payload, headers=headers, timeout=30.0)
            if resp.status_code in (401, 403):
                _remote_disabled_reason = f"HTTP {resp.status_code}"
                log.error("classification remote_disabled provider=%s reason=%s",
                          PROVIDER or "unsupported", _remote_disabled_reason)
                return _fallback_decision(title, description, _remote_disabled_reason)
            if resp.status_code == 429:
                wait = 2 ** attempt * 5  # 5, 10, 20, 40 s
                log.warning("classification provider=%s status=429 retry=%d wait=%ds",
                            PROVIDER or "unsupported", attempt + 1, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            response_data = resp.json()
            choices = response_data.get("choices") if isinstance(response_data, dict) else None
            message = choices[0].get("message") if isinstance(choices, list) and choices else None
            content = message.get("content") if isinstance(message, dict) else None
            groups, parse_error = _parse_remote_groups(content)
            if parse_error:
                if attempt == 3:
                    log.error("classification provider=%s output_contract=%s",
                              PROVIDER or "unsupported", parse_error)
                    break
                wait = 2 ** attempt
                log.warning("classification provider=%s output_contract=%s retry=%d wait=%ds",
                            PROVIDER or "unsupported", parse_error, attempt + 1, wait)
                time.sleep(wait)
                continue
            sanitized = _sanitize_groups(groups, title, description)
            if sanitized == ["Sonstige Deals"]:
                if attempt == 3:
                    log.error("classification provider=%s output_contract=forbidden_or_empty",
                              PROVIDER or "unsupported")
                    break
                wait = 2 ** attempt
                log.warning("classification provider=%s output_contract=forbidden_or_empty retry=%d wait=%ds",
                            PROVIDER or "unsupported", attempt + 1, wait)
                time.sleep(wait)
                continue
            _record_decision("llm_decision")
            log.info("classification route=llm_decision provider=%s", PROVIDER or "unsupported")
            return sanitized
        except Exception as e:
            log.error("classification provider=%s request_failed=%s",
                      PROVIDER or "unsupported", type(e).__name__)
            return _fallback_decision(title, description, type(e).__name__)

    if content is None:
        log.error("classification provider=%s retries_exhausted", PROVIDER or "unsupported")
    return _fallback_decision(title, description, "retries_exhausted")
