#!/usr/bin/env bash
#
# build-agents-md.sh — erzeugt AGENTS.md aus CLAUDE.md.
#
# CLAUDE.md ist die kanonische Quelle. Sie bindet die Regel-Module aus rules/
# per "@rules/datei.md" ein. Claude Code löst diese @-Imports nativ auf; andere
# Tools tun das nicht. Dieses Skript expandiert die @-Imports in einen Volltext
# und schreibt ihn an ZWEI Orte, damit jedes Tool dieselben Regeln sieht — ohne
# Doppelpflege:
#   - AGENTS.md          im Root  -> für Codex u. a.
#   - .agents/AGENTS.md            -> für Gemini / Antigravity
# (Gemini liest laut eigener Angabe NUR .agents/AGENTS.md und ignoriert die
#  Root-AGENTS.md; Codex liest die Root-Datei. Beide Artefakte sind identisch,
#  generiert und read-only. Quelle: Selbstauskunft Gemini/Antigravity, Stand
#  prüfen, falls sich deren Konvention ändert.)
#
# Aufruf:
#   scripts/build-agents-md.sh            -> baut im Kit-Root (Verzeichnis über diesem Skript)
#   scripts/build-agents-md.sh /ziel/pfad -> baut CLAUDE.md -> AGENTS.md in /ziel/pfad

set -euo pipefail

# Ziel-Root: explizites Argument, sonst Verzeichnis über diesem Skript.
if [ "${1:-}" != "" ]; then
  ROOT="$(cd "$1" && pwd)"
else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
SRC="$ROOT/CLAUDE.md"
OUT="$ROOT/AGENTS.md"

if [ ! -f "$SRC" ]; then
  echo "Fehler: $SRC nicht gefunden." >&2
  exit 1
fi

# Skill-/MCP-Übersicht (rules/99-...) aktualisieren — nur im Kit-Kontext, also
# wenn eine Skill-Quelle vorhanden ist (abgespeckte Projekte haben kein skills-src).
INDEX_GEN="$(dirname "${BASH_SOURCE[0]}")/build-index.sh"
if [ -f "$INDEX_GEN" ] && [ -d "$ROOT/skills-src" ]; then
  bash "$INDEX_GEN" "$ROOT" >/dev/null 2>&1 || \
    echo "Hinweis: Übersicht (build-index) übersprungen." >&2
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
  echo "<!-- AUTOMATISCH GENERIERT aus CLAUDE.md durch scripts/build-agents-md.sh."
  if [ -d "$ROOT/rules" ]; then
    echo "     NICHT direkt bearbeiten — Änderungen in rules/*.md vornehmen und neu bauen. -->"
  else
    # Abgespecktes Projekt: keine lokalen rules/ — nur der Projektblock ist hier zu pflegen.
    echo "     NICHT direkt bearbeiten — Projektblock in CLAUDE.md ändern und neu bauen."
    echo "     Generische Hausregeln liegen global (im Kit gepflegt: rules/, dann build-global.sh). -->"
  fi
  echo
} > "$TMP"

# CLAUDE.md zeilenweise durchgehen.
# - Reine @-Import-Zeilen -> durch Dateiinhalt ersetzen.
# - Block zwischen <!-- CLAUDE-ONLY-START/END --> -> verwerfen und durch eine
#   AGENTS-eigene Einleitung ersetzen (sonst behauptete AGENTS.md fälschlich,
#   selbst @-Imports einzubinden).
# - Titelzeile "# CLAUDE.md ..." -> "# AGENTS.md ...".
# - Alles andere unverändert übernehmen.
in_claude_only=0
while IFS= read -r line || [ -n "$line" ]; do
  if [[ "$line" == *"CLAUDE-ONLY-START"* ]]; then
    in_claude_only=1
    {
      echo "Diese Datei ist **generiert** aus \`CLAUDE.md\` und \`rules/\` durch"
      echo "\`scripts/build-agents-md.sh\` und enthält den Volltext aller Regeln für"
      echo "Tools, die \`@\`-Imports nicht auflösen (Codex u. a.)."
      echo
      echo "> Nicht direkt bearbeiten. Regeln in \`rules/*.md\` ändern und neu bauen."
    } >> "$TMP"
    continue
  fi
  if [[ "$line" == *"CLAUDE-ONLY-END"* ]]; then
    in_claude_only=0
    continue
  fi
  if [ "$in_claude_only" -eq 1 ]; then
    continue
  fi

  if [[ "$line" =~ ^@(.+\.md)[[:space:]]*$ ]]; then
    importpath="${BASH_REMATCH[1]}"
    target="$ROOT/$importpath"
    if [ -f "$target" ]; then
      cat "$target" >> "$TMP"
      echo >> "$TMP"
    else
      echo "Warnung: Import-Ziel nicht gefunden: $importpath" >&2
      echo "$line" >> "$TMP"
    fi
  else
    # Titelzeile anpassen: "# CLAUDE.md ..." -> "# AGENTS.md ..."
    # (Muster ohne führendes "#", da bash "/#" als Anker-an-Anfang deutet.)
    if [[ "$line" == "# CLAUDE.md"* ]]; then
      echo "# AGENTS.md${line#\# CLAUDE.md}" >> "$TMP"
    else
      echo "$line" >> "$TMP"
    fi
  fi
done < "$SRC"

mv "$TMP" "$OUT"
trap - EXIT
echo "AGENTS.md neu erzeugt: $OUT"

# Zweite Ausgabe für Gemini/Antigravity: derselbe Volltext unter .agents/AGENTS.md.
AGENTS_DIR="$ROOT/.agents"
mkdir -p "$AGENTS_DIR"
cp "$OUT" "$AGENTS_DIR/AGENTS.md"
echo "Außerdem geschrieben: $AGENTS_DIR/AGENTS.md (für Gemini/Antigravity)"

# Größen-Wächter: AGENTS.md schlank halten. Manche Tools begrenzen die Größe der
# Projekt-Doku (z. B. Codex: project_doc_max_bytes, Default laut Doku 32 KiB —
# Stand bitte gelegentlich prüfen). Schwelle überschreibbar via AGENTS_MAX_BYTES.
MAX_BYTES="${AGENTS_MAX_BYTES:-28672}"   # 28 KiB Vorwarnung vor dem 32-KiB-Limit
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "Größe: ${BYTES} Bytes (Warnschwelle ${MAX_BYTES})."
if [ "$BYTES" -gt "$MAX_BYTES" ]; then
  echo "Warnung: AGENTS.md nähert sich dem Tool-Limit für Projekt-Doku" >&2
  echo "         (z. B. Codex project_doc_max_bytes ~32 KiB). Regeln kürzen oder" >&2
  echo "         komplexe Abläufe in Skills/separate Docs auslagern." >&2
fi
