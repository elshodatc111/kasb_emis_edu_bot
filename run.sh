#!/usr/bin/env bash
cd "$(dirname "$0")"
. .venv/bin/activate
exec python -m app.main
