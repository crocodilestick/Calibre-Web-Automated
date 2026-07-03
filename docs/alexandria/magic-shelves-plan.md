# Implementierungsplan: Normale Regale als Magic-Shelf-Regelquelle (Überarbeitet)

> [!NOTE]
> **Status: Erfolgreich umgesetzt.** Dieses Feature sowie die nachgelagerte Kobo-Entkopplung (2-Säulen-Prinzip) und das Kobo-Dashboard sind fertiggestellt. Für den aktuellen Entwicklungsstand und künftige Pläne siehe die [Release-Roadmap](release-roadmap.md).

Dieses Dokument beschreibt die technische Umsetzung zur Einbindung von normalen Regalen (`ub.Shelf`) als Regelquelle in Magic-Shelves (`normal_shelf`).

---


## Technische Spezifikation

### 1. Einschränkung auf Operatoren
- Für das neue Feld `normal_shelf` sind **ausschließlich** die Operatoren `equal` (ist im Regal) und `not_equal` (ist nicht im Regal) zulässig.
- UI und Backend müssen dies explizit erzwingen.

### 2. Backend-Sicherheitsprüfungen (Permissions) & Fehlerbehandlung
Da Regeln manipuliert werden können, muss die Berechtigungsprüfung zwingend im Backend in `build_filter_from_rule` erfolgen:
1. Prüfen, ob das referenzierte Regal dem Benutzer gehört (`current_user.id` oder der an `build_filter_from_rule` übergebene `user_id`-Parameter) oder ob es öffentlich ist (`is_public == 1`).
2. **Sicherheits-Blocker (Fehlerbehandlung):**
   - Falls der Benutzer **keine Berechtigung** hat, die Regal-ID **ungültig** ist (z. B. keine Zahl), die Konvertierung scheitert oder ein **nicht unterstützter Operator** aufgerufen wird, darf die Funktion **niemals** `None` zurückgeben!
   - Ein Rückgabewert von `None` würde in `build_query_from_rules` ignoriert werden, wodurch restliche Regeln (z. B. in einer AND-Gruppe) ungewollt breit evaluieren und unberechtigte Bücher freigeben.
   - **Verhalten bei logischen Verknüpfungen (Semantik):**
     - Bei Fehlern wird eine blockierende SQLAlchemy-Bedingung wie `sqlalchemy.false()` zurückgegeben.
     - **AND-Verknüpfung:** `AND(false(), Restregel)` blockiert die gesamte Gruppe, sodass diese keine Treffer liefert (maximale Sicherheit).
     - **OR-Verknüpfung:** `OR(false(), Restregel)` führt dazu, dass der fehlerhafte/unberechtigte Regelzweig ignoriert wird, während die anderen legitimen OR-Zweige weiterhin ausgewertet werden. Dies verhindert unberechtigte Freigaben, ohne das gesamte Magic Shelf funktionsunfähig zu machen.

3. **Cache-Invalidierungsstrategie**
Um zu verhindern, dass Kobo-Geräte oder das Web-UI veraltete Daten anzeigen (da die Zuweisung in normalen Regalen nicht standardmäßig den Magic-Shelf-Cache invalidiert):
1. **Globale Invalidierung bei Regaländerungen:** Da normale Regale öffentlich sein können (`is_public == 1`) und somit von Magic Shelves anderer Benutzer referenziert werden können, reicht eine nutzerspezifische Cache-Invalidierung nicht aus. Wir führen bei jeder Änderung an einem Regal einen **globalen Cache-Flush** durch:
   ```python
   ub.session.query(ub.MagicShelfCache).delete()
   ```
   Da der Cache nur Performance-Zwecken dient und beim nächsten Web-Aufruf automatisch neu aufgebaut wird, ist dieser globale Flush sicher und performant genug.
   
   > [!NOTE]
   > **Zentraler Invalidator:** 
   > Da Regaländerungen (`BookShelf`-Mutationen) auch über andere Pfade wie Kobo-Collection-Sync (`cps/kobo.py`), OPDS, Editbooks oder die Admin-Oberfläche erfolgen können, implementieren wir eine zentrale Hilfsfunktion `invalidate_magic_shelf_cache()`. Diese wird von allen Stellen aufgerufen, an denen Regalinhalte verändert werden.
   
2. **Cache-Bypass bei Kobo-Sync:** Im Kobo-Synchronisations-Endpunkt in [cps/kobo.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/kobo.py) rufen wir `get_books_for_magic_shelf` bei Kobo-kritischen Pfaden mit `bypass_cache=True` auf, um die absolute Aktualität für den eReader zu garantieren.

---

## Vorgeschlagene Änderungen

### 1. Web-Routen ([cps/web.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/web.py))
In den Routen für das Erstellen und Editieren von Magic-Shelves (`create_magic_shelf` und `edit_magic_shelf` bei GET):
- Abfrage aller Regale, die dem aktuellen Benutzer gehören oder öffentlich sind:
  ```python
  shelves = ub.session.query(ub.Shelf).filter(
      or_(ub.Shelf.user_id == current_user.id, ub.Shelf.is_public == 1)
  ).order_by(ub.Shelf.name).all()
  shelves_map = {s.id: s.name for s in shelves}
  ```
- Übergabe als JSON (`shelves_json=json.dumps(shelves_map)`) an das Template.

### 2. UI-Ebene ([cps/templates/magic_shelf_edit.html](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/templates/magic_shelf_edit.html))
Erweiterung des `fields`-Arrays in der jQuery QueryBuilder Konfiguration:
```javascript
{
    id: 'normal_shelf',
    label: 'Shelf',
    type: 'integer',
    input: 'select',
    values: shelves_json,
    operators: ['equal', 'not_equal'], // Strikte Einschränkung der Operatoren
    description: 'Book is in a specific shelf'
}
```

### 3. Parser-Engine ([cps/magic_shelf.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/magic_shelf.py))
- Eintrag in `FIELD_MAP`: `'normal_shelf': ('ub_shelf', 'shelf')`.
- Erweiterung von `build_filter_from_rule`:
  ```python
  if model == 'ub_shelf' and column_name == 'shelf':
      from sqlalchemy import false
      
      # 1. Sichere Typkonvertierung & Existenzprüfung
      try:
          shelf_id = int(value) if value is not None else None
      except (ValueError, TypeError):
          log.error(f"Invalid shelf ID value: {value}")
          return false()  # Sicher blockieren!
          
      if not shelf_id:
          return false()
          
      target_shelf = ub.session.query(ub.Shelf).get(shelf_id)
      
      # 2. Permission-Check
      if not target_shelf or (target_shelf.user_id != user_id and target_shelf.is_public != 1):
          log.warning(f"Access denied or invalid shelf ID {shelf_id} for user {user_id}")
          return false()  # Sicher blockieren, nicht None zurückgeben!
          
      # 3. Operator-Validierung
      if operator_name not in ['equal', 'not_equal']:
          log.error(f"Unsupported operator '{operator_name}' for normal_shelf")
          return false()  # Sicher blockieren!
          
      # 4. Buch-IDs aus BookShelf ermitteln
      books_in_shelf = ub.session.query(ub.BookShelf.book_id).filter(
          ub.BookShelf.shelf == shelf_id
      ).all()
      book_ids = [b.book_id for b in books_in_shelf]
      
      # 5. Filter erzeugen (korrektes Mapping auf ub.BookShelf.shelf)
      if operator_name == 'equal':
          return db.Books.id.in_(book_ids)
      elif operator_name == 'not_equal':
          return ~db.Books.id.in_(book_ids)
  ```

### 4. Cache-Invalidierung in [cps/shelf.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/cps/shelf.py)
In `add_to_shelf`, `remove_from_shelf`, `delete_shelf` und `edit_shelf` einen globalen Cache-Flush integrieren:
```python
ub.session.query(ub.MagicShelfCache).delete()
```

---

## Test- und Verifikationsplan

### Unit-Tests ([tests/unit/test_magic_shelf_rules.py](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/tests/unit/test_magic_shelf_rules.py))
Wir implementieren folgende isolierte Testfälle im Testbaum:
1. **Regel „Buch ist in Shelf X“:** Erwartet, dass die erzeugte Expression `db.Books.id.in_([book_ids])` entspricht.
2. **Regel „Buch ist nicht in Shelf X“:** Erwartet, dass die Expression `~db.Books.id.in_([book_ids])` entspricht.
3. **Leeres Shelf:** Verifiziert, dass ein leeres Shelf zu `db.Books.id.in_([])` evaluiert (gibt keine Bücher zurück).
4. **Ungültige/Nicht sichtbare Shelf-ID:** Verifiziert, dass unberechtigte Anfragen (fremde private Regale) sicher mit `false()` blockiert werden.
5. **String-Wert als Shelf-ID:** Testet manipuliertes JSON wie `"abc"` und verifiziert, dass die Konvertierung sicher abgefangen wird und zu `false()` führt.
6. **Nicht unterstützte Operatoren:** Verifiziert, dass verbotene Operatoren (wie `contains` oder `greater`) auf `normal_shelf` sicher mit `false()` blockiert werden.
7. **Cache-Invalidierung:** Testet, dass bei Regaländerungen der Cache global geleert wird.
8. **Regression:** Testet, dass Standardregeln (z.B. Tag-Matching) weiterhin vollkommen unberührt bleiben.
