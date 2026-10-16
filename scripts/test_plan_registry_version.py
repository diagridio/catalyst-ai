#!/usr/bin/env python3
"""Tests for the registry version planner.

Offline: each case hands plan() a registry response and a local server.json. The
cases that matter most are the skips, because a wrong publish burns a version for
good and a wrong skip silently publishes nothing.

Run: python3 scripts/test_plan_registry_version.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plan_registry_version import PUBLISHER_META, plan  # noqa: E402

LOCAL = {
    "$schema": "https://example.com/schema.json",
    "name": "io.diagrid/catalyst",
    "description": "d",
    "version": "0.0.0",
    "remotes": [{"type": "streamable-http", "url": "https://example.com/mcp"}],
}


def entry(version: str, run_id: str | None = None, **changes: object) -> dict:
    server = {**LOCAL, "version": version, **changes}
    if run_id is not None:
        server["_meta"] = {PUBLISHER_META: {"runId": run_id, "commit": "abc"}}
    return {"server": server, "_meta": {}}


CASES: list[tuple[str, list[dict], str, str, tuple[str, str] | str]] = [
    # (name, registry entries, bump, run id, expected (action, version) or error substring)
    ("first publish is 0.0.1", [], "patch", "1", ("publish", "0.0.1")),
    ("first publish ignores a minor bump", [], "minor", "1", ("publish", "0.0.1")),
    ("first publish ignores a major bump", [], "major", "1", ("publish", "0.0.1")),
    ("a changed description bumps the patch", [entry("0.0.3", description="old")], "patch", "1", ("publish", "0.0.4")),
    ("minor resets the patch", [entry("0.2.3", description="old")], "minor", "1", ("publish", "0.3.0")),
    ("major resets minor and patch", [entry("1.2.3", description="old")], "major", "1", ("publish", "2.0.0")),
    ("identical metadata on a patch bump skips", [entry("0.0.3", run_id="9")], "patch", "1", ("skip", "0.0.3")),
    ("identical metadata on a minor bump publishes", [entry("0.0.3")], "minor", "1", ("publish", "0.1.0")),
    (
        "a re-run of the run that published skips, even with a later change",
        [entry("0.0.4", run_id="7", description="old"), entry("0.0.3")],
        "minor",
        "7",
        ("skip", "0.0.4"),
    ),
    (
        "the highest version is the base, not the newest",
        [entry("0.0.2", description="old"), entry("0.1.0", description="old")],
        "patch",
        "1",
        ("publish", "0.1.1"),
    ),
    ("ordering is numeric, not lexical", [entry("0.0.9", description="o"), entry("0.0.10", description="o")], "patch", "1", ("publish", "0.0.11")),
    ("a non-plain version is ignored as a base", [entry("v9.0.0"), entry("0.0.1", description="o")], "patch", "1", ("publish", "0.0.2")),
    ("only non-plain versions start at 0.0.1", [entry("1.0.0-rc.1")], "patch", "1", ("publish", "0.0.1")),
    ("an unknown bump is rejected", [], "huge", "1", "bump must be one of"),
]


def main() -> int:
    failures: list[str] = []
    for name, entries, bump, run_id, want in CASES:
        try:
            got: tuple[str, str] | str = plan(entries, LOCAL, bump, run_id)
        except ValueError as exc:
            got = str(exc)
        ok = want in got if isinstance(want, str) and isinstance(got, str) else got == want
        if not ok:
            failures.append(f"{name}: expected {want!r}, got {got!r}")

    if failures:
        print("FAILED:\n" + "\n".join(f"  {f}" for f in failures), file=sys.stderr)
        return 1
    print(f"{len(CASES)} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
