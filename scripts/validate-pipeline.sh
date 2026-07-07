#!/usr/bin/env bash
#
# validate-pipeline.sh — Validiert die Einrichtung der Agenten-Pipeline im Projekt.
#
# Aufruf:
#   scripts/validate-pipeline.sh [projekt_pfad]
#

set -euo pipefail

ROOT="${1:-}"
if [ -z "$ROOT" ]; then
  # Ermittle Root-Pfad relativ zum Skript-Speicherort (zwei Ebenen hoch)
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

echo "=== Pipeline-Validierung für: $ROOT ==="
echo

ERRORS=0
IS_KIT=0
if [ "$(basename "$ROOT")" = "ai-coding-starter-kit" ]; then
  IS_KIT=1
  echo "  (Führe Validierung im Starter-Kit-Modus aus)"
fi

# Helper: print status
status_ok() {
  echo -e "  [\033[0;32mOK\033[0m] $1"
}

status_warn() {
  echo -e "  [\033[0;33mWARN\033[0m] $1"
}

status_err() {
  echo -e "  [\033[0;31mFAIL\033[0m] $1"
  ERRORS=$((ERRORS + 1))
}

# 1. Check project rules and files
echo "1. Dateipflichtprüfungen:"
# Im Kit prüfen wir nur CLAUDE.md und AGENTS.md, da STAND/VERLAUF/Briefing dort nur Templates sind.
declare -a required_files
if [ "$IS_KIT" -eq 1 ]; then
  required_files=(CLAUDE.md AGENTS.md)
else
  required_files=(CLAUDE.md AGENTS.md .agents/AGENTS.md STAND.md VERLAUF.md)
fi

for f in "${required_files[@]}"; do
  if [ -f "$ROOT/$f" ]; then
    status_ok "$f existiert."
  else
    status_err "$f fehlt."
  fi
done

if [ "$IS_KIT" -eq 0 ]; then
  if [ -f "$ROOT/FEATURE_BRIEFING.md" ] || [ -f "$ROOT/docs/alexandria/FEATURE_BRIEFING.md" ]; then
    status_ok "FEATURE_BRIEFING.md existiert."
  else
    status_warn "FEATURE_BRIEFING.md oder docs/alexandria/FEATURE_BRIEFING.md fehlt."
  fi
fi

# 2. Check .gitignore
echo
echo "2. Gitignore-Sicherheitsprüfungen:"
if [ "$IS_KIT" -eq 1 ]; then
  status_ok "Starter-Kit benötigt keine .gitignore-Validierung für Secrets."
else
  if [ -d "$ROOT/.git" ]; then
    for entry in "STAND.md" ".env" ".env.local" ".mcp.json"; do
      if (cd "$ROOT" && git check-ignore -q "$entry" 2>/dev/null); then
        status_ok "'$entry' wird korrekt ignoriert."
      else
        status_err "'$entry' wird NICHT ignoriert!"
      fi
    done
  else
    GI="$ROOT/.gitignore"
    if [ -f "$GI" ]; then
      for entry in "STAND.md" ".env" ".env.local" ".mcp.json"; do
        if grep -q "$entry" "$GI"; then
          status_ok ".gitignore enthält Muster für '$entry'."
        else
          status_err ".gitignore fehlt Eintrag für '$entry'!"
        fi
      done
    else
      status_err ".gitignore fehlt völlig!"
    fi
  fi
fi

# 3. Check Secrets / .env
echo
echo "3. Secrets & Tokens Prüfungen:"
if [ "$IS_KIT" -eq 1 ]; then
  status_ok "Starter-Kit benötigt keine .env Secrets."
else
  ENV_FILE="$ROOT/.env"
  ENV_EX="$ROOT/.env.example"

  if [ -f "$ENV_EX" ]; then
    status_ok ".env.example existiert."
    if [ -f "$ENV_FILE" ]; then
      status_ok ".env existiert."
      # Keys aus .env.example lesen (alles vor = und ohne Kommentare)
      while IFS= read -r line || [ -n "$line" ]; do
        # Überspringe Leerzeilen und Kommentare
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue

        key="${line%%=*}"
        if grep -q "^$key=" "$ENV_FILE"; then
          val="$(grep "^$key=" "$ENV_FILE" | cut -d'=' -f2-)"
          if [ -z "$val" ] || [[ "$val" == *"here"* ]]; then
            status_warn "Key '$key' in .env ist leer oder enthält Platzhalter."
          else
            status_ok "Key '$key' in .env ist konfiguriert."
          fi
        else
          status_err "Key '$key' ist in .env.example deklariert, fehlt aber in .env!"
        fi
      done < "$ENV_EX"
    else
      status_err ".env fehlt! Bitte .env.example nach .env kopieren und befüllen."
    fi
  else
    status_warn ".env.example fehlt."
  fi
fi

# 4. Check rule synchronization (Rule Compilation)
echo
echo "4. Regel-Kompilierung (Regelsynchronität):"

# Wir prüfen immer die lokale AGENTS.md des Projekts bzw. des Starter-Kits.
# Wir verweisen NICHT mehr auf globale Tools-Dateien.
AGENTS_FILE="$ROOT/AGENTS.md"

if [ -f "$AGENTS_FILE" ]; then
  status_ok "Prüfe lokale '$AGENTS_FILE'..."
  # Kompatible Liste für Bash 3
  declare -a check_list
  check_list=(
    "VERDICT|Review-Urteilsformat (VERDICT: APPROVE | REVISE)"
    "ADR-Blöcke|Plan-Ausgabeformat (ADR-Blöcke)"
    "Akzeptanzkriterium|Teststrategie (Akzeptanzkriterium)"
    "Eskalationsregel|Multi-Agent-Eskalationsregel"
  )

  for item in "${check_list[@]}"; do
    kw="${item%%|*}"
    desc="${item#*|}"
    if grep -q "$kw" "$AGENTS_FILE"; then
      status_ok "Regel-Begriff gefunden: $desc"
    else
      status_err "Regel-Begriff FEHLT in $AGENTS_FILE: $desc!"
    fi
  done

  # In schlanken Projekten dürfen keine ungelösten @rules/ Imports übrig bleiben
  if [ "$IS_KIT" -eq 0 ] && [ ! -d "$ROOT/rules" ]; then
    if [ -f "$ROOT/CLAUDE.md" ] && grep -q "^@rules/" "$ROOT/CLAUDE.md"; then
      status_err "CLAUDE.md enthält ungelöste @rules/-Imports!"
    else
      status_ok "CLAUDE.md ist frei von ungelösten @rules/-Imports."
    fi
    if grep -q "^@rules/" "$AGENTS_FILE"; then
      status_err "AGENTS.md enthält ungelöste @rules/-Imports!"
    else
      status_ok "AGENTS.md ist frei von ungelösten @rules/-Imports."
    fi
  fi
else
  status_err "Kompilierte AGENTS.md ($AGENTS_FILE) existiert nicht, Inhalt kann nicht validiert werden."
fi

echo
if [ $ERRORS -eq 0 ]; then
  echo -e "\033[0;32mVERDICT: PIPELINE OK\033[0m"
  exit 0
else
  echo -e "\033[0;31mVERDICT: PIPELINE ERRORS ($ERRORS Fehler)\033[0m"
  exit 1
fi
