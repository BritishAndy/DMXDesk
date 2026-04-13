#!/bin/bash
# make_monitor_icon.sh — converts monitor_icon_1024.png to icon_monitor.icns
# Run from the QLVDesk directory: bash make_monitor_icon.sh

set -e
cd "$(dirname "$0")"

SRC="monitor_icon_1024.png"
if [ ! -f "$SRC" ]; then
    echo "Error: $SRC not found"; exit 1
fi

ICONSET="monitor_icon.iconset"
mkdir -p "$ICONSET"

echo "Generating icon sizes..."
for SIZE in 16 32 64 128 256 512; do
    sips -z $SIZE $SIZE "$SRC" --out "$ICONSET/icon_${SIZE}x${SIZE}.png"    > /dev/null
    S2=$((SIZE * 2))
    sips -z $S2 $S2 "$SRC"     --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" > /dev/null
done
sips -z 1024 1024 "$SRC" --out "$ICONSET/icon_512x512@2x.png" > /dev/null

echo "Converting to ICNS..."
iconutil -c icns "$ICONSET" -o icon_monitor.icns

rm -rf "$ICONSET"
echo "✓ icon_monitor.icns created"
