#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_PATH="$SCRIPT_DIR/BlindSpot.app"
EXECUTABLE_PATH="$APP_PATH/Contents/MacOS/BlindSpot"

if [ ! -d "$APP_PATH" ]; then
    echo "BlindSpot.app was not found beside this script."
    exit 1
fi

if [ ! -f "$EXECUTABLE_PATH" ]; then
    echo "The BlindSpot executable was not found inside BlindSpot.app."
    exit 1
fi

xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true
if xattr -pr com.apple.quarantine "$APP_PATH" >/dev/null 2>&1; then
    echo "BlindSpot's quarantine attribute could not be removed."
    exit 1
fi

echo "BlindSpot is ready to open."
open "$APP_PATH"
