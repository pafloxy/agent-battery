"""Portable Usagebar CLI, using only Python's standard library.

Examples (repository root):
    python3 -m usagebar --demo
    python3 -m usagebar --provider codex --format json
    python3 -m usagebar --provider claude
    python3 -m usagebar --doctor
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import signal
import sys
import time
from typing import Any

from .core import PROVIDERS, read_quota
from .credentials import CredentialError, reject_inline_secrets
from .providers.codex import QuotaError
from .providers.claude import ClaudeProviderError


def demo_snapshot() -> dict[str, Any]:
    """Produce explicitly synthetic quota data. Example: demo_snapshot()['demo']."""
    now = time.time()
    windows = [{"key": "primary", "remainingPercent": 68, "usedPercent": 32,
                "windowMinutes": 300, "resetsAt": now + 5400}]
    return {"schemaVersion": 1, "ok": True, "demo": True, "providerId": "demo",
            "serviceName": "Demo (synthetic)", "updatedAt": now,
            "capabilities": {"quotaWindows": True, "authStatus": False},
            "windows": windows, "buckets": [{"id": "demo", "name": "Demo", "windows": windows}]}


def render_text(snapshot: dict[str, Any], now: float | None = None) -> str:
    """Render a compact summary with explicit unknowns. Example: render_text(demo_snapshot())."""
    if not snapshot.get("ok"):
        return "Usagebar: " + snapshot.get("error", "Usage unavailable.")
    now = time.time() if now is None else now
    lines = [snapshot.get("serviceName", "Usagebar")]
    stale = now - snapshot.get("updatedAt", 0) > 360
    if stale:
        lines.append("STALE: refresh before relying on these values")
    if snapshot.get("ordinaryUsageAllowed") is False:
        lines.append("WARNING: ordinary usage is blocked")
    if snapshot.get("spendControlReached") is True:
        lines.append("WARNING: spend control reached")
    if snapshot.get("status"):
        lines.append(snapshot["status"])
    buckets = snapshot.get("buckets") or [{"name": "General", "windows": snapshot.get("windows", [])}]
    for bucket in buckets:
        if bucket.get("reachedType"):
            lines.append("WARNING: provider reports a limit reached")
        for window in bucket.get("windows", []):
            percent = window.get("remainingPercent")
            remaining = "unknown" if percent is None else f"{percent:g}% left"
            minutes = window.get("windowMinutes")
            label = f"{minutes:g}m" if minutes else window.get("key", "window")
            reset = window.get("resetsAt")
            countdown = "reset unknown" if reset is None else (
                "reset pending refresh" if reset <= now else f"reset in {int((reset - now) / 60)}m")
            lines.append(f"{bucket.get('name', 'General')} / {label}: {remaining}, {countdown}")
    if not any(b.get("windows") for b in buckets):
        lines.append("Quota: unknown")
    if snapshot.get("note"):
        lines.append(snapshot["note"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Read once and exit; help/doctor/demo never invoke a provider. Example: main(['--demo'])."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=tuple(PROVIDERS), help="Override the configured provider")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--config", type=Path, help="Optional non-secret path settings JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Use synthetic data without a login or network")
    mode.add_argument("--doctor", action="store_true", help="Report local executable discovery, without running them")
    args = parser.parse_args(argv)
    if args.doctor:
        print(json.dumps({"platform": sys.platform, "python": sys.version.split()[0],
                          "providerExecutablesOnPath": {p: shutil.which(p) is not None for p in ("codex", "claude")}}))
        return 0
    try:
        if args.demo:
            snapshot = demo_snapshot()
        else:
            config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
            if not isinstance(config, dict):
                raise QuotaError("Configuration must be a JSON object.")
            reject_inline_secrets(config)
            if args.provider:
                config["provider"] = args.provider
            snapshot = read_quota(config)
    except (CredentialError, QuotaError, ClaudeProviderError) as exc:
        snapshot = {"schemaVersion": 1, "ok": False, "error": str(exc)}
    except (OSError, ValueError):
        snapshot = {"schemaVersion": 1, "ok": False, "error": "Could not read settings or provider data."}
    print(json.dumps(snapshot, ensure_ascii=True, allow_nan=False) if args.format == "json" else render_text(snapshot))
    return 0 if snapshot["ok"] else 1


def stop(_signum: int, _frame: Any) -> None:
    """Unwind subprocess cleanup when interrupted. Example: stop(signal.SIGTERM, None)."""
    raise SystemExit(130)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    raise SystemExit(main())
