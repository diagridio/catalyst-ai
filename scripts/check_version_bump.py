#!/usr/bin/env python3
"""Fail a change to plugin content that does not bump the plugin version.

This is not hygiene. Claude Code caches an installed plugin at
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, keyed by the
`version` in `.claude-plugin/plugin.json` — and `claude plugin marketplace
update` does NOT repopulate a version directory that already exists.

Measured directly, same remote and same commit both times:

    stale 0.1.0 cache present  ->  1 skill registered
    0.1.0 cache deleted        ->  9 skills registered

So shipping new skills under an unchanged version means every user who
installed the older one keeps the older one, with no error and nothing in the
UI to suggest they are out of date. The only signal is a skill that never
fires. Bumping the version is what invalidates the cache.

Run: python3 scripts/check_version_bump.py [base-ref]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = ".claude-plugin/plugin.json"

# Paths whose contents reach an installed plugin. A change under any of these is
# visible to users and therefore needs a new cache key.
VERSIONED_PREFIXES = ("skills/", ".claude-plugin/")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def version_at(ref: str) -> str | None:
    """The declared version at a ref, or None if the manifest is absent there."""
    try:
        blob = git("show", f"{ref}:{MANIFEST}")
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(blob).get("version")
    except json.JSONDecodeError:
        return None


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "origin/main"

    try:
        merge_base = git("merge-base", base, "HEAD")
    except subprocess.CalledProcessError as exc:
        print(f"cannot resolve a merge base with {base}: {exc.stderr}", file=sys.stderr)
        return 1

    changed = [p for p in git("diff", "--name-only", merge_base, "HEAD").splitlines() if p]
    touched = sorted(p for p in changed if p.startswith(VERSIONED_PREFIXES))

    if not touched:
        print(f"no plugin content changed against {base} — version bump not required")
        return 0

    before, after = version_at(merge_base), version_at("HEAD")

    if after is None:
        print(f"{MANIFEST} is missing or unparseable at HEAD", file=sys.stderr)
        return 1

    if before == after:
        print(
            f"\n{len(touched)} plugin file(s) changed but the version is still {after!r}:\n",
            file=sys.stderr,
        )
        for p in touched[:20]:
            print(f"  {p}", file=sys.stderr)
        if len(touched) > 20:
            print(f"  ... and {len(touched) - 20} more", file=sys.stderr)
        print(
            f"\nBump `version` in {MANIFEST}.\n\n"
            "Claude Code caches an installed plugin under its declared version and\n"
            "does NOT refresh a version directory it already has. Shipping this as\n"
            f"{after} means everyone who already installed {after} keeps the old\n"
            "content — no error, no warning, just skills that never fire.\n",
            file=sys.stderr,
        )
        return 1

    print(f"plugin content changed and the version moved {before} -> {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
