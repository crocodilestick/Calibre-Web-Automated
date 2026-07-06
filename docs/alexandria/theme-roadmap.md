# Alexandria Theme Roadmap

Diese Roadmap baut auf der [Theme-Inventur](theme-inventory.md) auf. Sie
beschreibt die Schritte, mit denen Alexandria die Kontrolle ueber Optik,
Buchkarten und Preview-Interaktionen gewinnt, ohne den Calibre-Web-Automated-
Fork in einem grossen UI-Refactor zu versenken.

## Leitentscheidung

Wir behalten den aktuellen `main` als Basis. Die mitgemergten UI-Zwischenschritte
werden nicht zurueckgerollt, weil sie bereits wichtige Vorarbeit leisten:

- Preview-Overlay und entkoppelter Cover-/Titel-Klick.
- Shelf Gallery/Reader als erstes Alexandria-spezifisches Theme-System.
- Detailseiten-Politur und Schutz der neuen `.book-detail-card` vor alten
  caliBlur-DOM-Umbauten.
- Inventur der Theme-Schichten, Buchkarten, Klickpfade und Branding-Quellen.

Der aktuelle Stand ist aber noch kein fertiges globales Theme. Alexandria hat
momentan zwei konkurrierende UI-Autoritaeten:

- `caliBlur` als erzwungenes globales Dark-Theme mit CSS-Overrides und
  nachtraeglichen DOM-Rewrites.
- `cwa.css` plus neue Alexandria-Klassen fuer Shelf, Detailseite,
  Kobo-Dashboard und Preview-Overlay.

Ziel der folgenden Phasen ist, Alexandria Schritt fuer Schritt zur primaeren
optischen Autoritaet zu machen und caliBlur auf klar abgegrenzte Legacy- oder
Hilfsfunktionen zu reduzieren.

## Phase 0: Preview-Interaktion stabilisieren

Empfohlener Branch: `fix/preview-modal-caliblur`

### Ziel

Der Cover-Klick oeffnet das Preview-Overlay verlaesslich auf Home, Suche,
Autorenseite und Shelf, auch wenn caliBlur geladen ist.

### Umsetzung

- Primaerfix: In `main.js` einen delegierten Click-Handler fuer
  `.book-cover-link` verwenden.
- Der Handler soll das Preview-Overlay direkt oeffnen und das Fragment aus dem
  Link-`href` laden, statt sich auf Bootstrap-Data-Attribute zu verlassen.
- Die caliBlur-Whitelist nur als Notnagel nutzen. Der eigentliche Fix soll das
  Preview-Overlay unabhaengig von caliBlur machen.
- Beruecksichtigen, dass `caliBlur.js` aktuell nur `data-toggle` entfernt; die
  anderen Attribute bleiben im DOM. Der Fix kann sich daher weiterhin auf
  vorhandene Linkdaten stuetzen.
- Die erste Body-Klasse darf nicht zur neuen Abhaengigkeit werden, weil
  caliBlur selbst nur `bodyClass[0]` fuer seine Modal-Whitelist auswertet.

### Validierung

- Bestehende `tests/unit/test_preview_overlay.py` ausfuehren.
- Mindestens einen Browser-Smokecheck vorziehen:
  - Home: Cover-Klick oeffnet Overlay.
  - Suche: Cover-Klick oeffnet Overlay.
  - Autorenseite: Cover-Klick oeffnet Overlay.
  - Shelf: Cover-Klick oeffnet Overlay.
- `git diff --check`.

## Phase 1: Gemeinsame Buchkarte einfuehren

Empfohlener Branch: `refactor/book-card-template`

### Ziel

Buchkarten-Markup wird nicht mehr in mehreren Templates parallel gepflegt.

### Umsetzung

- Ein Jinja-Makro oder Include fuer Buchkarten erstellen.
- Abdecken:
  - Cover-Link / Preview-Link.
  - Titel-Link zur Detailseite.
  - Autorenzeile.
  - Serienzeile.
  - Rating/Sterne.
  - Read-Badge.
  - Zusatzklassen wie `isotope-item` oder `shelf-book-card`.
- Ersetzen in:
  - `index.html` mit Zufallsbuechern und Hauptliste.
  - `search.html`.
  - `author.html` fuer lokale Buchkarten.
  - `shelf.html`.
- Externe Ko-Autoren-/Goodreads-Karten auf der Autorenseite separat bewerten,
  weil sie fachlich nicht dieselbe Datenform haben.

### Validierung

- Render- oder Template-Assertions fuer mindestens `index`, `search`, `author`
  und `shelf`.
- Preview-Overlay-Smoke aus Phase 0 erneut ausfuehren.
- `git diff --check`.

## Phase 2: Globalen Alexandria-Theme-Zustand definieren

Empfohlener Branch: `feature/global-alexandria-theme-state`

### Ziel

Gallery/Reader wird von einer Shelf-Insel zu einem globalen Alexandria-
Ansichtsmodus fuer Buchlisten.

### Produktentscheidung

Fuer den ersten Schritt ist `localStorage` als Quelle akzeptabel, weil das
heutige Shelf-Verhalten bereits so funktioniert und keine Backend-Migration
braucht. Die Entscheidung muss aber bewusst dokumentiert werden:

- `localStorage`: pro Browser/Geraet, schnell und risikoarm.
- Datenbank/User-Setting: geraeteuebergreifend konsistent, aber mit Backend-
  und Einstellungsarbeit verbunden.

Langfristig kann ein User-Setting sinnvoll sein. Phase 2 soll diese Option
nicht verbauen.

### Umsetzung

- Allgemeine Body-Klassen einfuehren:
  - `cwa-theme-gallery`
  - `cwa-theme-reader`
- Alte Shelf-spezifische Klassen nur als Kompatibilitaetsschicht behalten oder
  gezielt migrieren.
- Die Klasse frueh setzen: blockierendes Inline-Script am Anfang von `<body>` in
  `layout.html`, um sichtbares Theme-Flackern beim Laden zu vermeiden.
- Home, Suche, Autorenseite und Shelf an dieselben Theme-Klassen anbinden.
- Den View-Umschalter nur dort sichtbar machen, wo er fachlich Sinn ergibt.

### Validierung

- Browsercheck ohne Theme-Flackern auf Home, Suche, Autorenseite und Shelf.
- Kein Bruch der mobilen Navigation.
- `git diff --check`.

## Phase 3: caliBlur-Grenzen ziehen

Empfohlener Branch: `refactor/caliblur-boundaries`

### Ziel

caliBlur ist nicht mehr heimliche globale UI-Autoritaet, sondern eine
abgegrenzte Legacy- und Hilfsschicht.

### Umsetzung

Die Kategorisierung folgt der Theme-Inventur:

- Behalten:
  - Mobile Sidebar-Unterstuetzung.
  - Readmore fuer lange Beschreibungen.
  - Gezielt nuetzliche Dropdown-Helfer.
- Isolieren:
  - Blur-Hintergruende.
  - Legacy-Detailseiten-Umbauten.
  - Sidebar-Verschiebungen.
- Entfernen oder umgehen:
  - Globale Modal-Attribut-Entfernung.
  - Pauschale DOM-Rewrites fuer neue Alexandria-Seiten.
  - Starre Buchkartenbreiten, sofern Alexandria-Karten aktiv sind.

Bei Aenderungen in `caliBlur.js` additiv und mergefreundlich arbeiten:

- Guards statt grosse Blockverschiebungen.
- Fruehe `return`-Pfade fuer Alexandria-Layouts.
- Keine kosmetischen Gesamtformatierungen.

### Langfristige Option

Alexandria kann spaeter ein eigener `config_theme`/`current_theme`-Wert werden,
bei dem `caliBlur.css` und `caliBlur.js` gar nicht mehr geladen werden. Bis
dahin bleibt `caliBlur` eine Kompatibilitaetsschicht unter Alexandria.

### Validierung

- Preview-Smoke erneut.
- Detailseite: neue `.book-detail-card` bleibt stabil.
- Mobile Sidebar pruefen.
- `git diff --check`.

## Phase 4: Alexandria Design Tokens einfuehren

Empfohlener Branch: `feature/alexandria-design-tokens`

### Ziel

Optische Entscheidungen werden zentral steuerbar, statt ueber verstreute
Einzelwerte und `!important`-Korrekturen zu leben.

### Umsetzung

Einen klaren Abschnitt in `cwa.css` pflegen fuer:

- Flaechen (`surface`).
- Textfarben.
- Akzentfarben.
- Covergroessen.
- Kartenabstaende.
- Hover- und Focus-Zustaende.
- Gallery- und Reader-Varianten.

Keine neue Design-System-Abstraktion erzwingen. Nur Werte zentralisieren, die
bereits mehrfach auftauchen oder fuer die globale Theme-Autoritaet notwendig
sind.

### Validierung

- Home, Suche, Autorenseite, Shelf Gallery, Shelf Reader und Preview visuell
  pruefen.
- Keine Textueberlagerungen auf mobilen Breiten.
- `git diff --check`.

## Phase 5: Branding sauber entscheiden

Empfohlener Branch: `feature/alexandria-branding`

### Ziel

Das sichtbare Produkt wirkt wie Alexandria, ohne Upstream-Nahe und technische
Herkunft unnoetig zu verschleiern.

### Umsetzung

- `config_calibre_web_title` weiterhin als konfigurierbare Instanzbezeichnung
  nutzen.
- Sichtbare harte Strings gezielt inventarisieren und bewerten:
  - Navbar/Instanztitel.
  - About/Admin.
  - Flash- und E-Mail-Texte.
  - CLI-Hilfen getrennt von UI-Branding behandeln.
- Produktentscheidung dokumentieren:
  - UI-Produktname: `Alexandria`.
  - Technischer Fork-/Upstream-Hinweis: z. B. `CWA Alexandria` in About oder
    Admin-Kontext.
  - Keine pauschale Umbenennung von Kommentaren, Lizenzhinweisen oder
    technischen Pfaden.

### Validierung

- String-Sweep auf sichtbare UI-Bereiche.
- Keine Aenderung an rechtlichen Headern oder Lizenzhinweisen.
- `git diff --check`.

## Phase 6: Browser-Matrix als Merge-Gate

Diese Phase ist kein eigenes Feature, sondern die Abschlussroutine fuer alle
groesseren UI-Schritte.

### Mindestmatrix

- Home.
- Suche.
- Autorenseite.
- Shelf Gallery.
- Shelf Reader.
- Detailseite.
- Preview-Overlay.
- Kobo-Dashboard.
- Einstellungen.

### Mindestpruefung

- Desktop und mobil.
- Cover-Klick, Titel-Klick und Preview-Schliessen.
- Keine groben Ueberlagerungen.
- Keine sichtbaren Theme-Flackerer.
- Keine Regression der mobilen Navigation.

## Empfohlene Reihenfolge

1. `fix/preview-modal-caliblur`
2. `refactor/book-card-template`
3. `feature/global-alexandria-theme-state`
4. `refactor/caliblur-boundaries`
5. `feature/alexandria-design-tokens`
6. `feature/alexandria-branding`

Die Reihenfolge ist bewusst konservativ: Erst Interaktion stabilisieren, dann
Markup vereinheitlichen, dann Theme-Zustand globalisieren, danach caliBlur
zurueckdraengen und erst zum Schluss das visuelle System breiter ausrollen.
