#!/bin/zsh
# Start AnyVoice. Open http://<this-mac-ip>:8080 on your phone (same Wi-Fi).
cd "$(dirname "$0")"
echo "LAN: http://$(ipconfig getifaddr en0 2>/dev/null || hostname):8080"
exec uv run uvicorn server:app --host 0.0.0.0 --port 8080 "$@"
