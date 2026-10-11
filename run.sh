#!/usr/bin/env bash
# photoArch launcher: uses the project venv, installs deps if needed, runs the app.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR="venv"
PY="$VENV_DIR/bin/python"
REQ="requirements.txt"

if [ ! -x "$PY" ]; then
    echo "🔧 Creating virtual environment in ./$VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

if ! "$PY" -c "import textual, PIL" >/dev/null 2>&1; then
    echo "📦 Installing dependencies from $REQ ..."
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r "$REQ"
fi

exec "$PY" -m photoarch "$@"
