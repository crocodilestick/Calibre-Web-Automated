# Kobo-Sync Runbook

Dieses Runbook dokumentiert das funktionierende Muster fuer einen Kobo eReader, der Calibre-Web-Automated ueber das Internet erreicht. Es ist bewusst bereinigt: echte Tokens, konkrete Hostnamen und private IPs gehoeren nicht in versionierte Projektdokumente.

## Ziel

- Kobo kann kabellos Buecher ueber Calibre-Web-Automated synchronisieren.
- Zugriff funktioniert auch ausserhalb des Heimnetzes.
- Kobo-Sammlungen/Regale werden aus Calibre-Web heraus erzeugt.
- Lesestaende und Kobo-Sync-Endpunkte laufen ueber eine HTTPS-Domain.

## Beispiel-Platzhalter

```text
PUBLIC_KOBO_DOMAIN=kobo.example.org
NAS_LAN_IP=192.168.x.y
CALIBRE_WEB_PORT=8083
PUBLIC_HTTPS_PORT=443
DUCKDNS_TOKEN=<secret>
KOBO_SYNC_TOKEN=<secret>
```

## Architektur

```text
Kobo eReader
  -> https://PUBLIC_KOBO_DOMAIN
  -> Router Portweiterleitung 443
  -> NAS / Nginx Proxy Manager
  -> http://127.0.0.1:CALIBRE_WEB_PORT
  -> Calibre-Web-Automated
```

Wichtig ist die Trennung zwischen externem HTTPS und internem HTTP. Der Kobo spricht nach aussen HTTPS. Der Reverse Proxy spricht intern mit Calibre-Web typischerweise unverschluesselt ueber HTTP.

## Finale Konfiguration

### DuckDNS oder vergleichbarer DynDNS-Dienst

Der Kobo kann kein Tailscale/VPN nutzen. Deshalb braucht er eine oeffentliche Domain, die auf die aktuelle Heim-IP zeigt.

Beispiel fuer einen DuckDNS-Container:

```yaml
services:
  duckdns:
    image: lscr.io/linuxserver/duckdns:latest
    container_name: duckdns
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Berlin
      - SUBDOMAINS=<duckdns-subdomain>
      - TOKEN=${DUCKDNS_TOKEN}
    restart: unless-stopped
```

Secrets gehoeren in `.env` oder in die sichere Konfiguration der jeweiligen NAS-/Container-Umgebung, nicht in Git.

### Nginx Proxy Manager

Bei der beobachteten NAS-/Docker-Konstellation war der Host-Netzwerkmodus fuer Nginx Proxy Manager die stabile Variante, weil sonst interne Weiterleitung/Loopback blockiert wurde.

```yaml
services:
  app:
    image: jc21/nginx-proxy-manager:latest
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./data:/data
      - ./letsencrypt:/etc/letsencrypt
```

Proxy Host:

```text
Domain Name: PUBLIC_KOBO_DOMAIN
Scheme: http
Forward Hostname/IP: 127.0.0.1
Forward Port: CALIBRE_WEB_PORT
SSL: Let's Encrypt
Force SSL: enabled
HTTP/2 Support: enabled
```

Advanced:

```nginx
proxy_buffer_size 128k;
proxy_buffers 4 256k;
proxy_busy_buffers_size 256k;
```

Diese Buffer-Werte waren fuer den Kobo-Sync wichtig, weil `/v1/library/sync` sonst mit `upstream sent too big header` scheitern konnte.

### Router

```text
TCP 80  -> NAS:80
TCP 443 -> NAS:443
```

Port 80 wird typischerweise fuer Let's-Encrypt-HTTP-Challenges gebraucht. Der Kobo-Sync selbst sollte ueber 443 laufen.

### Calibre-Web-Automated

Admin/Feature-Konfiguration:

```text
Kobo-Sync aktivieren: enabled
Unbekannte Anfragen an den Kobo Store weiterleiten: enabled
KOReader-Sync aktivieren: enabled
Externer Server-Port: 443
```

Benutzerprofil:

```text
Kobo-Sync fuer diesen Benutzer aktivieren: enabled
```

Der externe Server-Port ist wichtig, weil Calibre-Web download-Links mit dem internen Port erzeugen kann, zum Beispiel `:8083`. Von aussen ist aber nur 443 erreichbar.

### Kobo eReader

Datei auf dem Kobo:

```text
.kobo/Kobo/Kobo eReader.conf
```

Bereinigtes Muster:

```ini
[OneStoreServices]
account_page=https://www.kobo.com/account/settings
account_page_rakuten=https://my.rakuten.co.jp/
api_endpoint=https://PUBLIC_KOBO_DOMAIN/kobo/KOBO_SYNC_TOKEN
image_host=https://PUBLIC_KOBO_DOMAIN
image_url_quality_template=https://PUBLIC_KOBO_DOMAIN/kobo/KOBO_SYNC_TOKEN/{ImageId}/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg
image_url_template=https://PUBLIC_KOBO_DOMAIN/kobo/KOBO_SYNC_TOKEN/{ImageId}/{Width}/{Height}/false/image.jpg
```

## Troubleshooting

| Symptom | Wahrscheinliche Ursache | Fix |
| --- | --- | --- |
| Kobo erreicht Tailscale-IP nicht | Kobo hat keinen VPN-Client | Oeffentliche HTTPS-Domain mit DynDNS verwenden |
| Webseite laedt, Kobo-Sync scheitert mit 502 | Proxy erreicht Calibre-Web intern nicht | NPM-Netzwerkmodus und Forward-Ziel pruefen; bei Bedarf `network_mode: host` und `127.0.0.1` verwenden |
| `wrong version number while SSL handshaking to upstream` | Proxy spricht intern HTTPS mit einem HTTP-Dienst | Scheme in NPM auf `http` stellen |
| `no such table: book_format_checksums` | Calibre-Web-Datenbankmigration fuer Checksummen fehlt | KOReader-Sync aktivieren und Container neu starten |
| `/v1/library/sync` scheitert mit `upstream sent too big header` | Proxy-Header-Puffer zu klein | `proxy_buffer_size`, `proxy_buffers`, `proxy_busy_buffers_size` erhoehen |
| Download-Link enthaelt `:8083` | Externer Server-Port in Calibre-Web falsch | Externer Server-Port auf `443` setzen |
| Alte Kobo-Sammlungen bleiben bestehen | Kobo behandelt sie als lokale Sammlungen | Kobo-Datenbank nach Backup bereinigen |

## Kobo-Sammlungen bereinigen

Achtung: Dieser Eingriff veraendert die SQLite-Datenbank auf dem Kobo direkt. Vorher immer ein Backup der Datei `KoboReader.sqlite` anlegen.

Backup-Beispiel auf macOS:

```bash
cp /Volumes/KOBOeReader/.kobo/KoboReader.sqlite ~/Desktop/KoboReader.sqlite.backup
```

Bereinigung nur der Sammlungen:

```bash
sqlite3 /Volumes/KOBOeReader/.kobo/KoboReader.sqlite "DELETE FROM Shelf; DELETE FROM ShelfContent;"
```

Danach Kobo sauber auswerfen und per WLAN erneut synchronisieren. Die aktiven Sammlungen sollten dann aus Calibre-Web neu aufgebaut werden.

## Alexandria-Learnings

Diese Setup-Erfahrung sollte spaeter in Alexandria sichtbar werden:

- Kobo-Sync braucht eine eigene Diagnoseansicht, weil Browser-Erreichbarkeit allein nicht reicht.
- Die UI sollte externe URL, internen Port, Proxy-Scheme und externen Server-Port getrennt anzeigen.
- Eine Warnung sollte erscheinen, wenn generierte Download-URLs einen internen Port enthalten.
- Sehr breite Kobo-Sync-Regeln sollten vor dem Aktivieren eine Vorschau zeigen.
- Datenbankeingriffe auf dem Kobo gehoeren in ein Runbook mit Backup-Schritt, nicht in normale UI-Flows.
