#!/usr/bin/env python3
"""Tests for the plugin-version header gate.

Each case copies this repo's real plugin.json, README.md and catalyst-setup skill
into a throwaway directory, changes one thing, and asserts the gate's verdict. The controls (the
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
SETUP_SKILL = Path("skills") / "catalyst-setup" / "SKILL.md"
HEADER = "X-Catalyst-Plugin-Version"
CURRENT = json.loads((REPO / MANIFEST).read_text(encoding="utf-8"))["version"]


def edit_manifest(root: Path, change: Callable[[dict], None]) -> None:
    path = root / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def edit_doc(root: Path, doc: Path, change: Callable[[str], str]) -> None:
    path = root / doc
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def edit_readme(root: Path, change: Callable[[str], str]) -> None:
    edit_doc(root, Path("README.md"), change)


def edit_skill(root: Path, change: Callable[[str], str]) -> None:
    edit_doc(root, SETUP_SKILL, change)


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
    edit_skill(root, lambda s: s.replace(f'"{CURRENT}"', f'"{v}"'))


def drop_first_snippet(s: str) -> str:
    """Remove the first line that sets the header, wherever it is."""
    lines = s.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if HEADER in line and CURRENT in line:
            return "".join(lines[:i] + lines[i + 1:])
    raise AssertionError("README has no header snippet to drop")


def stale_first_snippet(s: str) -> str:
    lines = s.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if HEADER in line and CURRENT in line:
            lines[i] = line.replace(CURRENT, "0.0.1")
            return "".join(lines)
    raise AssertionError("README has no header snippet to change")


def stale_last_snippet(s: str) -> str:
    lines = s.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        if HEADER in lines[i] and CURRENT in lines[i]:
            lines[i] = lines[i].replace(CURRENT, "0.0.1")
            return "".join(lines)
    raise AssertionError("no header snippet to change")


def replace_toml_with_json_duplicate(s: str) -> str:
    """Drop the Codex TOML line and repeat a JSON one, keeping the total at three."""
    lines = s.splitlines(keepends=True)
    toml = next(i for i, l in enumerate(lines) if f'{HEADER} = "' in l)
    json_line = next(l for l in lines if f'"{HEADER}":' in l)
    lines[toml] = json_line
    return "".join(lines)


def case(name: str, mutate: Callable[[Path], None], expect: str) -> tuple[str, str, bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / MANIFEST).parent.mkdir(parents=True)
        (root / MANIFEST).write_text((REPO / MANIFEST).read_text(encoding="utf-8"), encoding="utf-8")
        (root / "README.md").write_text((REPO / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
        (root / SETUP_SKILL).parent.mkdir(parents=True)
        (root / SETUP_SKILL).write_text((REPO / SETUP_SKILL).read_text(encoding="utf-8"), encoding="utf-8")
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
        case("a version bump that leaves the setup skill behind",
             lambda r: (bump_everywhere(r), edit_skill(r, lambda s: s.replace("9.9.9", CURRENT))), "reject"),
        case("one setup skill snippet left on an old version",
             lambda r: edit_skill(r, stale_first_snippet), "reject"),
        case("one README snippet left on an old version",
             lambda r: edit_readme(r, stale_first_snippet), "reject"),

        case("the last README snippet left on an old version",
             lambda r: edit_readme(r, stale_last_snippet), "reject"),
        case("the last setup skill snippet left on an old version",
             lambda r: edit_skill(r, stale_last_snippet), "reject"),
        case("the Codex snippet replaced by a duplicate JSON one in the README",
             lambda r: edit_readme(r, replace_toml_with_json_duplicate), "reject"),
        case("the Codex snippet replaced by a duplicate JSON one in the setup skill",
             lambda r: edit_skill(r, replace_toml_with_json_duplicate), "reject"),

        # The header has to be there to be right.
        case("the manifest header removed", lambda r: edit_manifest(r, set_header(None)), "reject"),
        case("the catalyst MCP server removed",
             lambda r: edit_manifest(r, lambda d: d.pop("mcpServers")), "reject"),

        # Deleting a snippet must not be a way to pass.
        case("a README snippet removed", lambda r: edit_readme(r, drop_first_snippet), "reject"),
        case("a setup skill snippet removed", lambda r: edit_skill(r, drop_first_snippet), "reject"),
        case("the setup skill removed", lambda r: (r / SETUP_SKILL).unlink(), "reject"),
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
