#!/bin/bash
# build_app.sh — builds DMX Desk.app
# Run from the QLVDesk directory: bash build_app.sh

set -e
cd "$(dirname "$0")"

echo "=== DMX Desk App Builder ==="
echo ""

# 1. Check py2app
if ! python3 -c "import py2app" 2>/dev/null; then
    echo "Installing py2app..."
    pip3 install py2app
else
    echo "✓ py2app found"
fi

# 2. Generate icon if not present
if [ ! -f "icon.icns" ]; then
    echo "Generating icon..."
    bash make_icon.sh
else
    echo "✓ icon.icns found"
fi

# 3. Clean previous build
echo "Cleaning previous build..."
rm -rf build dist

# 4. Build
echo "Building app bundle..."
python3 setup.py py2app 2>&1

# 5. Copy show files into app Resources so it finds them on first launch
APP="dist/DMX Desk.app/Contents/Resources"
echo "Copying show files..."
[ -f patch.json ]        && cp patch.json        "$APP/"
[ -f patch_scenes.json ] && cp patch_scenes.json "$APP/"
[ -f ofl_fixtures.json ] && cp ofl_fixtures.json "$APP/"
# desk_prefs.json is NOT copied — it will be created fresh on first launch

echo ""
echo "=== Build complete ==="
echo ""
echo "App is at: dist/DMX Desk.app"
echo ""
echo "To run:    open 'dist/DMX Desk.app'"
echo "To share:  zip -r 'DMX Desk.zip' 'dist/DMX Desk.app'"
echo ""
