#!/usr/bin/env python3
"""Fail when the `X-Catalyst-Plugin-Version` header disagrees with the plugin version.

The `catalyst` MCP server in `.claude-plugin/plugin.json` sends the header
`X-Catalyst-Plugin-Version` so the server can tell a plugin install from a server
someone added by hand, and see who is on an old version. The README and the
catalyst-setup skill tell Codex, Copilot CLI and VS Code users to set the same
header by hand.

The value is a literal, because a plugin manifest cannot interpolate its own
`version`. So every version bump has to move it in all of those places, and one
that does not would report the old version forever with nothing to show for it.
check_version_bump.py makes every plugin change bump `version`; this makes the
header follow.

Checked:

* plugin.json  `mcpServers.catalyst.headers["X-Catalyst-Plugin-Version"]` equals
               `version`.
* README.md and skills/catalyst-setup/SKILL.md
               every snippet that sets the header sets it to `version`, and there
               are at least MIN_SNIPPETS of them in each file (Codex, Copilot CLI
               and VS Code), so deleting a snippet cannot make the check pass.

web/install/ is generated from plugin.json and checked against the README by
build_install_data.py --check, so it follows from these two.

Run: python3 scripts/check_plugin_version_header.py [repo-root]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = Path(".claude-plugin") / "plugin.json"
README = Path("README.md")
SETUP_SKILL = Path("skills") / "catalyst-setup" / "SKILL.md"
HAND_SET_DOCS = (README, SETUP_SKILL)
HEADER = "X-Catalyst-Plugin-Version"
SERVER = "catalyst"
MIN_SNIPPETS = 3

# Matches the header as a JSON key (`"X-...": "0.7.2"`) or a TOML key
# (`X-... = "0.7.2"`), and captures the value.
SNIPPET_VALUE = re.compile(rf'"?{re.escape(HEADER)}"?\s*[:=]\s*"([^"]*)"')


def check(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"{MANIFEST}: cannot read: {error}"]

    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        return [f"{MANIFEST}: no `version`"]

    server = (manifest.get("mcpServers") or {}).get(SERVER)
    if not isinstance(server, dict):
        problems.append(f"{MANIFEST}: no `mcpServers.{SERVER}`")
    else:
        sent = (server.get("headers") or {}).get(HEADER)
        if sent != version:
            problems.append(
                f"{MANIFEST}: mcpServers.{SERVER}.headers[{HEADER!r}] is {sent!r}, "
                f"but `version` is {version!r}"
            )

    for doc in HAND_SET_DOCS:
        try:
            text = (root / doc).read_text(encoding="utf-8")
        except OSError as error:
            problems.append(f"{doc}: cannot read: {error}")
            continue
        values = SNIPPET_VALUE.findall(text)
        if len(values) < MIN_SNIPPETS:
            problems.append(
                f"{doc}: {len(values)} snippet(s) set {HEADER}, expected at least "
                f"{MIN_SNIPPETS} (Codex, Copilot CLI, VS Code)"
            )
        for value in values:
            if value != version:
                problems.append(f"{doc}: a snippet sets {HEADER} to {value!r}, but `version` is {version!r}")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else REPO
    problems = check(root)
    if problems:
        print(f"{HEADER} does not match the plugin version:\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            f"\nSet {HEADER} to the `version` in {MANIFEST}, in the manifest and in every\n"
            "README and catalyst-setup snippet, then run `python3 scripts/build_install_data.py`.",
            file=sys.stderr,
        )
        return 1
    print(f"{HEADER} matches the plugin version everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
