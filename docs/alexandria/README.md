# CWA Alexandria

CWA Alexandria ist Alex' persoenlicher Arbeitsbereich fuer einen schrittweisen Fork von Calibre-Web-Automated. Ziel ist keine komplette Neuentwicklung, sondern ein ruhigerer, deutschsprachiger und Kobo-zentrierter Fork, der moeglichst lange nah am Upstream bleibt.

## Arbeitsname

- Produktname: Alexandria
- Repository-Name: `cwa-alexandria`
- Alternative: `cw-alexandria`

Stand 2026-07-02: Der GitHub-Fork wurde als `salutaris91/cwa-alexandria` angelegt. Der reine Name `Alexandria` bleibt Produktname, waere als GitHub-Repository-Name aber zu unscharf.

## Zielrichtung

- Ausgewaehlte Buecher kontrolliert auf den Kobo synchronisieren.
- Kobo-Sammlungen sollen sinnvoll sortieren, aber nicht die ganze Bibliothek aus Versehen freigeben.
- Serien nicht als eigene Sammlungen modellieren, weil Kobo Serien ohnehin separat darstellen kann.
- Universen, Leseprojekte und Sonderkategorien sollen als Sammlungen nutzbar sein.
- Magic Shelves sollen langfristig Regeln fuer normale Regale und Calibre-Custom-Columns bekommen.
- Die Oberflaeche soll deutscher, ruhiger und weniger ueberladen werden.

## Dokumente

- [Vision](vision.md)
- [Kobo-Workflow](kobo-workflow.md)
- [Fork-Audit](fork-audit.md)
- [UI-Ideen](ui-ideen.md)
- [Kobo-Sync Runbook](kobo-setup-runbook.md)

## Naechster Schritt

Der initiale lesende Code-Audit ist abgeschlossen und die Strukturierung als Fork-root (CWA-Code direkt im Hauptverzeichnis) ist umgesetzt. Der naechste technische Schritt ist der kleine `sync_shelves()`-Bugfix mit gezieltem Test im CWA-Testbaum.
