#!/bin/zsh
cd "$(dirname "$0")"
exec uv run uvicorn worker:app --host 127.0.0.1 --port 8091 "$@"
