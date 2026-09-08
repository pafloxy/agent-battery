#!/usr/bin/env bash
# Per-user install only. No sudo, forced logout, package upgrades, or shell hacks.
set -euo pipefail
UUID='codex-battery@local'
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
DEST="$DATA_HOME/gnome-shell/extensions/$UUID"
SUPPORTED_SHELL_RE='(^|[[:space:]])(42|43|44)([.]|$)'
AGENT_BATTERY_PROVIDER="${AGENT_BATTERY_PROVIDER:-${USAGEBAR_PROVIDER:-codex}}"

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    echo 'Run this as your normal desktop user, without sudo.' >&2
    exit 1
fi
for executable in /usr/bin/python3 gnome-shell gnome-extensions; do
    if ! command -v "$executable" >/dev/null 2>&1; then
        echo "Missing: $executable. This installer requires Linux with GNOME Shell 42-44." >&2
        exit 1
    fi
done
SHELL_VERSION="$(gnome-shell --version)"
if [[ ! "$SHELL_VERSION" =~ $SUPPORTED_SHELL_RE ]]; then
    printf 'Detected: %s\nThis build targets GNOME Shell 42-44 legacy extensions only; nothing was installed.\n' "$SHELL_VERSION" >&2
    exit 1
fi
case "$AGENT_BATTERY_PROVIDER" in
    codex)
        PROVIDER_BINARY="${CODEX_BINARY:-$(type -P codex || true)}"
        PROVIDER_BINARY_ENV='CODEX_BINARY'
        SERVICE_NAME='Codex'
        PANEL_LABEL='/codex'
        CACHE_NAMESPACE='codex-battery'
        ;;
    claude)
        PROVIDER_BINARY="${CLAUDE_BINARY:-$(type -P claude || true)}"
        PROVIDER_BINARY_ENV='CLAUDE_BINARY'
        SERVICE_NAME='Claude Code'
        PANEL_LABEL='/claude'
        CACHE_NAMESPACE='usagebar-claude'
        ;;
    *)
        printf 'Unsupported AGENT_BATTERY_PROVIDER=%s. Use codex or claude.\n' "$AGENT_BATTERY_PROVIDER" >&2
        exit 1
        ;;
esac
if [[ -z "$PROVIDER_BINARY" || ! -x "$PROVIDER_BINARY" ]]; then
    printf '%s CLI was not found on your terminal PATH.\n' "$SERVICE_NAME" >&2
    printf 'For a custom location: %s=/absolute/path/to/%s AGENT_BATTERY_PROVIDER=%s bash install.sh\n' "$PROVIDER_BINARY_ENV" "$AGENT_BATTERY_PROVIDER" "$AGENT_BATTERY_PROVIDER" >&2
    exit 1
fi
export PROVIDER_BINARY SERVICE_NAME PANEL_LABEL CACHE_NAMESPACE AGENT_BATTERY_PROVIDER
STAGE="$(mktemp -d)"
trap 'rm -rf -- "$STAGE"' EXIT
export CODEX_BATTERY_DEST="$DEST" CODEX_BATTERY_STAGE="$STAGE"
/usr/bin/python3 - <<'PY'
import json, os
from pathlib import Path
stage = Path(os.environ['CODEX_BATTERY_STAGE'])
previous = Path(os.environ['CODEX_BATTERY_DEST']) / 'config.json'
provider = os.environ['AGENT_BATTERY_PROVIDER']
config = {}
try:
    old = json.loads(previous.read_text())
    if isinstance(old, dict):
        config = old
except (OSError, ValueError):
    pass
provider_config = {
    'provider': provider,
    'service_name': os.environ['SERVICE_NAME'],
    'panel_label': os.environ['PANEL_LABEL'],
    'cache_namespace': os.environ['CACHE_NAMESPACE'],
    'command_path': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
}
if provider == 'codex':
    provider_config.update({
        'codex_path': os.path.abspath(os.environ['PROVIDER_BINARY']),
        'codex_home': str(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser().absolute()),
    })
elif provider == 'claude':
    provider_config.update({
        'claude_path': os.path.abspath(os.environ['PROVIDER_BINARY']),
        'claude_config_dir': str(Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser().absolute()),
    })
config.update(provider_config)
config.setdefault('show_numbers', False)
config.setdefault('poll_seconds', 120)
path = stage / 'config.json'
path.write_text(json.dumps(config, indent=2) + '\n')
path.chmod(0o600)
PY

printf 'Checking local %s usage protocol (no coding task is started)…\n' "$SERVICE_NAME"
if ! /usr/bin/python3 "$HERE/extension/quota.py" --config "$STAGE/config.json" > "$STAGE/quota.json"; then
    /usr/bin/python3 - "$STAGE/quota.json" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get('error', 'Quota check failed.'), file=sys.stderr)
except (OSError, ValueError):
    print('Agent Battery helper failed. Check your provider CLI installation.', file=sys.stderr)
PY
    echo 'No extension files were installed. Resolve this error and rerun install.sh.' >&2
    exit 1
fi
/usr/bin/python3 - "$STAGE/quota.json" <<'PY'
import json, sys
snapshot = json.load(open(sys.argv[1]))
print(f"Usage protocol check passed for {snapshot.get('serviceName', 'provider')}: {len(snapshot['windows'])} general window(s) reported.")
if not snapshot['windows']:
    print('The provider did not report a general quota; the panel will show unknown, not full.')
PY

if [[ -d "$DEST" ]]; then
    BACKUP="$DATA_HOME/codex-battery-backups/$(date +%d%m%y%H%M)-$$"
    mkdir -p -- "$(dirname -- "$BACKUP")"
    cp -a -- "$DEST" "$BACKUP"
    printf 'Previous version backed up to %s\n' "$BACKUP"
    gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
fi
mkdir -p -- "$DEST" "$CACHE_HOME/$CACHE_NAMESPACE"
chmod 700 -- "$DEST" "$CACHE_HOME/$CACHE_NAMESPACE"
for filename in metadata.json extension.js stylesheet.css model.js quota.py; do
    install -m 644 -- "$HERE/extension/$filename" "$DEST/$filename"
done
mkdir -p -- "$DEST/usagebar/providers"
for source in "$HERE"/usagebar/*.py "$HERE"/usagebar/providers/*.py; do
    install -m 644 -- "$source" "$DEST/${source#"$HERE/"}"
done
install -m 600 -- "$STAGE/config.json" "$DEST/config.json"
install -m 600 -- "$STAGE/quota.json" "$CACHE_HOME/$CACHE_NAMESPACE/quota.json"

gnome-extensions enable "$UUID" >/dev/null 2>&1 || true
cat <<'MSG'

Installed Agent Battery for GNOME Shell 42-44.

Save your work, log out of Ubuntu, and log back in. Then run:
  gnome-extensions enable codex-battery@local

The provider batteries appear on the right of the top bar.
Click them for exact percentages/reset countdowns and the optional number display.
An exclamation mark or dim gauge means unknown, stale, blocked, or pending reset;
it does not mean that the allowance has refilled.

To disable:
  gnome-extensions disable codex-battery@local

To uninstall, run bash uninstall.sh from this extracted folder.
MSG
