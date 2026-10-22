#!/usr/bin/env bash
# Remove DB Profile from your application menu (your connections and saved queries are kept).
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -f "$DATA/applications/dbprofile.desktop"
rm -f "$DATA"/icons/hicolor/*/apps/dbprofile.png
touch "$DATA/icons/hicolor" 2>/dev/null
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" || true
echo "Removed DB Profile from the application menu"
