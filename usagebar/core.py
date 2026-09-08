#!/usr/bin/env python3
"""Dispatch Agent Battery quota reads to the configured provider.

Example:
    python3 -m agent_battery --config config.json --format json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
from typing import Any

from .providers.claude import ClaudeProviderError
from .providers.codex import QuotaError
from .providers.codex import read_quota as read_codex_quota
from .providers.claude import read_quota as read_claude_quota
from .credentials import CredentialError, reject_inline_secrets


PROVIDERS = {
    "codex": {"read": read_codex_quota, "quotaWindows": True},
    "claude": {"read": read_claude_quota, "quotaWindows": False},
}


def provider_id(config: dict[str, Any]) -> str:
    """Return the normalized provider id from config.

    Example:
        provider_id({"provider": "Claude"})
    """

    value = config.get("provider", "codex")
    return value.lower() if isinstance(value, str) else "codex"


def read_quota(config: dict[str, Any]) -> dict[str, Any]:
    """Read quota or availability from the configured provider.

    Example:
        snapshot = read_quota({"provider": "codex"})
        print(snapshot["ok"])
    """

    provider = provider_id(config)
    adapter = PROVIDERS.get(provider)
    if adapter is None:
        raise QuotaError("Unsupported provider. Choose one of: " + ", ".join(PROVIDERS) + ".")
    reject_inline_secrets(config)
    result = adapter["read"](config)
    result["schemaVersion"] = 1
    result["capabilities"] = {"quotaWindows": adapter["quotaWindows"], "authStatus": True}
    return result


def main() -> int:
    """Run the provider helper CLI.

    Example:
        raise SystemExit(main())
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Local configuration JSON (contains paths, never tokens)")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text()) if args.config else {}
        if not isinstance(config, dict):
            raise QuotaError("Configuration must be a JSON object.")
        result = read_quota(config)
    except (QuotaError, ClaudeProviderError, CredentialError) as exc:
        result = {"ok": False, "error": str(exc)}
    except (OSError, ValueError):
        result = {"ok": False, "error": "Could not read settings or local provider data. Re-run install.sh."}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    def stop(_signum: int, _frame: Any) -> None:
        """Stop the helper when GNOME disables the extension.

        Example:
            stop(signal.SIGTERM, None)
        """

        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    raise SystemExit(main())
