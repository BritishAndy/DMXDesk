#!/bin/bash
# build_monitor.sh — builds DMX Monitor.app
# Run from the QLVDesk directory: bash build_monitor.sh

set -e
cd "$(dirname "$0")"

echo "=== DMX Monitor App Builder ==="
echo ""

# 1. Check py2app
if ! python3 -c "import py2app" 2>/dev/null; then
    echo "Installing py2app..."
    pip3 install py2app
else
    echo "✓ py2app found"
fi

# 2. Clean previous monitor build
echo "Cleaning previous build..."
rm -rf build dist_monitor

# 3. Create a temporary setup file for monitor_gui
cat > setup_monitor.py << 'SETUP'
from setuptools import setup

APP = ['monitor_gui.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon_monitor.icns' if __import__('os').path.exists('icon_monitor.icns') else None,
    'plist': {
        'CFBundleName':        'DMX Monitor',
        'CFBundleDisplayName': 'DMX Monitor',
        'CFBundleIdentifier':  'com.dmxdesk.monitor',
        'CFBundleVersion':     '1.0.0',
        'CFBundleShortVersionString': '1.0',
        'LSMinimumSystemVersion': '10.14',
        'NSHighResolutionCapable': True,
    },
    'packages': [],
    'excludes': ['matplotlib', 'numpy', 'scipy', 'PIL'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
SETUP

# 4. Build
echo "Building app bundle..."
python3 setup_monitor.py py2app --dist-dir dist_monitor 2>&1

# 5. Copy resources into app bundle
APP="dist_monitor/DMX Monitor.app/Contents/Resources"
echo "Copying resources..."
[ -f patch.json ]   && cp patch.json "$APP/"
[ -d fixtures ]     && cp -r fixtures "$APP/"

# 6. Clean up temp setup file
rm -f setup_monitor.py

echo ""
echo "=== Build complete ==="
echo ""
echo "App is at: dist_monitor/DMX Monitor.app"
echo ""
echo "To run:    open 'dist_monitor/DMX Monitor.app'"
echo "To share:  zip -r 'DMX Monitor.zip' 'dist_monitor/DMX Monitor.app'"
echo ""
