#!/usr/bin/env bash
# Add DB Profile to your application menu, with its icon.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

# The icon is drawn by the app itself, so render it with the app's Python (set up the venv like run.sh).
if [ ! -x "$DIR/.venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$DIR/.venv"
    "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi
(cd "$DIR" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m dbprofile.app_icon "$DATA/icons/hicolor" >/dev/null)
touch "$DATA/icons/hicolor"  # tell desktops the icon theme changed
if command -v gtk-update-icon-cache >/dev/null && [ -f "$DATA/icons/hicolor/index.theme" ]; then
    gtk-update-icon-cache -q "$DATA/icons/hicolor" || true
fi

mkdir -p "$DATA/applications"
cat > "$DATA/applications/dbprofile.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=DB Profile
Comment=Simple MySQL client
Exec=$DIR/run.sh
Icon=dbprofile
StartupWMClass=DB Profile
Terminal=false
Categories=Development;Database;
DESKTOP
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" || true
echo "Installed $DATA/applications/dbprofile.desktop"
echo "Installed icon $DATA/icons/hicolor/<size>/apps/dbprofile.png"
