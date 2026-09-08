#!/usr/bin/env python3
"""Claude Code provider for Agent Battery.

Claude Code currently exposes authentication status through its CLI, but this
provider does not assume a quota-window API. It reports availability and keeps
the shared Agent Battery snapshot shape so the panel can display a truthful unknown
state until a supported quota source is added.

Example:
    snapshot = read_quota({"provider": "claude", "claude_path": "/usr/bin/claude"})
    print(snapshot["serviceName"])
"""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from ..credentials import CredentialError, build_cli_runtime


class ClaudeProviderError(Exception):
    """A sanitized Claude Code provider error safe for UI display.

    Example:
        raise ClaudeProviderError("Claude Code is not signed in.")
    """


def text(value: Any, fallback: str = "", length: int = 80) -> str:
    """Return printable bounded text for optional provider metadata.

    Example:
        text("Claude Code", length=6)
    """

    if not isinstance(value, str):
        return fallback
    return "".join(c for c in value if c.isprintable())[:length]


def read_auth_status(command: str, env: dict[str, str], timeout: float = 15) -> dict[str, Any]:
    """Read `claude auth status` without exposing raw credential data.

    Example:
        status = read_auth_status("/usr/bin/claude", {"PATH": "/usr/bin"})
        print(isinstance(status, dict))
    """

    completed = subprocess.run(
        [command, "auth", "status"],
        env=env,
        cwd=None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise ClaudeProviderError("Claude Code is not signed in. Run claude auth login, then re-run install.sh.")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeProviderError("Claude Code returned invalid authentication status JSON.") from exc
    if not isinstance(data, dict):
        raise ClaudeProviderError("Claude Code returned unsupported authentication status.")
    if data.get("loggedIn") is False:
        raise ClaudeProviderError("Claude Code is not signed in. Run claude auth login.")
    return data


def read_quota(config: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-neutral snapshot for Claude Code availability.

    Example:
        snapshot = read_quota({"provider": "claude"})
        print(snapshot["providerId"])
    """

    try:
        runtime = build_cli_runtime(
            config=config,
            provider_id="claude",
            binary_name="claude",
            binary_key="claude_path",
            home_key="claude_config_dir",
            home_env_key="CLAUDE_CONFIG_DIR",
            default_home="~/.claude",
            cache_namespace="usagebar-claude",
        )
        status = read_auth_status(runtime.command, runtime.env)
    except subprocess.TimeoutExpired as exc:
        raise ClaudeProviderError("Claude Code auth status timed out. Check claude auth status in a terminal.") from exc
    except CredentialError as exc:
        raise ClaudeProviderError(str(exc)) from exc

    return {
        "ok": True,
        "providerId": "claude",
        "serviceName": "Claude Code",
        "panelLabel": "/claude",
        "updatedAt": time.time(),
        "windows": [],
        "buckets": [],
        "status": "Authenticated",
        "note": "Claude Code authentication is available, but no supported local quota-window reader is configured.",
    }
