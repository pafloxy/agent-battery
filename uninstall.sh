#!/usr/bin/env bash
set -euo pipefail
UUID='codex-battery@local'
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    echo 'Run without sudo.' >&2
    exit 1
fi
gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
if [[ -d "$DEST" ]]; then
    /usr/bin/python3 - "$DEST/metadata.json" <<'PY'
import json, sys
if json.load(open(sys.argv[1])).get('uuid') != 'codex-battery@local':
    raise SystemExit('Unexpected extension directory; refusing to delete it.')
PY
    rm -rf -- "$DEST"
fi
rm -rf -- "${XDG_CACHE_HOME:-$HOME/.cache}/codex-battery"
rm -rf -- "${XDG_CACHE_HOME:-$HOME/.cache}/usagebar-claude"
echo 'Agent Battery removed. Your provider CLI installations and logins were left alone.'
echo 'Any installer backups in the data directory were retained.'
