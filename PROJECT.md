---
projektstatus: aktiv
projekt: mydealz-filter
lebensbereich: technik_infrastruktur
nebenbereiche: []
---

# MyDealz Filter – technischer Projektvertrag

## Ziel und Auftrag

Dieses Repository enthält einen persönlichen, selbstlernenden Filter für den
MyDealz-RSS-Feed.

Der Dienst ruft den MyDealz-Feed ab, speichert Deal-Daten, klassifiziert
Inhalte über OpenRouter, bewertet Relevanz anhand lokaler Interaktionen und
stellt einen gefilterten RSS-Feed sowie ein lokales Dashboard bereit.

## Scope

- Quellcode und Tests des MyDealz-Filters
- Polling und Verarbeitung des MyDealz-RSS-Feeds
- OpenRouter-basierte Klassifikation
- lokale SQLite-Datenhaltung
- Bayesianisches Scoring und Impression-Auswertung
- FastAPI-Feed, Dashboard und Admin-Endpunkte
- Docker- und Compose-Deployment
- technische und operative Dokumentation dieses Repositories

## Nicht-Scope

- Änderung oder Kontrolle des ursprünglichen MyDealz-Feeds
- öffentliche oder kommerzielle Weiterverbreitung ohne gesonderte Prüfung
- Multi-User-Betrieb
- öffentliche Internetfreigabe
- PKP- oder Obsidian-Kopie des Repositories
- automatische Synchronisation mit PKP
- Speicherung von Secrets im Repository
- Verwaltung anderer Homelab- oder Blog-Projekte
- automatische Umbenennung oder Verschiebung des Workspace

## Projektstatus und aktuelle Phase

- Projektstatus: `aktiv`
- Aktuelle Phase: Betrieb und Pflege
- Der technische Dienst ist implementiert.
- Der produktive Laufzeitstatus wurde am 2026-07-31 geprüft; der Dienst läuft
  im LXC 100.

## Letzte Betriebsprüfung

Prüfung am 2026-07-31 gegen die dokumentierte Laufzeitquelle:

- LXC 100 auf dem Proxmox-Host: `running`.
- Container `mydealz-filter`: `running`, 0 Neustarts, gestartet am 2026-07-02;
  Docker-Healthcheck ist nicht konfiguriert.
- `/healthz`, `/feed.xml` und Dashboard: HTTP 200.
- MyDealz-RSS und OpenRouter: aktuelle Polls mit HTTP 200.
- SQLite: `PRAGMA integrity_check = ok`, WAL aktiv.
- Datenbestand: 32.380 Deals, 1.285 Gruppen, 35.933 Zuordnungen, 340 Klicks,
  93.337 Impressionen und 1.725 Feed-Abrufe.

Nicht dringende Befunde:

- `Sonstige Deals` ist aktuell noch 20 Deals zugeordnet, obwohl der letzte
  Klassifizierungs-Audit diese Zuordnung mit 0 ausweist. Ein erneuter
  Klassifizierungs-Audit ist sinnvoll.
- Ein einzelner OpenRouter-Response war am 2026-07-31 um 18:04 Uhr strukturell
  unerwartet (`'choices'`); der Poll wurde trotzdem erfolgreich abgeschlossen.

Die Prüfung änderte weder Anwendung, Deployment noch Runtime-Daten.

## Verantwortlichkeit

- Verantwortlich: Repository-Eigentümer
- Analyse und Entscheidungsvorbereitung: ChatGPT
- Repository-Änderungen: Codex ausschließlich nach ausdrücklicher Freigabe
- Produktive Betriebs- und Sicherheitsänderungen benötigen eine gesonderte
  menschliche Freigabe

Keine konkrete Person ergänzen, sofern sie im Repository nicht eindeutig
dokumentiert ist.

## Technische Primärquelle und Laufzeitquelle

- Technische Primärquelle:
  dieses Git-Repository
- Workspace:
  `/Users/Shared/Projects/gefilterter MyDealz RSS Feed`
- Branch:
  `main`
- Remote:
  bestehendes `origin`
- Zentrale technische Dateien:
  `README.md`, `app/`, `tests/`, `Dockerfile`, `docker-compose.yml`,
  `requirements.txt`
- Laufzeitquelle:
  Docker-Image und Compose-Konfiguration
- Externe Laufzeitkonfiguration:
  `.env`
- Persistente Runtime-Daten:
  `./data:/data`
- Datenbank:
  `/data/mydealz.db`
- Container:
  `mydealz-filter`
- Port:
  `5102`
- Scheduler:
  eingebetteter APScheduler
- Statisch dokumentierte, nicht verifizierte Deploymentgrenze:
  LXC 100 auf `192.168.178.200`

Repository und Laufzeitdaten bleiben getrennte Quellen.

## Werkzeug- und PKP-Zuordnung

- ChatGPT:
  Analyse, Klärung und Entscheidungsvorbereitung
- Codex:
  reproduzierbare Umsetzung ausdrücklich freigegebener Änderungen
- Git:
  Versionshistorie, Review und Rückfall
- PKP:
  kuratierte Zusammenfassung stabilisierter Erkenntnisse, Entscheidungen,
  Risiken und technischer Verweise

Die PKP ist keine technische Primärquelle und enthält keine Repository-Kopie.

## Autoritäts- und Konfliktregel

- Technische Implementierung:
  Repository und Quellcode
- Tatsächlicher Laufzeitstatus:
  Container-, Datenbank- und Deploymentumgebung
- Architekturentscheidungen:
  freigegebene ADRs im Repository `personal-platform`
- Projektauftrag, Scope und Workspace-Zuordnung:
  `PROJECT.md`
- Operative Aufgaben:
  eine spätere `TODO.md`, ausschließlich bei belegtem Bedarf
- Stabilisiertes Wissen und zusammengefasster Status:
  PKP-Projektnotiz

Es gibt keine automatische Synchronisation.

Widersprüche werden in der fachlich zuständigen Primärquelle korrigiert.

## Sicherheits-, Datenschutz- und Nutzungsgrenzen

- Keine Secrets, API-Schlüssel oder Passwörter im Repository
- `.env`, Datenbank und Runtime-Daten bleiben außerhalb der Versionskontrolle
- Deal-Titel, Dealtext und Original-URLs werden verarbeitet
- Teile der Dealbeschreibung werden an OpenRouter übertragen
- Klicks, Impressionen, Zeitstempel und Gruppenwerte bilden lokale
  Nutzungs- und Interessensdaten
- Admin-Endpunkte besitzen laut bestehender Dokumentation keine
  Authentifizierung
- Die Compose-Konfiguration verwendet HTTP
- Keine öffentliche Internetfreigabe ohne Authentifizierung und TLS
- Die Repository-Lizenz gilt nur für den eigenen Code
- Nutzungs- und Weiterverbreitungsrechte des MyDealz-Feeds sind im Repository
  nicht belegt
- Keine öffentliche oder kommerzielle Weiterverwendung als erlaubt darstellen
- Keine PKP-Kopien, Symlinks oder automatischen Sync-Mechanismen

## Abnahmekriterien

1. README verlinkt `PROJECT.md`.
2. Projektauftrag und technische Primärquelle sind eindeutig.
3. Repository, externe Konfiguration und Runtime-Daten sind klar getrennt.
4. Bestehende Anwendung und Deploymentkonfiguration bleiben unverändert.
5. Keine zusätzlichen Netzwerkzugriffe oder Schreibrechte entstehen.
6. Keine `TODO.md` wird ohne belegte Aufgaben angelegt.
7. Keine PKP-Dateien, Symlinks, Vollkopien oder Sync-Mechanismen entstehen.
8. Die Änderung ist über Git nachvollziehbar und gezielt rücknehmbar.

## Risiken

- aktueller produktiver Laufzeitstatus unbekannt
- fehlende Authentifizierung der Admin-Endpunkte
- HTTP statt TLS
- externe Datenübertragung an OpenRouter
- lokale Nutzungs- und Interessensdaten
- MyDealz-Nutzungs- und Weiterverbreitungsrechte nicht belegt

## Nächste Überprüfung

Nach Abschluss des vierten A-019-Piloten.

Zusätzliche Auslöser:

- Änderung des Datenflusses
- Änderung des OpenRouter-Modells oder Providers
- Änderung der Deploymentumgebung
- öffentliche oder externe Freigabe
- Einführung von Authentifizierung oder TLS
- Änderung der MyDealz-Feed-Nutzung
- neue belastbare operative Aufgaben
