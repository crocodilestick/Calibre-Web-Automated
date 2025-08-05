#!/bin/bash
set -e

# 1. Extract messages from Python and Jinja2 templates
pybabel extract -F babel.cfg -o messages.pot . || { echo "pybabel extract failed"; exit 1; }

# 2. Merge new strings into each .po file
for po in cps/translations/*/LC_MESSAGES/messages.po; do
    echo "Updating $po"
    msgmerge --update "$po" messages.pot || { echo "msgmerge failed for $po"; exit 1; }
done

# 3. Compile .po files to .mo files
for po in cps/translations/*/LC_MESSAGES/messages.po; do
    mo="${po%.po}.mo"
    echo "Compiling $po to $mo"
    msgfmt "$po" -o "$mo" || { echo "msgfmt failed for $po"; exit 1; }
done

echo "Translation update complete."