# Vision

Alexandria soll ein persoenlicher, Kobo-zentrierter Fork von Calibre-Web-Automated werden. Der wichtigste Gedanke: CWA bleibt die Basis, Alexandria reduziert Reibung fuer Alex' Bibliothek.

## Warum Fork statt Neubau

Ein Neubau waere technisch reizvoll, wuerde aber sehr viel bereits geloeste Arbeit neu erfinden: Calibre-Datenbankzugriff, Import-Logik, Metadaten, OPDS/Kobo-Sync, Auth, Docker-Betrieb und Hintergrundjobs. Ein Fork ist der bessere Start, solange wir die Aenderungen klein halten und gut dokumentieren.

## Leitplanken

- Upstream zuerst verstehen, dann aendern.
- Kleine, reviewbare Schritte statt grosser Umbau.
- Bestehende Calibre-Daten bleiben kompatibel.
- Kobo-Auswahl darf nie versehentlich die ganze Bibliothek freigeben.
- Deutsche Begriffe sollen Verhalten erklaeren, nicht nur Woerter uebersetzen.
- Erweiterte Optionen bleiben erreichbar, aber nicht im Weg.

## Nicht-Ziele fuer den Anfang

- Kein kompletter Rewrite.
- Keine eigene Calibre-Datenbank.
- Keine neue Reader-Sync-Engine, solange CWA/Kobo-Sync erweiterbar bleibt.
- Keine Serien-Sammlungen als Standard, weil Kobo Serien bereits separat darstellt.

## Grobe Phasen

1. Projektstart und Fork-Audit.
2. Ist-Workflow fuer Kobo-Sync stabil dokumentieren.
3. Erste Codeaenderung: bessere Auswahlregel fuer Kobo/Magic Shelves.
4. Deutsche UX-Begriffe und reduzierte Kobo-Ansicht.
5. UI schrittweise aufraeumen, ohne Upstream-Merges unnoetig schwer zu machen.

## Namensentscheidung

`Alexandria` bleibt der Produktname. Als Repository-Name ist `cwa-alexandria` aktuell die beste Wahl, weil der Name eindeutig auf Calibre-Web-Automated verweist und in der oeffentlichen GitHub-Suche am 2026-07-01 keinen Treffer hatte.
