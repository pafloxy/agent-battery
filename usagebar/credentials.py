#!/usr/bin/env python3
"""Resolve provider CLI runtimes without storing user secrets.

The Agent Battery extension is shipped to end users, so this module treats raw tokens
and API keys as out of scope for `config.json`. Users authenticate with each
provider's own CLI, and Agent Battery records only executable paths, config-home
locations, and a terminal PATH captured by the installer.

Example:
    runtime = build_cli_runtime(
        config={"provider": "codex", "codex_path": "/usr/bin/codex"},
        provider_id="codex",
        binary_name="codex",
        binary_key="codex_path",
        home_key="codex_home",
        home_env_key="CODEX_HOME",
        default_home="~/.codex",
        cache_namespace="usagebar-codex",
    )
    print(runtime.command)
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Any

from .platforms import cache_root


class CredentialError(Exception):
    """A sanitized credential/runtime error safe for UI display.

    Example:
        raise CredentialError("Provider CLI not found.")
    """


@dataclass(frozen=True)
class CliRuntime:
    """Resolved command, environment, and private cache directory for a provider.

    Example:
        runtime = CliRuntime(
            command="/usr/bin/codex",
            env={"PATH": "/usr/bin"},
            cache_dir=Path("~/.cache/usagebar-codex").expanduser(),
        )
        print(runtime.cache_dir)
    """

    command: str
    env: dict[str, str]
    cache_dir: Path


SECRET_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "auth_token",
    "refresh_token",
    "anthropic_api_key",
    "anthropic_auth_token",
    "claude_code_oauth_token",
    "openai_api_key",
}


def reject_inline_secrets(config: dict[str, Any]) -> None:
    """Reject config objects that try to store raw credential values.

    Example:
        reject_inline_secrets({"codex_path": "/usr/bin/codex"})
    """

    lowered = {str(key).lower() for key in config}
    found = sorted(lowered.intersection(SECRET_CONFIG_KEYS))
    if found:
        raise CredentialError(
            "Agent Battery config must not contain raw secrets. Use the provider CLI login flow instead."
        )
    for value in config.values():
        if isinstance(value, dict):
            reject_inline_secrets(value)
        elif isinstance(value, list):
            reject_inline_secrets({str(index): item for index, item in enumerate(value)})


def sanitized_env(base: dict[str, str] | None, command_path: Any) -> dict[str, str]:
    """Return a provider process environment with the installer-captured PATH.

    Example:
        env = sanitized_env({"HOME": "/home/user"}, "/usr/local/bin:/usr/bin")
        print(env["PATH"])
    """

    env = dict(os.environ if base is None else base)
    if isinstance(command_path, str) and command_path:
        env["PATH"] = command_path
    return env


def resolve_binary(env: dict[str, str], configured: Any, binary_name: str, provider_label: str) -> str:
    """Resolve a provider executable from config or PATH.

    Example:
        resolve_binary({"PATH": "/usr/bin"}, None, "python3", "Python")
    """

    if isinstance(configured, str) and configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise CredentialError(f"{provider_label} CLI path is not executable. Check the configured path.")
    discovered = shutil.which(binary_name, path=env.get("PATH"))
    if discovered:
        return discovered
    raise CredentialError(f"{provider_label} CLI not found. Install it and sign in using its official CLI.")


def build_cli_runtime(
    config: dict[str, Any],
    provider_id: str,
    binary_name: str,
    binary_key: str,
    home_key: str,
    home_env_key: str,
    default_home: str,
    cache_namespace: str,
) -> CliRuntime:
    """Build a provider runtime from non-secret Agent Battery configuration.

    Example:
        runtime = build_cli_runtime(
            config={"command_path": "/usr/bin"},
            provider_id="claude",
            binary_name="claude",
            binary_key="claude_path",
            home_key="claude_config_dir",
            home_env_key="CLAUDE_CONFIG_DIR",
            default_home="~/.claude",
            cache_namespace="usagebar-claude",
        )
        print(runtime.env["CLAUDE_CONFIG_DIR"])
    """

    reject_inline_secrets(config)
    env = sanitized_env(None, config.get("command_path"))
    configured_home = config.get(home_key)
    home = configured_home if isinstance(configured_home, str) and configured_home else env.get(home_env_key, default_home)
    env[home_env_key] = str(Path(home).expanduser().absolute())
    command = resolve_binary(env, config.get(binary_key), binary_name, provider_id)
    cache_dir = cache_root(env) / cache_namespace
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_dir.chmod(0o700)
    return CliRuntime(command=command, env=env, cache_dir=cache_dir)
