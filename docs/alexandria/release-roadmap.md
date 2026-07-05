# Alexandria Release-Roadmap

Diese Roadmap beschreibt die geplanten Ausbaustufen und UX-Verbesserungen für Alexandria. Sie dient als Orientierung für künftige Arbeitsschritte und bündelt die konzeptionellen Leitlinien für Kobo-Synchronisation, Einstellungen, Sammlungen und Übersetzungen.

---

## 1. Kurzfristig / Nächster Schritt: Transparenz („Warum ist dieses Buch auf/nicht auf dem Kobo?“)

Bisher wurden die Berechnungen (Sync-Erlaubnis, Kobo-Ausschlussregale und Magic Shelves) im Hintergrund ausgeführt. Der Benutzer sieht zwar das Ergebnis im Dashboard, aber nicht immer die genaue Ursache.

### Ziele
* **Erklärung der Erlaubnis-Quelle:** Das Dashboard soll für jedes Buch im Sync-Bereich erklären, *welche* Quelle (z. B. ein bestimmtes normales Regal, eine Magic-Shelf-Regel oder ein Kobo-Sync-Flag) das Buch für den Kobo freigegeben hat.
* **Sichtbare Begründung des Kobo-Ausschlusses:** Ein durch einen manuellen Blocker (`reader_override = "never"`) ausgeschlossenes Buch soll in den Listen markiert und mit einem Hinweis versehen sein (z. B. „Manuell für den Kobo blockiert“).
* **Nachvollziehbarkeit in Sammlungen:** Wenn eine Sammlung auf dem Kobo weniger Bücher enthält als in der lokalen Bibliothek, soll der Benutzer auf einen Blick sehen, *welche* Bücher dieser Sammlung nicht sync-berechtigt sind und *warum* (z. B. „Keine Kobo-Freigabe für dieses Buch“ oder „Manuell ausgeschlossen“).
* **Arbeitsfilter in der Kobo-Auswahl:** Filter für Universum, Inhaltstyp, Buchart und Lesestatus, um die Menge der angezeigten Bücher in der Kobo-Auswahl schnell zu reduzieren.
* **Proaktive Warnhinweise:**
  - *Schnittstellen-Miskonfiguration:* Hinweis, wenn ein Buch für den Kobo freigegeben ist, aber in keiner kobo-synchronisierten Sammlung liegt.
  - *Regel-Massenwarnung:* Warnung bei der Definition von Kobo-Auswahlregeln, wenn eine Regel oder ein Kriterium (z. B. ein sehr breites Genre wie „Fantasy“) droht, ungewollt riesige Mengen an Büchern auf den Kobo zu synchronisieren.

---

## 2. Einstellungen zusammenführen und beruhigen

Aktuell sind Einstellungen in Calibre-Web-Automated über mehrere Bereiche verstreut (globale Administrations-Einstellungen, Benutzereinstellungen, eReader-Einstellungen). Dies erzeugt visuelles Rauschen und macht die Konfiguration unübersichtlich.

### Ziele
* **Zentraler Einstellungsbereich:** Zusammenführung aller alexandria-relevanten Einstellungen in einer ruhigeren, logisch gruppierten Oberfläche.
* **Strukturierung nach Relevanz:** Häufig genutzte Kobo- und Sammlungs-Einstellungen erhalten prominente Plätze; fortgeschrittene oder selten genutzte Optionen (wie LDAP, Mail-Server etc.) werden standardmäßig eingeklappt oder in eine Untersektion verschoben.
* **Premium-UX/UI:** Das Design der Einstellungsformulare soll modernisiert werden (bessere Abstände, verständliche Hilfstexte, visuelle Gruppierung durch Trennlinien oder Cards statt langer unstrukturierter Listen).

---

## 3. Schöne Sammlungsansicht

Der Klick auf „Sammlungen“ (Shelves / Magic Shelves) führt derzeit auf eine rein funktionale, tabellarische oder listenbasierte Ansicht.

### Ziele
* **Übersichtliche Kachelansicht:** Darstellung von normalen Regalen und automatischen Sammlungen (Magic Shelves) als visuelle Kacheln (Cards), ähnlich einer echten Buchregal-Bibliothek.
* **Status und Bedeutung auf einen Blick:**
  * **Typ-Visualisierung:** Klare Icons oder Badges für den Sammlungstyp (*Normales Regal*, *Automatische Sammlung/Magic Shelf*).
  * **Sync-Status:** Sichtbarkeit der Kobo-Eigenschaften (*Wird auf Kobo synchronisiert* vs. *Display-only*).
  * **Metadaten:** Anzeige der Buchanzahl innerhalb der Kachel.
* **Bedingungs-Vorschau (Magic Shelves):** Direkt im Editor für automatische Sammlungen soll eine Live-Vorschau der Bücher angezeigt werden, die den aktuellen Bedingungen entsprechen, um Fehleinstellungen sofort zu erkennen.
* **Anpassbare Darstellung:** Später sollen Nutzer zentrale Darstellungsparameter der Regalansicht anpassen können, insbesondere Schriftarten, Titel-Schriftart, Titelgröße und Titel-/Akzentfarben für Galerie- und Reader-Modus. Als Inspirationsquelle für lizenzfreie, eReader-optimierte Schriften soll <https://github.com/nicoverbruggen/ebook-fonts> geprüft werden; konkrete Schriften werden vor Übernahme jeweils einzeln auf Lizenz, Attribution und Web-Eignung geprüft.
* **Lesbare Metadaten trotz Kürzung:** Abgeschnittene Titel, Serien- und perspektivisch Universumszeilen sollen beim Hover vollständig lesbar werden, z. B. über native Tooltips oder eine ruhige eigene Tooltip-Komponente.
* **Erweiterte Sortierung:** Zusätzlich zu den bestehenden Sortierungen soll eine Sortierung nach Serie und perspektivisch nach Universum ergänzt werden. Innerhalb einer Serie sollen Bücher nach Serienindex sortiert werden, sodass z. B. Serien alphabetisch gruppiert und darin `Buch 1`, `Buch 2`, `Buch 3` korrekt angeordnet werden.
* **Micro-Animations & Hover-Effekte:** Dezente visuelle Rückmeldungen beim Überfahren der Kacheln, um das Stöbern lebendiger zu machen.
* **Cozy Musikmodus beim Stöbern (Produkt-Spike):** Optionaler, unaufdringlicher Musikplayer für eine positive, gemütliche Bibliotheksstimmung beim Durchstöbern der Bücher. Nutzer sollen später eigene lokale Musikdateien oder kuratierte Playlists einbetten können. Vor einer Umsetzung müssen Speicherort, Datenschutz, Rechte-/Lizenzfragen, Autoplay-Verhalten und ein klarer Aus-Schalter geprüft werden.

---

## 4. Deutsche Sprache konsequent verbessern

Ein zentrales Ziel von Alexandria ist eine ruhige, stimmige deutsche Benutzeroberfläche. Viele Begriffe im Upstream sind direkt oder hölzern übersetzt oder mischen englische Fachbegriffe mit deutschen Formulierungen.

### Ziele
* **Einheitliches Wording:**
  * `Shelf` / `Magic Shelf` $\rightarrow$ „Regal“ / „Automatische Sammlung“ (konsistent im gesamten Interface).
  * `Kobo Sync` $\rightarrow$ „Kobo-Auswahl“ oder „Kobo-Synchronisation“.
* **Reduzierung technischer Begriffe:** Vermeidung von Begriffen wie „Query“, „Boolean“, „Database-Trigger“ oder „Custom Columns“ in normalen Benutzer-Flows. Stattdessen verständliche Formulierungen wie „Bedingung“, „Benutzerdefiniertes Feld“ oder „Filter“.
* **Katalog-Audit:** Überprüfung aller Hinweistexte, Tooltips, Erfolgsmeldungen und Buttons im Bereich Kobo-Sync, Sammlungen, Einstellungen und Buchaktionen.

---

## 5. Zukünftige UX-Idee: Schnelle Anzeige-Auswahl in der Seitenleiste (Produkt-Spike)

*Hinweis: Dies ist eine reine Design-Idee und wird noch nicht implementiert.*

### Konzept
* **Direktzugriff statt Tiefen-Navigation:** An der Stelle in der Seitenleiste, an der sich heute die globale Suche und die Browse-Navigation befinden, soll eine Schnellwahl integriert werden.
* **Verhalten:** Der Benutzer soll direkt über die Seitenleiste umschalten können, welche Bücher in der Hauptansicht angezeigt werden (z. B. Filter wie „Alle Bücher“, „Nur Kobo-Bücher“, „Ungelesene Bücher“).
* **Ziel:** Vermeidung des ständigen Wechsels in die tiefen Einstellungsmenüs, um den aktuellen Bibliotheks-Fokus auf dem Desktop anzupassen.
