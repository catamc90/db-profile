#!/usr/bin/env bash
# Start DB Profile, creating the virtualenv on first run.
set -e
cd "$(dirname "$(readlink -f "$0")")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python -m dbprofile "$@"
