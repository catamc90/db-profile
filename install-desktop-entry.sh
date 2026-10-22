#!/usr/bin/env bash
# Add DB Profile to your application menu.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/dbprofile.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=DB Profile
Comment=Simple MySQL client
Exec=$DIR/run.sh
Icon=network-server
Terminal=false
Categories=Development;Database;
DESKTOP
echo "Installed ~/.local/share/applications/dbprofile.desktop"
