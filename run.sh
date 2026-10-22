#!/usr/bin/env bash
# Start DB Profile, creating the virtualenv on first run.
set -e
cd "$(dirname "$(readlink -f "$0")")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv --system-site-packages .venv
fi
# (Re)install requirements on first run and whenever requirements.txt changes.
if [ ! -f .venv/.requirements-installed ] || [ requirements.txt -nt .venv/.requirements-installed ]; then
    .venv/bin/pip install -q -r requirements.txt
    touch .venv/.requirements-installed
fi
exec .venv/bin/python -m dbprofile "$@"
