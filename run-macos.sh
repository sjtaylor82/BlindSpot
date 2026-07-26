#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOG_FILE="${PROJECT_DIR}/mac.log"
: >"$LOG_FILE"
exec 2>>"$LOG_FILE"

echo "Starting BlindSpot at $(date)"

find_python() {
    for candidate in \
        "${HOME}/.blindspot-venv/bin/python" \
        python3.13 python3.12 python3.11 python3
    do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c \
                'import sys, wx; raise SystemExit(sys.version_info < (3, 11))' \
                2>/dev/null
        then
            command -v "$candidate"
            return
        fi
    done
    return 1
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ]; then
    echo "No Python 3.11+ installation with wxPython was found."
    echo "Install the dependencies with:"
    echo "python3 -m pip install -r \"${PROJECT_DIR}/requirements.txt\""
    exit 1
fi

cd "$PROJECT_DIR"
export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPYCACHEPREFIX="${HOME}/Library/Caches/BlindSpot/python"
echo "Using Python: $PYTHON"
echo "Loading source from: ${PROJECT_DIR}/src"

set +e
"$PYTHON" -m blindspot
status=$?
set -e

if [ "$status" -ne 0 ]; then
    echo "BlindSpot failed with status $status. See ${LOG_FILE}"
fi
exit "$status"
