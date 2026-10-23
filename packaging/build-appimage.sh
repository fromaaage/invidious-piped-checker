#!/usr/bin/env bash
# Builds dist/Invidious_Piped_Checker-<version>-x86_64.AppImage
# Usage: packaging/build-appimage.sh [version]
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:-dev}"
BUILD="$PWD/build/appimage"
rm -rf "$BUILD" dist && mkdir -p "$BUILD" dist

python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --upgrade pip
"$BUILD/venv/bin/pip" install -q PySide6-Essentials requests pyinstaller

"$BUILD/venv/bin/pyinstaller" --noconfirm --clean --onedir --windowed \
  --name invidious-piped-checker \
  --distpath "$BUILD/pyi" --workpath "$BUILD/work" --specpath "$BUILD" \
  --add-data "$PWD/Main.qml:." \
  --exclude-module tkinter \
  app.py

APPDIR="$BUILD/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/applications"
cp -r "$BUILD/pyi/invidious-piped-checker/." "$APPDIR/usr/bin/"
cp packaging/icon.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/invidious-piped-checker.svg"
cp packaging/icon.svg "$APPDIR/invidious-piped-checker.svg"
cp packaging/invidious-piped-checker.desktop "$APPDIR/"
cp packaging/invidious-piped-checker.desktop "$APPDIR/usr/share/applications/"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/invidious-piped-checker" "$@"
RUN
chmod +x "$APPDIR/AppRun"

TOOL="$BUILD/appimagetool"
curl -sSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$TOOL"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$PWD/dist/Invidious_Piped_Checker-${VERSION}-x86_64.AppImage"
ls -lh dist/
