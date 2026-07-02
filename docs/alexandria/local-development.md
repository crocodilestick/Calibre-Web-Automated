# Lokale Entwicklungsumgebung (macOS)

Diese Dokumentation beschreibt, wie CWA Alexandria lokal auf dem Mac in einer isolierten Docker-Umgebung gestartet und live editiert werden kann, ohne eine produktive NAS-Bibliothek oder echte Zugangsdaten zu verwenden.

## 1. Voraussetzungen

- **Docker Desktop** auf dem Mac installiert und gestartet.
- GitHub CLI (`gh`) optional für PR-Workflows.

---

## 2. Initialisierung & Verzeichnisstruktur

Um eine frische, unbenutzte Testumgebung zu erzeugen, verwende das bereitgestellte Initialisierungs-Skript. Dieses legt die Ordnerstruktur unter `./local-dev` an und kopiert leere Datenbanken aus dem Projekt-Template.

Führe im Root-Verzeichnis des Repositories aus:
```bash
./init_local_dev.sh
```

### Die erzeugte Struktur (gitignored):
- `local-dev/config/`: Beinhaltet die Calibre-Web-Konfiguration und die SQLite-Datenbank `app.db`.
- `local-dev/calibre-library/`: Die Calibre-Bibliothek mit der leeren `metadata.db`.
- `local-dev/ingest/`: Das Ingest-Verzeichnis. Bücher, die hier abgelegt werden, verarbeitet CWA automatisch.

> [!WARNING]
> **Host-Artefakte im Container:**
> Da der gesamte Repository-Root nach `/app/calibre-web-automated` gemountet wird, sind auch die Ordner `.venv/` und `local-dev/` im Container sichtbar.
> **Wichtig:** Verwende diese Ordner im Calibre-Web-Interface (Admin-Bereich) **niemals** als Pfade! Nutze ausschließlich die dafür vorgesehenen Container-Mounts:
> - Konfiguration: `/config` (gemappt auf `./local-dev/config`)
> - Ingest-Ordner: `/cwa-book-ingest` (gemappt auf `./local-dev/ingest`)
> - Calibre-Bibliothek: `/calibre-library` (gemappt auf `./local-dev/calibre-library`)

---

## 3. Container starten und stoppen

Starte die lokale Entwicklungsumgebung mit:
```bash
docker compose -f docker-compose.local.yml up -d
```

- **Web-Interface**: Erreichbar unter [http://localhost:8085](http://localhost:8085)
- **Standard-Admin-Login**:
  - Benutzername: `admin`
  - Passwort: `admin123` (oder das in Calibre-Web standardmäßige `adminadmin`)

Stoppe die Umgebung mit:
```bash
docker compose -f docker-compose.local.yml down
```

---

## 4. Live-Editing (Codeänderungen testen)

Durch den Volume-Bind im Compose-File (`- .:/app/calibre-web-automated`) wird jeder lokale Edit an Python-Dateien (z. B. in `cps/` oder `kobo_sync_utils.py`) oder HTML/CSS-Templates sofort im laufenden Container abgebildet.

- **Templates (HTML/CSS)**: Werden bei jedem Seitenaufruf direkt vom Container neu geladen.
- **Python-Code (.py)**: Da Flask/Gunicorn im Container läuft, kann es sein, dass bei Code-Änderungen ein Neustart des Python-Prozesses nötig ist. Starte in diesem Fall einfach den Container neu:
  ```bash
  docker compose -f docker-compose.local.yml restart
  ```

---

## 5. Umgebung komplett zurücksetzen

Wenn du die Testdatenbanken komplett leeren und in den Ursprungszustand zurückversetzen möchtest:

1. Stoppe die Container (`docker compose -f docker-compose.local.yml down`).
2. Lösche das lokale Verzeichnis: `rm -rf local-dev/`
3. Initialisiere die Struktur neu: `./init_local_dev.sh`
4. Starte die Container wieder.

---

## 6. Optional: Kobo-Geräte-Synchronisation testen (ngrok)

Da der Kobo eReader für die Synchronisation zwingend eine verschlüsselte HTTPS-Verbindung benötigt (er akzeptiert kein lokales HTTP), kann das kabellose Synchronisieren lokal auf dem Mac nur über einen HTTPS-Tunnel getestet werden.

> [!CAUTION]
> **Sicherheitshinweis für Tunnel-Dienste:**
> - Nutze für diese Tunnel **niemals** echte Passwörter, produktive Calibre-Bibliotheken oder persönliche Kobo-Tokens.
> - Starte den Tunnel nur temporär während des aktiven Testens und beende ihn sofort danach.

### Schritt-für-Schritt mit ngrok:

1. Installiere ngrok (z. B. über Homebrew: `brew install ngrok`).
2. Starte ngrok auf dem lokalen Port `8085`:
   ```bash
   ngrok http 8085
   ```
3. Kopiere die generierte HTTPS-Url von ngrok (z. B. `https://1234-abcd.ngrok-free.app`).
4. Konfiguriere deinen Kobo eReader gemäß dem [Kobo-Sync Runbook](kobo-setup-runbook.md) mit dieser HTTPS-Domain.
