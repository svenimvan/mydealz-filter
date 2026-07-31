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
- Container `mydealz-filter`: `running`, Docker-Healthcheck `healthy`,
  0 Neustarts.
- `/healthz`, `/feed.xml` und Dashboard: HTTP 200.
- MyDealz-RSS und OpenRouter: aktuelle Polls mit HTTP 200.
- SQLite: `PRAGMA integrity_check = ok`, WAL aktiv.
- Datenbestand nach der Betriebsstabilisierung: 32.387 Deals, 1.286 Gruppen,
  35.946 Zuordnungen, 340 Klicks, 93.461 Impressionen und 1.728 Feed-Abrufe.

## Betriebsstabilisierung 2026-07-31

- Docker Compose prüft den bestehenden HTTP-Endpunkt `/healthz` alle 30 Sekunden;
  der Container wurde nach dem Deploy als `healthy` verifiziert.
- Strukturell ungültige OpenRouter-HTTP-200-Antworten werden nun bis zu drei Mal
  erneut versucht, bevor die lokale Fallback-Klassifikation greift.
- Vor beiden produktiven Eingriffen wurden konsistente SQLite-Snapshots im
  persistenten Datenvolume erstellt.
- Alle 20 aktiven Zuordnungen zu `Sonstige Deals` wurden neu klassifiziert;
  danach verblieben 0 aktive Zuordnungen.

Die Änderungen wurden mit Tests, Build, Container-Healthcheck, HTTP-Endpoints,
aktuellen Poll-/OpenRouter-Logs und SQLite-Integritätsprüfung verifiziert.

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
