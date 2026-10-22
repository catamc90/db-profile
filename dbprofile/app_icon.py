"""Write DB Profile's icon as PNG files into an icon theme folder (used by install-desktop-entry.sh).

    python -m dbprofile.app_icon ~/.local/share/icons/hicolor
"""
import os
import sys

from PyQt6.QtGui import QGuiApplication

from . import icons

SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
NAME = "dbprofile"


def write_theme_icons(theme_dir: str) -> list[str]:
    paths = []
    for size in SIZES:
        folder = os.path.join(theme_dir, f"{size}x{size}", "apps")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{NAME}.png")
        icons.save_png(icons.app, path, size)
        paths.append(path)
    return paths


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window is shown
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - QPixmap needs an application
    for path in write_theme_icons(os.path.expanduser(sys.argv[1])):
        print(path)


if __name__ == "__main__":
    main()
