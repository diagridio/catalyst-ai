#!/usr/bin/env python3
"""Tests for the server.json gate.

Each case writes a throwaway server.json and plugin.json, then asserts the
verdict. The controls must PASS, or the rejections prove only that the gate
rejects whatever it is shown.

Run: python3 scripts/test_check_server_json.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_server_json import REPO, check  # noqa: E402

URL = "https://mcp.cloud.r1.diagrid.io/mcp"


def server(**overrides: object) -> dict:
    base = {
        "name": "io.diagrid/catalyst",
        "description": "d",
        "version": "0.0.0",
        "remotes": [{"type": "streamable-http", "url": URL}],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def plugin(url: str = "${DIAGRID_MCP_URL:-" + URL + "}") -> dict:
    return {"name": "catalyst-ai", "mcpServers": {"catalyst": {"type": "http", "url": url}}}


def tree(server_doc: object, plugin_doc: object = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / ".claude-plugin").mkdir()
    if server_doc is not None:
        text = server_doc if isinstance(server_doc, str) else json.dumps(server_doc)
        (root / "server.json").write_text(text, encoding="utf-8")
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(plugin() if plugin_doc is None else plugin_doc), encoding="utf-8"
    )
    return root


CASES: list[tuple[str, Path, str]] = [
    # (name, tree, substring the failure must mention, or "" for a pass)
    ("a matching server.json passes", tree(server()), ""),
    ("a plugin URL with no env default passes", tree(server(), plugin(URL)), ""),
    ("a missing server.json fails", tree(None), "missing"),
    ("invalid JSON fails", tree("{"), "not valid JSON"),
    ("a different name fails", tree(server(name="io.diagrid/other")), "name"),
    ("a leading v fails", tree(server(version="v0.0.1")), "plain X.Y.Z"),
    ("a prerelease suffix fails", tree(server(version="0.0.1-rc.1")), "plain X.Y.Z"),
    ("packages fail", tree(server(packages=[{}])), "remote only"),
    ("no remotes fails", tree(server(remotes=None)), "exactly one remote"),
    ("two remotes fail", tree(server(remotes=[{"type": "streamable-http", "url": URL}] * 2)), "exactly one remote"),
    ("an sse remote fails", tree(server(remotes=[{"type": "sse", "url": URL}])), "remote type"),
    (
        "a drifted URL fails",
        tree(server(remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}])),
        "differs",
    ),
    ("a plugin with no catalyst server fails", tree(server(), {"mcpServers": {}}), "no mcpServers"),
]


def main() -> int:
    failures: list[str] = []
    for name, root, want in CASES:
        findings = check(root)
        if not want and findings:
            failures.append(f"{name}: expected a pass, got {findings}")
        elif want and not any(want in f for f in findings):
            failures.append(f"{name}: expected a finding mentioning {want!r}, got {findings}")

    real = check(REPO)
    if real:
        failures.append(f"the real repo's server.json fails: {real}")

    if failures:
        print("FAILED:\n" + "\n".join(f"  {f}" for f in failures), file=sys.stderr)
        return 1
    print(f"{len(CASES) + 1} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
