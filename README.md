# MyDealz Filter

Ein selbstlernender RSS-Filter für [mydealz.de](https://www.mydealz.de), der
deinen Klick-Verlauf nutzt um irrelevante Deals automatisch auszublenden.

## Workspace-Dokumente

- [Projektvertrag](PROJECT.md)

- **Implicit Feedback**: Du musst nicht aktiv bewerten — was du nicht anklickst,
  zählt als "nicht interessant".
- **Rule-first-LLM-Klassifikation**: Eindeutige lokale Regeln entscheiden zuerst;
  nur Grenzfälle gehen an Scaleway Mistral Small. Jeder Deal wird in eine feine
  Produkt-Gruppe einsortiert (z.B. `iPhone`, `3D-Drucker`, `KI-Abo`, `Bohrhammer`),
  nicht in die groben MyDealz-Oberkategorien.
- **Bayes-Bandit-Scoring**: Pro Gruppe wird eine Beta-Verteilung geführt; das
  System filtert Gruppen mit niedrigem geschätzten Klick-Score, mit
  Exploration (Thompson Sampling) damit auch neue/unsichere Gruppen Chancen
  bekommen.
- **Manuelle Overrides**: Block / Allow / Reset für einzelne Gruppen über das
  Dashboard.

## Architektur

```
mydealz.de/rss/alles  →  [Poller]  →  SQLite
                           ↓
                      [Regeln → LLM-Klassifikator]  (Scaleway Mistral Small)
                           ↓
                        Deal-Tags ── /feed.xml  →  dein RSS-Reader
                                          ↓
                                    [Click-Tracker]  /click/<id>  →  mydealz.de
                                          ↓
                                  α/β-Update pro Gruppe
                                          ↓
                                    [Bayes-Scorer]  →  Filter-Entscheidung
```

- **Stack**: Python 3.12, FastAPI, SQLite (WAL), APScheduler, Jinja2
- **Deployment**: Docker (single container), Compose-Datei inklusive

## Funktionsweise im Detail

1. **Poller** (alle 10 min): holt MyDealz-RSS-Feed, speichert neue Deals.
2. **Klassifikator**: lokale Regeln entscheiden eindeutige Fälle. Nur unsichere
   Fälle werden per Scaleway Mistral Small in 1–3 feine Produkt-Gruppen
   einsortiert. Bei Providerfehlern greift die lokale Fallback-Logik; es gibt
   keinen automatischen Wechsel zu OpenRouter. Bereits bekannte Gruppen werden
   dem Modell mitgegeben, damit das Vokabular konsistent bleibt.
3. **Feed-Endpoint** `/feed.xml`: liefert gefilterten RSS mit umgeschriebenen
   Click-Tracking-Links und einem unverwechselbaren GUID-Präfix
   (`mydealz-filter-<id>`) damit RSS-Reader ihn als eigenständigen Feed
   behandeln. Der komplette Dealtext wird zusätzlich als `content:encoded`
   ausgegeben, damit RSS-Reader ihn für Offline-Lesen speichern können.
4. **Click-Tracker** `/click/<id>`: registriert den Klick (mit 60s-Dedup für
   Reader-Prefetch), erhöht α für die zugehörigen Gruppen, redirected dann
   per 302 zum echten Deal.
5. **Impression-Settlement** (alle 30 min): Deals die in den letzten 6h im
   Feed waren aber nicht geklickt wurden, erhöhen β für ihre Gruppen — aber
   nur wenn der Feed in den letzten 6h auch tatsächlich abgerufen wurde
   (sonst bestrafen wir Gruppen nur weil du den Reader nicht offen hattest).
6. **Decay** (sonntags 3:00): alle α/β werden mit 0,97 multipliziert →
   Halbwertszeit ≈ 23 Wochen. So passt sich das System langsam an
   veränderte Interessen an.
7. **Filter-Entscheidung**: ODER-Logik mit Mindest-Sample-Größe 15. Ein Deal
   kommt durch wenn mindestens eine seiner Gruppen entweder zu wenig Daten
   hat (Unschuldsvermutung) oder einen Score ≥ 8 % erreicht.

## Endpoints

| Pfad                                  | Zweck                                                 |
|---------------------------------------|-------------------------------------------------------|
| `GET  /feed.xml`                      | Gefilterter RSS-Feed (in deinen Reader eintragen)     |
| `GET  /click/<id>`                    | Klick-Tracker → 302 Redirect zum echten Deal          |
| `GET  /`                              | Dashboard: Gruppen, Scores, Status-Filter, Aktionen   |
| `POST /groups/<name>/override`        | Manuell Block / Allow / Auto setzen (Form-Body)       |
| `POST /groups/<name>/reset`           | α/β auf 0 + Override entfernen                        |
| `POST /admin/reclassify-unknown`      | Alle `unklassifiziert`-Deals neu klassifizieren       |
| `POST /admin/reclassify-group/<name>` | Alle Deals einer Gruppe neu klassifizieren            |
| `GET  /healthz`                       | Healthcheck                                           |

## Setup

### Voraussetzungen

- Docker + Docker Compose
- Scaleway Generative-API-Key aus der bestehenden Secret-Verwaltung

### Installation

```bash
git clone https://github.com/<user>/mydealz-filter.git
cd mydealz-filter

# .env mit dem Secret aus der bestehenden Secret-Verwaltung anlegen
cp .env.example .env
chmod 600 .env

# Starten
docker compose up -d

# Erreichbar unter http://<host>:5102
```

### Konfiguration (Umgebungsvariablen in `docker-compose.yml`)

| Variable                  | Default                                | Bedeutung                                    |
|---------------------------|----------------------------------------|----------------------------------------------|
| `CLASSIFIER_PROVIDER`     | `scaleway`                             | Aktiver Provider (`scaleway` oder `openrouter`) |
| `SCALEWAY_API_KEY`        | —                                      | Scaleway-API-Key (in `.env`)                |
| `SCALEWAY_API_URL`        | `https://api.scaleway.ai/v1/chat/completions` | Scaleway-Chat-Completions-Endpunkt      |
| `CLASSIFIER_MODEL`        | `mistral-small-3.2-24b-instruct-2506`  | Modell-ID für die Klassifikation             |
| `CLASSIFIER_MIN_DELAY`    | `0.2`                                  | Mindest-Sekunden zwischen API-Calls          |
| `POLL_INTERVAL_MINUTES`   | `10`                                   | Wie oft MyDealz-RSS abgefragt wird           |
| `IMPRESSION_WINDOW_HOURS` | `6`                                    | Zeitfenster bevor Nicht-Klicks gezählt werden|
| `PUBLIC_BASE_URL`         | `http://localhost:5102`                | Basis-URL für Click-Redirect-URLs            |

## Offline-Lesen / Volltext

MyDealz liefert den Dealtext bereits im RSS. Der Poller speichert den längsten
verfügbaren Inhalt (`content:encoded`, falls vorhanden, sonst
`summary`/`description`) und aktualisiert bekannte Deals, wenn der aktuelle
RSS-Snapshot einen vollständigeren Text enthält.

`/feed.xml` gibt diesen Text sowohl in `description` als auch in
`content:encoded` aus. `description` steht zuerst als kompatibler Fallback,
`content:encoded` enthält den Volltext für Reader, die Vollinhalte separat
speichern. Der Hauptlink bleibt der lokale Click-Tracker (`/click/<id>`), damit
das Lernsystem weiter Klicksignale bekommt; im Volltext steht zusätzlich ein
Link zum Originaldeal.

Da das Projekt keinen Gelesen-Status aus deinem RSS-Reader kennt, werden beim
nächsten Poll nur Deals aus dem aktuellen MyDealz-RSS-Snapshot nachträglich
aufgefrischt. Für eine sofortige Auffrischung kannst du den manuellen Poll aus
den operativen Befehlen ausführen.

### Expliziter Rollback

```yaml
# Nur fuer einen bewussten Rollback setzen; kein automatischer Fallback:
- CLASSIFIER_PROVIDER=openrouter
- CLASSIFIER_MODEL=google/gemini-2.5-flash-lite
# OPENROUTER_API_KEY bleibt im .env erhalten.
```

## DB-Schema

| Tabelle       | Inhalt                                                          |
|---------------|-----------------------------------------------------------------|
| `deals`       | `mydealz_id`, `title`, `description`, `url`, `first_seen`       |
| `deal_groups` | `(deal_id, group_name)` — n:m zwischen Deals und Produkt-Gruppen|
| `groups`      | `name`, `alpha`, `beta`, `manual_override` (allow/block/NULL)   |
| `clicks`      | `deal_id`, `clicked_at`                                         |
| `impressions` | `deal_id`, `shown_at`, `counted` (Bool: schon in β verbucht?)   |
| `feed_pulls`  | `pulled_at` — für 6h-Fenster-Logik im Settlement                |

## Operative Befehle

```bash
# Logs in Echtzeit
docker logs -f mydealz-filter

# Manueller Poll (statt 10-Min-Intervall)
docker exec -w /app mydealz-filter python3 -c "from app.poller import poll_once; print(poll_once())"

# Alle Deals einer Gruppe neu klassifizieren (bei Fehlklassifikations-Wellen)
curl -X POST "http://localhost:5102/admin/reclassify-group/Büroartikel"

# DB direkt einsehen (Container-intern)
docker exec mydealz-filter sqlite3 /data/mydealz.db  # falls sqlite3 installiert
```

## Entwicklung / Tests

```bash
# Klassifizierungsregeln, Provider-Routing und Fallbacks testen
python3.12 -m unittest discover -s tests -v
```

## Klassifizierungs-Audit 2026-05-24

Die produktive Klassifizierung wurde erneut geprüft. Ergebnis:

- OpenRouter-Calls laufen stabil mit `200 OK`.
- Aktive Zuordnungen zu `Gutschein`, `Payback`, `Cashback`, `unklassifiziert`,
  `keine passende Gruppe gefunden` und `Sonstige Deals` stehen bei 0.
- Neue Schutzregeln korrigieren u.a. Fernseher, Desktop-Gaming-PCs, Kühlboxen,
  Tiernahrung, Auto-Zubehör, Kabelmanagement, Lippenpflege, Toilettenpapier,
  Menstruationsprodukte und reine Shopping-Rabatte.
- Kontext-Ausschlüsse verhindern, dass TV-Remote-Apps, Gaming-Laptops oder
  Red-Bull-Racing-Bundles durch einzelne Stichworte falsch umklassifiziert
  werden.

## Klassifizierungs-Audit 2026-05-29

Wiederholungsprüfung der produktiven Klassifizierung:

- Healthcheck OK, OpenRouter-Calls laufen weiter mit `200 OK`.
- Produktive DB nach Bereinigung: 3467 Deals, 396 Gruppen, 3874
  Deal-Gruppen-Zuordnungen.
- Aktive Zuordnungen zu `Gutschein`, `Payback`, `Cashback`, `unklassifiziert`,
  `keine passende Gruppe gefunden` und `Sonstige Deals` stehen bei 0.
- Neue Schutzregeln klassifizieren Gutschein-/Fallbackfälle wie Lieferando,
  Restaurantgutscheine, mydays/Smartbox, Herpa, Decathlon, Vapes,
  Deutschlandfahnen und Fressnapf-Zugaben in stabilere Produktgruppen.
- `Sonstige Deals` wird nicht mehr als normales LLM-Ergebnis akzeptiert,
  sondern löst die lokale Fallback-Klassifikation aus.

## Betriebsprüfung 2026-07-31

Der produktive Dienst im dokumentierten LXC 100 wurde ohne Änderungen geprüft:

- Container läuft seit 2026-07-02 ohne Neustarts; `/healthz`, Dashboard und
  `/feed.xml` antworten mit HTTP 200.
- Poller und Scheduler laufen im 10-Minuten-Takt; MyDealz-RSS und OpenRouter
  lieferten in den aktuellen Polls HTTP 200.
- SQLite meldet `PRAGMA integrity_check = ok` und verwendet WAL.
- Bestand: 32.380 Deals, 1.285 Gruppen, 35.933 Deal-Gruppen-Zuordnungen,
  340 Klicks, 93.337 verbuchte Impressionen und 1.725 Feed-Abrufe.

Zum Prüfzeitpunkt bestanden zwei nicht dringende Befunde: Es fehlte ein
Docker-Healthcheck, und `Sonstige Deals` war noch 20 Deals zugeordnet. Am
2026-07-31 trat zudem ein einzelner strukturell unerwarteter OpenRouter-Response
auf; der betroffene Poll wurde mit Fallback-Verhalten abgeschlossen.

## Betriebsstabilisierung 2026-07-31

Die offenen Befunde wurden anschließend behoben und produktiv verifiziert:

- Compose prüft `/healthz` nun alle 30 Sekunden mit dem bereits vorhandenen
  Python-Laufzeitsystem; nach dem Deploy meldete Docker `healthy`.
- Eine HTTP-200-Antwort ohne verwertbares OpenRouter-`choices`-Feld wird bis zu
  drei Mal erneut versucht (1, 2 und 4 Sekunden), bevor der lokale Fallback
  verwendet wird.
- Vor den produktiven Änderungen wurden zwei konsistente SQLite-Snapshots im
  persistenten Datenvolume angelegt.
- Die 20 aktiven `Sonstige Deals`-Zuordnungen wurden neu klassifiziert. Zwei
  konkrete Restfälle erhielten eng gefasste Fallbacks (`Erlebnisgutschein` und
  `Fotodruck`); danach blieben 0 aktive Zuordnungen übrig.
- Container, `/healthz`, `/feed.xml`, aktuelle Poll-/OpenRouter-Logs und
  `PRAGMA integrity_check` wurden nach dem Deploy erneut erfolgreich geprüft.

## Dashboard-Features

- **Filter-Bar**: schnell zwischen "Alle", "Nur Auto", "Nur Block", "Nur Allow"
  umschalten — perfekt zum effizienten Triagieren neuer Gruppen
- **AJAX-Updates**: Block/Allow/Reset funktioniert ohne Page-Reload, deine
  Scroll-Position bleibt erhalten
- **Progressive Enhancement**: ohne JavaScript fällt es auf klassischen
  Form-Submit zurück (mit Anker-Redirect für Scroll-Restoration)
- **Filter-Persistenz**: deine Filter-Auswahl bleibt über Reloads erhalten
  (localStorage)

## Limitationen / Bekannte Einschränkungen

- **MyDealz-RSS hat nur 30 Items pro Snapshot** → der Feed rotiert schnell;
  beim 10-Min-Poll können bei sehr hohem Deal-Aufkommen vereinzelt Items
  verpasst werden.
- **Offline-Lesen zielt auf Text** — der Dealtext wird im Feed als Volltext
  ausgeliefert. Bilder werden nicht lokal gecacht; ob Bilder offline verfügbar
  sind, hängt vom jeweiligen RSS-Reader ab.
- **HTTP only** — Klick-Tracking läuft unverschlüsselt im lokalen Netz.
  Für Internet-Exposition einen Reverse-Proxy mit TLS davor setzen.
- **Single-User** — keine Auth, kein Multi-Account. Designed für persönlichen
  Heimserver-Einsatz.
- **LLM-Klassifikationen können daneben liegen** — typischer Fall: Modell
  rät bei ungewöhnlichen Produktnamen. Über `/admin/reclassify-group` oder
  manuellen Eingriff korrigierbar.
- **Scaleway-Fehler** — bei fehlendem/ungültigem API-Key, Rate-Limits, Timeouts,
  5xx oder ungültigem Output nutzt der Klassifikator die lokale Fallback-Logik.
  Nicht erkennbare Fälle landen als `Sonstige Deals`; es erfolgt kein
  automatischer Wechsel zu OpenRouter.

## Lizenz

MIT
