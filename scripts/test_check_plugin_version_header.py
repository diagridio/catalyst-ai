#!/usr/bin/env python3
"""Tests for the plugin-version header gate.

Each case copies this repo's real plugin.json and README.md into a throwaway
directory, changes one thing, and asserts the gate's verdict. The controls (the
repo as it is, and a bump done properly) must pass, or the rejections prove only
that the gate rejects whatever it is shown.

Run: python3 scripts/test_check_plugin_version_header.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "check_plugin_version_header.py"
MANIFEST = Path(".claude-plugin") / "plugin.json"
HEADER = "X-Catalyst-Plugin-Version"
CURRENT = json.loads((REPO / MANIFEST).read_text(encoding="utf-8"))["version"]


def edit_manifest(root: Path, change: Callable[[dict], None]) -> None:
    path = root / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def edit_readme(root: Path, change: Callable[[str], str]) -> None:
    path = root / "README.md"
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def set_version(v: str) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        data["version"] = v
    return change


def set_header(v: str | None) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        headers = data["mcpServers"]["catalyst"].setdefault("headers", {})
        if v is None:
            headers.pop(HEADER, None)
        else:
            headers[HEADER] = v
    return change


def bump_everywhere(root: Path, v: str = "9.9.9") -> None:
    edit_manifest(root, set_version(v))
    edit_manifest(root, set_header(v))
    edit_readme(root, lambda s: s.replace(f'"{CURRENT}"', f'"{v}"'))


def drop_first_readme_snippet(s: str) -> str:
    """Remove the first line that sets the header, wherever it is."""
    lines = s.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if HEADER in line and CURRENT in line:
            return "".join(lines[:i] + lines[i + 1:])
    raise AssertionError("README has no header snippet to drop")


def stale_first_readme_snippet(s: str) -> str:
    lines = s.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if HEADER in line and CURRENT in line:
            lines[i] = line.replace(CURRENT, "0.0.1")
            return "".join(lines)
    raise AssertionError("README has no header snippet to change")


def case(name: str, mutate: Callable[[Path], None], expect: str) -> tuple[str, str, bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / MANIFEST).parent.mkdir(parents=True)
        (root / MANIFEST).write_text((REPO / MANIFEST).read_text(encoding="utf-8"), encoding="utf-8")
        (root / "README.md").write_text((REPO / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
        mutate(root)
        proc = subprocess.run([sys.executable, str(CHECKER), str(root)], capture_output=True, text=True)
        return name, expect, proc.returncode != 0, (proc.stderr + proc.stdout).strip()


def main() -> int:
    cases = [
        # Controls.
        case("the repo as it is", lambda r: None, "pass"),
        case("a version bump that moves the header everywhere", bump_everywhere, "pass"),

        # The defect this exists for: `version` moves, the header does not.
        case("a version bump that leaves the manifest header behind",
             lambda r: (bump_everywhere(r), edit_manifest(r, set_header(CURRENT))), "reject"),
        case("a version bump that leaves the README behind",
             lambda r: edit_manifest(r, lambda d: (set_version("9.9.9")(d), set_header("9.9.9")(d))), "reject"),
        case("one README snippet left on an old version",
             lambda r: edit_readme(r, stale_first_readme_snippet), "reject"),

        # The header has to be there to be right.
        case("the manifest header removed", lambda r: edit_manifest(r, set_header(None)), "reject"),
        case("the catalyst MCP server removed",
             lambda r: edit_manifest(r, lambda d: d.pop("mcpServers")), "reject"),

        # Deleting a snippet must not be a way to pass.
        case("a README snippet removed", lambda r: edit_readme(r, drop_first_readme_snippet), "reject"),
    ]

    failures = 0
    for name, expect, rejected, output in cases:
        ok = rejected == (expect == "reject")
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}\n           wanted {expect}, "
              f"got {'rejected' if rejected else 'passed'}")
        if not ok:
            print(f"           gate said:\n{output}\n")

    print()
    if failures:
        print(f"{failures} of {len(cases)} version-header tests failed", file=sys.stderr)
        return 1
    print(f"all {len(cases)} version-header tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
