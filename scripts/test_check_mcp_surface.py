#!/usr/bin/env python3
"""Tests for the MCP surface gate.

Each case builds a throwaway tree, then asserts the verdict. The controls must
PASS: a gate that rejects everything proves nothing, and one whose patterns
match nothing is green on everything.

Run: python3 scripts/test_check_mcp_surface.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_mcp_surface import check  # noqa: E402

CONTRACT = "# tools\ncatalyst_whoami\ncatalyst_get_app\n"


def tree(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "contracts").mkdir()
    (root / "contracts" / "catalyst-mcp-tools.txt").write_text(CONTRACT, encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


CASES: list[tuple[str, dict[str, str], bool, str]] = [
    # (name, files, should_fail, substring the failure must mention)
    ("clean skill passes", {"skills/a/SKILL.md": "Call `catalyst_whoami`, then `catalyst_get_app`.\n"}, False, ""),
    (
        "a prefixed client name and the wildcard pass",
        {"skills/a/SKILL.md": "`mcp__plugin_catalyst-ai_catalyst__catalyst_whoami` and `catalyst_*`\n"},
        False,
        "",
    ),
    (
        "prose, packages and domains that contain 'diagrid' pass",
        {
            "skills/a/SKILL.md": "Diagrid Catalyst. `@diagrid/agent-mastra`, diagridio/x, https://mcp.cloud.r1.diagrid.io/mcp, `diagrid`.\n",
            "README.md": "Run `copilot mcp add --transport http catalyst https://mcp.cloud.r1.diagrid.io/mcp`\n",
        },
        False,
        "",
    ),
    ("unknown tool in a skill", {"skills/a/SKILL.md": "Call `catalyst_frobnicate`.\n"}, True, "catalyst_frobnicate"),
    ("unknown tool in an eval", {"evals/e/prompt.md": "uses catalyst_frobnicate\n"}, True, "catalyst_frobnicate"),
    ("unknown tool in the README", {"README.md": "catalyst_frobnicate\n"}, True, "catalyst_frobnicate"),
    ("CLI invocation in a skill", {"skills/a/SKILL.md": "Run `diagrid project list`.\n"}, True, "CLI invocation"),
    ("CLI invocation in an eval", {"evals/e/graders/g.md": "diagrid workflow get\n"}, True, "CLI invocation"),
    ("unknown tool in a command", {"commands/try.md": "Call `catalyst_frobnicate`.\n"}, True, "catalyst_frobnicate"),
    ("CLI invocation in a command", {"commands/try.md": "Run `diagrid project list`.\n"}, True, "CLI invocation"),
    ("CLI invocation in the README", {"README.md": "diagrid login\n"}, True, "CLI invocation"),
    ("mcp serve", {"skills/a/SKILL.md": "diagrid mcp serve\n"}, True, "local MCP server"),
    ("mcp install", {"README.md": "then mcp install it\n"}, True, "local MCP server"),
    ("the phrase local MCP server", {"skills/a/SKILL.md": "Start the local MCP server.\n"}, True, "local MCP server"),
    ("staging host in a skill", {"skills/a/SKILL.md": "https://mcp.cloud.staging.diagrid.dev/mcp\n"}, True, "non-production"),
    ("stg host in the README", {"README.md": "catalyst.stg.diagrid.io\n"}, True, "non-production"),
    ("dev host in an eval", {"evals/e/prompt.md": "api.dev.diagrid.io\n"}, True, "non-production"),
    ("local host in the plugin manifest", {".claude-plugin/plugin.json": '{"u": "x.local.diagrid.io"}\n'}, True, "non-production"),
    ("CLI command with a closing backtick", {"skills/a/SKILL.md": "the `diagrid` command does it\n"}, True, "CLI invocation"),
    ("CLI command split across a line wrap", {"skills/a/SKILL.md": "run diagrid\nproject list\n"}, True, "CLI invocation"),
    ("the phrase diagrid CLI", {"skills/a/SKILL.md": "install the diagrid CLI.\n"}, True, "diagrid CLI"),
    ("a wrapped local MCP server", {"skills/a/SKILL.md": "a local\nMCP server\n"}, True, "local MCP server"),
    ("a mixed-case tool name", {"skills/a/SKILL.md": "Call `Catalyst_Get_App`.\n"}, True, "Catalyst_Get_App"),
    ("a tool name with digits", {"skills/a/SKILL.md": "Call `catalyst_get_app2`.\n"}, True, "catalyst_get_app2"),
    ("an all-caps error kind passes", {"skills/a/SKILL.md": "`CATALYST_NOT_ENABLED` means no entitlement.\n"}, False, ""),
    ("a yaml file is scanned", {".github/workflows/x.yaml": "x"}, False, ""),
    ("an unlisted diagrid host in a skill", {"skills/a/SKILL.md": "https://api.r1.diagrid.io/v1\n"}, True, "not an allowed host"),
    ("a bare unlisted diagrid host in an eval", {"evals/e/prompt.md": "call api.r1.diagrid.io\n"}, True, "not an allowed host"),
    ("allowlisted hosts pass", {"README.md": "https://catalyst.diagrid.io/x https://docs.diagrid.io https://diagrid.io mail a@diagrid.io\n"}, False, ""),
    ("marketplace id and repo path pass", {"README.md": "claude plugin install catalyst-ai@diagrid    # ok\nclaude plugin marketplace update diagrid\nclaude plugin update x\nhttps://github.com/diagridio/catalyst-ai\n"}, False, ""),
    ("the override variable alone passes", {".claude-plugin/plugin.json": '{"u": "${DIAGRID_MCP_URL:-https://mcp.cloud.r1.diagrid.io/mcp}"}\n'}, False, ""),
]


def main() -> int:
    failures: list[str] = []
    for name, files, should_fail, needle in CASES:
        found = check(tree(files))
        text = "\n".join(str(f) for f in found)
        if should_fail and (not found or needle not in text):
            failures.append(f"{name}: expected a finding mentioning {needle!r}, got {text or 'none'}")
        if not should_fail and found:
            failures.append(f"{name}: expected a pass, got {text}")

    missing = Path(tempfile.mkdtemp())
    if not check(missing):
        failures.append("a tree with no contract must fail")

    if failures:
        print("FAILED:\n" + "\n".join(f"  {f}" for f in failures), file=sys.stderr)
        return 1
    print(f"{len(CASES) + 1} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
