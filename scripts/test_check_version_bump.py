#!/usr/bin/env python3
"""Tests for the version-bump gate.

Each case builds a throwaway git repo, commits a base, commits a change, and
asserts the gate's verdict. A gate nobody has pointed at a real repository is
not a gate.

Run: python3 scripts/test_check_version_bump.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "check_version_bump.py"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def manifest(version: str) -> str:
    return json.dumps({"name": "catalyst-ai", "version": version, "skills": "./skills/"}, indent=2)


def build_repo(root: Path) -> None:
    """A repo with a base commit on `main` and a branch off it."""
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "scripts").mkdir()
    shutil.copy(CHECKER, root / "scripts" / "check_version_bump.py")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(manifest("0.1.0"))
    (root / "skills" / "one").mkdir(parents=True)
    (root / "skills" / "one" / "SKILL.md").write_text("---\nname: one\ndescription: d\n---\n\nB.\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "change")


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "check_version_bump.py"), "main"],
        cwd=root, capture_output=True, text=True,
    )


def case(name: str, mutate, expect: str) -> tuple[str, str, bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_repo(root)
        mutate(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "change")
        proc = run(root)
        return name, expect, proc.returncode != 0, (proc.stderr + proc.stdout).strip()


def add_skill(root: Path) -> None:
    (root / "skills" / "two").mkdir()
    (root / "skills" / "two" / "SKILL.md").write_text("---\nname: two\ndescription: d\n---\n\nB.\n")


def bump(root: Path, v: str = "0.2.0") -> None:
    (root / ".claude-plugin" / "plugin.json").write_text(manifest(v))


def main() -> int:
    cases = [
        # The defect this exists for: new skill, version untouched. Users who
        # already installed 0.1.0 would never see it.
        case("a new skill without a version bump", add_skill, "reject"),

        # Editing an existing skill is just as invisible as adding one.
        case(
            "an edited skill without a version bump",
            lambda r: (r / "skills" / "one" / "SKILL.md").write_text(
                "---\nname: one\ndescription: d\n---\n\nDifferent body.\n"
            ),
            "reject",
        ),

        # The manifest itself is cached too.
        case(
            "a manifest change without a version bump",
            lambda r: (r / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "catalyst-ai", "version": "0.1.0",
                            "skills": "./skills/", "homepage": "https://x"}, indent=2)
            ),
            "reject",
        ),

        # The control: the correct workflow must pass, or the gate just blocks
        # all work and gets deleted.
        case("a new skill WITH a version bump", lambda r: (add_skill(r), bump(r)), "pass"),

        # Work that cannot reach an installed plugin must not be gated —
        # otherwise every CI or docs tweak demands a fake release.
        case(
            "changing only files outside the plugin",
            lambda r: (r / "README.md").write_text("docs\n"),
            "pass",
        ),

        # A downgrade is still a change of cache key, so it is not this gate's
        # job to police ordering — only that the key moved.
        case("a version that changed at all", lambda r: (add_skill(r), bump(r, "0.0.9")), "pass"),
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
        print(f"{failures} of {len(cases)} version-gate tests failed", file=sys.stderr)
        return 1
    print(f"all {len(cases)} version-gate tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
