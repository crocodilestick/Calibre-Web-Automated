# Audit der Magic-Shelf-Regeln in CWA Alexandria

Dieses Dokument analysiert das bestehende Magic-Shelf-Regelwerk in Calibre-Web-Automated (CWA). Es dient als Grundlage für die Kobo-Entkopplung sowie die Einbindung normaler Regale als Regelquelle.

---

## Fachliches Zielmodell: Die Kobo-Entkopplung

Für Alexandria soll die Steuerung der Kobo-Synchronisation grundlegend überarbeitet werden. Aktuell sind Freigabe und Sammlungsbildung in CWA starr gekoppelt (`kobo_sync=True` auf einem Regal bedeutet: Bücher werden synchronisiert *und* eine gleichnamige Kobo-Sammlung wird erzeugt).

### Das 2-Säulen-Prinzip
Künftig trennen wir die Synchronisation in zwei getrennte Fragen auf:
1. **Sync-Erlaubnis:** Darf ein bestimmtes Buch auf den Kobo? (Berechnung der Kobo-Buchmenge).
2. **Sammlungs-Definition:** In welchen Kobo-Sammlungen soll das Buch auf dem eReader erscheinen?

### Das Zielbild
- **Getrennte Einstellungen:** Jedes normale Regal (`ub.Shelf`) und jedes Magic Shelf (`ub.MagicShelf`) erhält zwei unabhängige Flags:
  - „Für Kobo freigeben“ (Sync-Quelle).
  - „Als Kobo-Sammlung anzeigen“ (Sammlungs-Quelle).
- **Sicherheits-Schranke:** Eine Kobo-Sammlung darf ausschließlich Bücher gruppieren, die bereits über eine der Sync-Quellen freigegeben wurden. Eine Sammlung darf niemals heimlich neue Bücher für den Sync freigeben.
- **Komfort-Aktionen:** Ganze Serien können per Klick gesynct werden.
- **Serien-Ausnahme:** Serien erzeugen standardmäßig keine Kobo-Sammlungen, da der Kobo eReader eine native Serien-Ansicht besitzt.
- **Universum-Sammlungen:** Spezielle Sammlungen (wie Universen oder komplexe Leseprojekte) können gezielt als Kobo-Sammlungen modelliert werden, da der Kobo diese Struktur nicht nativ kennt.
- **Zentrale Kobo-Übersichtsseite (Dashboard):** Eine Diagnoseansicht im UI zeigt dem Benutzer:
  - Welche Bücher landen auf dem Kobo und warum (durch welche Quelle)?
  - In welchen Sammlungen tauchen sie auf?
  - Gibt es breite, riskante oder überlaufende Regeln?

---

## Befunde & Strukturanalyse

### 1. Unterstützte Felder und Operatoren

Die Logik der Regeln befindet sich im Backend in [cps/magic_shelf.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/magic_shelf.py).

#### Felder (`FIELD_MAP`):
- **Calibre-Metadaten:** `title`, `author` (Name), `tag` (Name), `series` (Name), `publisher` (Name), `rating`, `language` (Code), `pubdate`, `timestamp` (Erstellungsdatum), `series_index`, `comments` (Beschreibung).
- **Booleans:** `has_cover` (0 oder 1).
- **Sonderfelder:**
  - `read_status`: Verweist auf ein konfigurierbares Custom-Column oder fällt auf den internen Benutzer-Lesestatus in `ub.ReadBook` zurück.
  - `hardcover_id`: Prüft das Vorhandensein bestimmter Hardcover-Identifier-Typen in der `Identifiers`-Tabelle.

#### Operatoren (`OPERATOR_MAP`):
- **Vergleiche:** `equal`, `not_equal`, `less`, `less_or_equal`, `greater`, `greater_or_equal`, `between`, `not_between`.
- **String-Suchen:** `contains`, `not_contains`, `begins_with`/`starts_with`, `not_begins_with`, `ends_with`, `not_ends_with`.
- **Null-Checks:** `is_empty`/`is_null`, `is_not_empty`/`is_not_null`.
- **Listen:** `in`, `not_in`.

### 2. Backend-Regelgenerierung
- **Parser-Funktion:** `build_query_from_rules(rules_json, user_id=None)` parst die JSON-Regelstruktur rekursiv (unterstützt logische Gruppen über `AND` und `OR`).
- **Filter-Ersteller:** `build_filter_from_rule(rule, user_id=None)` erzeugt die SQLAlchemy-Bedingungen. Sie ordnet Felder über `FIELD_MAP` zu und wendet die Lambdas aus `OPERATOR_MAP` an.
- **Query & Cache:** In `get_books_for_magic_shelf` wird der SQLAlchemy-Filter auf die Calibre-Datenbank angewendet. Um Performance-Probleme zu vermeiden, werden die resultierenden Buch-IDs in `ub.MagicShelfCache` mit einer TTL von 30 Minuten gecached.

### 3. UI-Definition
- **Client-Framework:** Das Frontend nutzt die Bibliothek **jQuery QueryBuilder** in [cps/templates/magic_shelf_edit.html](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/templates/magic_shelf_edit.html).
- **Konfiguration:** Das JavaScript definiert ein hartcodiertes `fields`-Array (Zeilen 521–618), das an den QueryBuilder übergeben wird.

---

## Fachliche Risikoanalyse (Kobo-Sync)

### 4. Riskante Regeln für Kobo-Sync (Breite Freigabe)
Da Kobo beim Synchronisieren Sammlungen komplett herunterlädt und breite Freigaben das Gerät überlasten können, sind folgende Konfigurationen riskant:
- **String-Operatoren mit Wildcards:** `title contains "a"` oder `author contains "e"` matchen fast die gesamte Bibliothek.
- **Negationen (`not_equal`, `not_contains`):** `language not_equal "fr"` gibt sämtliche anderssprachigen Bücher frei. `tag not_contains "NoSync"` gibt auch alle Bücher ohne jegliche Tags frei.
- **Leere Datumsbereiche:** `timestamp greater "2000-01-01"` gibt alle modernen E-Books frei.

### 5. Der 1000-Bücher-Deckel
Der Kobo eReader fordert in [cps/kobo.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/kobo.py#L382) Magic-Shelf-Sammlungen mit einer festen `page_size=1000` an:
```python
books, _ = magic_shelf.get_books_for_magic_shelf(shelf.id, page=1, page_size=1000)
```
- **Konsequenz:** Große Magic-Shelf-Sammlungen (>1000 Bücher) werden stillschweigend abgeschnitten.
- **Fehlerpotenzial:** Der Benutzer wundert sich, warum Bücher auf dem Kobo fehlen. Die spätere Kobo-Übersicht muss daher vor solchen überlaufenden Regeln/Sammlungen explizit warnen.

---

## Konzeptionelle Fragen für die Regelerweiterung

### 6. Integration normaler Regale (`ub.Shelf`) als Regelquelle
- **Name des Feldes:** Wir benennen das Feld **`normal_shelf`**, um es sprachlich präzise von Magic Shelves zu trennen.
- **Operatorenbeschränkung:** Für `normal_shelf` sind **ausschließlich** die Operatoren `equal` (Buch ist im Regal) und `not_equal` (Buch ist nicht im Regal) zulässig. String-, Datums- oder Zahlenoperatoren werden im UI und Backend blockiert.
- **Datenbankübergreifende Abfragen (SQL-Joins):**
  Obwohl die Calibre-Bibliothek (`metadata.db`) und die Benutzer-Konfiguration (`ub.db`) in CWA separate SQLite-Dateien sind, nutzt CWA an anderen Stellen bereits Cross-Model-Joins (z. B. in `cps/search.py` via SQLAlchemy-Joins).
  - *Designentscheidung:* Für die Magic-Shelf-Regeln wählen wir jedoch bewusst die **ID-Listen-Auflösung im Python-Backend** als die robustere und Upstream-nähere Variante. Dies entkoppelt die SQL-Query-Generierung und verhindert, dass wir die komplexen Filter-Generatoren von CWA mit datenbankübergreifenden Tabellen-Joins überladen.

### 7. Backend-Berechtigungen (Permissions)
Da die Magic-Shelf-Regeln als JSON in der Datenbank gespeichert und prinzipiell manipuliert werden können, darf das Backend sich nicht auf die UI-Filterung verlassen.
- **Sicherheitsprüfung:** Beim Auflösen einer `normal_shelf`-Regel in `build_filter_from_rule` muss das Backend prüfen:
  1. Gehört das referenzierte normale Regal dem Benutzer (`current_user.id` bzw. dem Ersteller des Magic Shelves)?
  2. Oder ist das normale Regal öffentlich (`is_public == 1`)?
- **Verhalten bei fehlenden Rechten:** Wenn der Zugriff verweigert wird, wird die Regel als leere Bedingung oder `False`-Ausdruck ausgewertet, sodass keine Bücher unberechtigt freigegeben werden. Die Logik orientiert sich an `check_shelf_view_permissions` in `cps/shelf.py`.

### 8. Cache-Invalidierungsstrategie
Da Ergebnisse von Magic Shelves gecached werden (`ub.MagicShelfCache`), veraltet dieser Cache, sobald sich der Inhalt des referenzierten normalen Regals (`ub.BookShelf`) ändert.
- **Kombinierte Strategie für Alexandria:**
  - *Option A (Echtzeit-Invalidierung):* Bei Änderungen an normalen Regalen (Hinzufügen/Entfernen von Büchern in `cps/shelf.py` bei `add_to_shelf` und `remove_from_shelf`) invalidieren wir die betroffenen Caches des Benutzers.
  - *Option B (Selektiver Cache-Bypass):* Wenn ein Magic Shelf Regeln enthält, die auf `normal_shelf` verweisen, wird der Cache bei kritischen Aufrufen (wie dem Kobo-Sync) umgangen (`bypass_cache=True`), um absolute Konsistenz zu garantieren.

---

## Scope & Fahrplan

Die Einführung von **`normal_shelf` als Regelquelle** ist ein rein vorbereitender Baustein. Er schafft die technische Möglichkeit, Regale logisch zu verknüpfen.

Die eigentliche **Kobo-Entkopplung** und das **Dashboard** folgen in separaten Schritten auf Basis dieses Bausteins.
