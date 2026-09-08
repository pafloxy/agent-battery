#!/usr/bin/env python3
"""Read Codex subscription quota through the local app-server protocol.

Only initialize, initialized, account/read, and account/rateLimits/read are sent.
No conversation or model turn is started. Auth stays with the installed Codex CLI.
Python 3.10+; standard library only.

Example:
    snapshot = read_quota({"provider": "codex", "codex_path": "/usr/bin/codex"})
    print(snapshot["serviceName"])
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import signal
import time
from typing import Any

from ..credentials import CredentialError, build_cli_runtime
from ..platforms import JsonLineProcess, ProcessError

VERSION = "0.2.1"


class QuotaError(Exception):
    """An error safe to display without including raw server responses."""


def number(value: Any) -> float | None:
    """Accept finite numeric measurements. Example: number(25) returns 25.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def text(value: Any, fallback: str = "", length: int = 80) -> str:
    """Bound printable metadata. Example: text('Codex', length=3) returns 'Cod'."""
    if not isinstance(value, str):
        return fallback
    return "".join(c for c in value if c.isprintable())[:length]


def normalize_window(raw: Any, key: str) -> dict[str, Any] | None:
    """Normalize one reported window. Example: normalize_window({'usedPercent': 20}, 'primary')."""
    if not isinstance(raw, dict):
        return None
    used = number(raw.get("usedPercent"))
    minutes = number(raw.get("windowDurationMins"))
    reset = number(raw.get("resetsAt"))
    # Missing values are unknown, never a fabricated full allowance.
    return {
        "key": key,
        "remainingPercent": None if used is None else max(0.0, min(100.0, 100.0 - used)),
        "usedPercent": used,
        "windowMinutes": minutes if minutes is not None and minutes > 0 else None,
        "resetsAt": reset if reset is not None and reset > 0 else None,
    }


def normalize_snapshot(raw: Any, timestamp: float | None = None) -> dict[str, Any]:
    """Preserve general and model-specific pools. Example: normalize_snapshot({}, 123)."""
    if not isinstance(raw, dict):
        raise QuotaError("Codex returned an unsupported quota response. Update the Codex CLI.")
    buckets: dict[str, Any] = {}
    legacy = raw.get("rateLimits")
    if isinstance(legacy, dict):
        key = text(legacy.get("limitId"), "codex") or "codex"
        buckets[key] = legacy
    multiple = raw.get("rateLimitsByLimitId")
    if isinstance(multiple, dict):
        for key, value in list(multiple.items())[:32]:
            if isinstance(key, str) and isinstance(value, dict):
                buckets[key] = value

    normalized = []
    for key, bucket in buckets.items():
        windows = [w for name in ("primary", "secondary")
                   if (w := normalize_window(bucket.get(name), name)) is not None]
        windows.sort(key=lambda w: w["windowMinutes"] if w["windowMinutes"] is not None else math.inf)
        normalized.append({
            "id": text(key),
            "name": text(bucket.get("limitName"), text(key)) or text(key),
            "windows": windows,
            "reachedType": text(bucket.get("rateLimitReachedType")),
        })
    normalized.sort(key=lambda b: (b["id"] != "codex", b["id"]))
    # Do not silently substitute a model-specific quota for the general quota.
    general = next((b for b in normalized if b["id"] == "codex"), None)
    result = {
        "ok": True,
        "updatedAt": time.time() if timestamp is None else timestamp,
        "windows": [] if general is None else general["windows"],
        "buckets": normalized,
        "ordinaryUsageAllowed": raw.get("ordinaryUsageAllowed") if isinstance(raw.get("ordinaryUsageAllowed"), bool) else None,
        "spendControlReached": raw.get("spendControlReached") if isinstance(raw.get("spendControlReached"), bool) else None,
    }
    if not result["windows"]:
        result["note"] = "No general Codex quota windows were reported. This does not mean unlimited usage."
    return result


class AppServer:
    """Read-only Codex RPC client. Example: server.request('account/read', {})."""

    def __init__(self, command: str, env: dict[str, str], cwd: str, timeout: float = 25):
        """Launch the OS transport. Example: AppServer('codex', env, '.', 25)."""
        self.serial = 0
        try:
            self.transport = JsonLineProcess([command, "app-server"], env, cwd, timeout)
        except ProcessError as exc:
            raise QuotaError("Cannot launch Codex. Check the configured executable path.") from exc
        self.process = self.transport.process

    def send(self, message: dict[str, Any]) -> None:
        """Send a protocol object. Example: server.send({'method': 'initialized'})."""
        try:
            self.transport.send(message)
        except ProcessError as exc:
            raise QuotaError(str(exc)) from exc

    def receive(self) -> dict[str, Any]:
        """Receive one RPC object. Example: response = server.receive()."""
        try:
            return self.transport.receive()
        except ProcessError as exc:
            raise QuotaError(str(exc)) from exc

    def request(self, method: str, params: Any = None) -> dict[str, Any]:
        """Match a reply and reject unsolicited RPCs. Example: server.request('account/read')."""
        self.serial += 1
        request_id = self.serial
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        while True:
            response = self.receive()
            if response.get("method") is not None:
                # This client grants no tool permissions and handles no auth-token requests.
                if "id" in response:
                    self.send({"id": response["id"], "error": {
                        "code": -32601, "message": "Read-only quota client: method not supported"}})
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                code = error.get("code") if isinstance(error, dict) else None
                if code == -32601:
                    raise QuotaError("This Codex CLI lacks the quota method. Update Codex, then retry.")
                raise QuotaError("Codex could not read subscription quota. Check codex login status, your network, and CLI version.")
            result = response.get("result")
            if not isinstance(result, dict):
                raise QuotaError("Unsupported Codex response. Update the CLI and retry.")
            return result

    def close(self) -> None:
        """Release process resources. Example: server.close()."""
        self.transport.close()


def read_quota(config: dict[str, Any]) -> dict[str, Any]:
    """Read subscription limits without a model turn. Example: read_quota({'provider': 'codex'})."""
    try:
        runtime = build_cli_runtime(
            config=config,
            provider_id="codex",
            binary_name="codex",
            binary_key="codex_path",
            home_key="codex_home",
            home_env_key="CODEX_HOME",
            default_home="~/.codex",
            cache_namespace="codex-battery",
        )
    except CredentialError as exc:
        raise QuotaError(str(exc)) from exc
    # Use a private, empty working directory: never start in a research repository.
    server = AppServer(runtime.command, runtime.env, str(runtime.cache_dir))
    try:
        server.request("initialize", {"clientInfo": {
            "name": "agent-battery", "title": "Agent Battery", "version": VERSION}})
        server.send({"method": "initialized"})
        auth = server.request("account/read", {"refreshToken": False})
        account = auth.get("account")
        if not isinstance(account, dict):
            raise QuotaError("Not signed in. Run codex login and choose your ChatGPT account.")
        if str(account.get("type", "")).lower() not in ("chatgpt", "chatgptauthtokens"):
            raise QuotaError("Codex is not using ChatGPT subscription authentication. Run codex login with the intended account.")
        result = normalize_snapshot(server.request("account/rateLimits/read"))
        result["providerId"] = "codex"
        result["serviceName"] = "Codex"
        result["panelLabel"] = "/codex"
        result["plan"] = text(account.get("planType"))
        return result
    finally:
        server.close()


def main() -> int:
    """Run this adapter's diagnostic entry point. Example: python3 -m agent_battery --help."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Local configuration JSON (contains paths, never tokens)")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text()) if args.config else {}
        if not isinstance(config, dict):
            raise QuotaError("Configuration must be a JSON object.")
        result = read_quota(config)
    except QuotaError as exc:
        result = {"ok": False, "error": str(exc)}
    except (OSError, ValueError):
        result = {"ok": False, "error": "Could not read settings or local Codex data. Re-run install.sh."}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    def stop(_signum: int, _frame: Any) -> None:
        """Unwind child cleanup on interruption. Example: stop(signal.SIGTERM, None)."""
        raise SystemExit(0)  # Unwinds read_quota's finally block, stopping the child.
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    raise SystemExit(main())
