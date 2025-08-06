import polib
import glob

# Mapping of language codes to full language names
LANGUAGE_NAMES = {
    "cs": "Czech",
    "de": "German",
    "el": "Greek",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "gl": "Galician",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "km": "Khmer",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pt_BR": "Portuguese (Brazil)",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh_Hans_CN": "Chinese (Simplified, China)",
    "zh_Hant_TW": "Chinese (Traditional, Taiwan)",
}

status_lines = []
status_lines.append("| Language | Total Strings | Untranslated | Completion |")
status_lines.append("|---|---|---|---|")
for po_path in sorted(glob.glob("cps/translations/*/LC_MESSAGES/messages.po")):
    lang = po_path.split("/")[2]
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    po = polib.pofile(po_path)
    total = len([e for e in po if not e.obsolete])
    untranslated = sum(1 for entry in po if not entry.msgstr.strip() and not entry.obsolete)
    percent = 100 * (total - untranslated) // total if total else 0
    status_lines.append(f"| {f"{lang_name} ([{lang}](https://github.com/crocodilestick/Calibre-Web-Automated/tree/main/cps/translations/{lang}/LC_MESSAGES))"} | {total} | {untranslated} | {percent}% |")

# Write to the wiki file (replace the table section)

import re
import sys
wiki_path = sys.argv[1] if len(sys.argv) > 1 else "wiki-tmp/Contributing-Translations.md"
with open(wiki_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the table between special markers, or insert if not present
start_marker = "<!-- TRANSLATION_STATUS_START -->"
end_marker = "<!-- TRANSLATION_STATUS_END -->"
table_md = start_marker + "\n" + "\n".join(status_lines) + "\n" + end_marker

if start_marker in content and end_marker in content:
    content = re.sub(f"{start_marker}.*?{end_marker}", table_md, content, flags=re.DOTALL)
else:
    # Insert after the first heading
    parts = content.split("\n", 2)
    if len(parts) > 2:
        content = parts[0] + "\n" + parts[1] + "\n" + table_md + "\n" + parts[2]
    else:
        content = content + "\n" + table_md

with open(wiki_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Translation status table updated in wiki.")
