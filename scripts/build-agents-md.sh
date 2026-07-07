#!/usr/bin/env bash
#
# build-agents-md.sh — erzeugt AGENTS.md aus CLAUDE.md.
#
# CLAUDE.md ist die kanonische Quelle.
# - Wenn ein lokales rules/ Ordner existiert (Kit-Modus):
#   Wir lösen @rules/... Imports in CLAUDE.md auf.
# - Wenn KEIN lokaler rules/ Ordner existiert (abgespecktes Projekt):
#   CLAUDE.md enthält keine @rules-Imports (sie bleibt projektspezifisch).
#   scripts/build-agents-md.sh holt die globalen Hausregeln aus der globalen
#   Installation (~/.gemini/config/AGENTS.md) und bettet sie automatisch ein.
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

# Bestimme, ob wir im Kit-Modus sind
HAS_LOCAL_RULES=0
if [ -d "$ROOT/rules" ]; then
  HAS_LOCAL_RULES=1
fi

# Skill-/MCP-Übersicht (rules/99-...) aktualisieren — nur im Kit-Kontext
INDEX_GEN="$(dirname "${BASH_SOURCE[0]}")/build-index.sh"
if [ -f "$INDEX_GEN" ] && [ -d "$ROOT/skills-src" ]; then
  bash "$INDEX_GEN" "$ROOT" >/dev/null 2>&1 || \
    echo "Hinweis: Übersicht (build-index) übersprungen." >&2
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
  echo "<!-- AUTOMATISCH GENERIERT aus CLAUDE.md durch scripts/build-agents-md.sh."
  if [ "$HAS_LOCAL_RULES" -eq 1 ]; then
    echo "     NICHT direkt bearbeiten — Änderungen in rules/*.md vornehmen und neu bauen. -->"
  else
    echo "     NICHT direkt bearbeiten — Projektblock in CLAUDE.md ändern und neu bauen."
    echo "     Generische Hausregeln liegen global (im Kit gepflegt: rules/, dann build-global.sh). -->"
  fi
  echo
} > "$TMP"

# Wenn abgespecktes Projekt: Hole die globalen Regeln aus der globalen Installation
GLOBAL_RULES_BLOCK=""
if [ "$HAS_LOCAL_RULES" -eq 0 ]; then
  # Finde globale Regeln
  for f in "$HOME/.gemini/config/AGENTS.md" "$HOME/.claude/CLAUDE.md" "$HOME/.codex/AGENTS.md"; do
    if [ -f "$f" ]; then
      # Extrahiere den Block zwischen den Markern
      extracted="$(awk '/<!-- AI-CODING-KIT:START/,/<!-- AI-CODING-KIT:END/' "$f" || true)"
      # Validierung: Prüfe, ob sowohl START- als auch END-Marker vorhanden sind
      if [[ "$extracted" == *"AI-CODING-KIT:START"* ]] && [[ "$extracted" == *"AI-CODING-KIT:END"* ]]; then
        GLOBAL_RULES_BLOCK="$extracted"
        break
      fi
    fi
  done

  if [ -z "$GLOBAL_RULES_BLOCK" ]; then
    echo "Fehler: Globale Hausregeln (AI-Coding-Kit Block) konnten nicht aus globalen Dateien extrahiert werden." >&2
    echo "        Stelle sicher, dass scripts/build-global.sh im Kit-Verzeichnis ausgeführt wurde." >&2
    exit 1
  fi
fi

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

  # Injektion der globalen Hausregeln direkt vor ## Projektspezifisch
  if [ "$HAS_LOCAL_RULES" -eq 0 ] && [ -n "$GLOBAL_RULES_BLOCK" ] && [[ "$line" == "## Projektspezifisch"* ]]; then
    echo "$GLOBAL_RULES_BLOCK" >> "$TMP"
    echo >> "$TMP"
    echo "---" >> "$TMP"
    echo >> "$TMP"
  fi

  if [[ "$line" =~ ^@ ]]; then
    if [ "$HAS_LOCAL_RULES" -eq 0 ]; then
      echo "Fehler: @-Imports sind in schlanken Projekten nicht erlaubt: $line" >&2
      exit 1
    fi
    importpath="${line#@}"
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
    if [[ "$line" == "# CLAUDE.md"* ]]; then
      echo "# AGENTS.md${line#\# CLAUDE.md}" >> "$TMP"
    else
      echo "$line" >> "$TMP"
    fi
  fi
done < "$SRC"

mv "$TMP" "$OUT"
trap - EXIT
chmod 644 "$OUT"
echo "AGENTS.md neu erzeugt: $OUT"

# Zweite Ausgabe für Gemini/Antigravity: derselbe Volltext unter .agents/AGENTS.md.
AGENTS_DIR="$ROOT/.agents"
mkdir -p "$AGENTS_DIR"
cp "$OUT" "$AGENTS_DIR/AGENTS.md"
chmod 644 "$AGENTS_DIR/AGENTS.md"
echo "Außerdem geschrieben: $AGENTS_DIR/AGENTS.md (für Gemini/Antigravity)"

# Größen-Wächter am Ende
MAX_BYTES="${AGENTS_MAX_BYTES:-28672}"   # 28 KiB Vorwarnung vor dem 32-KiB-Limit
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "Größe: ${BYTES} Bytes (Warnschwelle ${MAX_BYTES})."
if [ "$BYTES" -gt "$MAX_BYTES" ]; then
  echo "Warnung: AGENTS.md nähert sich dem Tool-Limit für Projekt-Doku" >&2
  echo "         (z. B. Codex project_doc_max_bytes ~32 KiB). Regeln kürzen oder" >&2
  echo "         komplexe Abläufe in Skills/separate Docs auslagern." >&2
fi
