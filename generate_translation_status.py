import polib
import glob

status_lines = []
status_lines.append("| Language | Total Strings | Untranslated | Completion |")
status_lines.append("|---|---|---|---|")
for po_path in sorted(glob.glob("cps/translations/*/LC_MESSAGES/messages.po")):
    lang = po_path.split("/")[2]
    po = polib.pofile(po_path)
    total = len([e for e in po if not e.obsolete])
    untranslated = sum(1 for entry in po if not entry.msgstr.strip() and not entry.obsolete)
    percent = 100 * (total - untranslated) // total if total else 0
    status_lines.append(f"| {lang} | {total} | {untranslated} | {percent}% |")

# Write to the wiki file (replace the table section)
import re
wiki_path = "cwa-wiki/Contributing-Translations.md"
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
