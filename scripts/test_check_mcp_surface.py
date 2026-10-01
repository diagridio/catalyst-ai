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

from check_mcp_surface import REPO, check, missing_roots, starter_eval_drift  # noqa: E402

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
    ("clean web component passes", {"web/install/c.js": "const u = 'https://mcp.cloud.r1.diagrid.io/mcp'; // catalyst_whoami\n", "web/install/package.json": '{"name": "@diagrid/catalyst-ai-install"}\n'}, False, ""),
    ("prose after diagrid in web code passes", {"web/install/c.js": "// diagrid site embed\nconst t = 'see the diagrid docs';\n"}, False, ""),
    ("prose after diagrid in the web demo passes", {"web/demo.html": "<p>on the diagrid site embed it</p>\n"}, False, ""),
    ("CLI invocation in web html", {"web/demo.html": "<code>diagrid project list</code>\n"}, True, "CLI invocation"),
    ("prose after diagrid in a README under web stays strict", {"web/install/README.md": "run diagrid site embed\n"}, True, "CLI invocation"),
    ("CLI invocation in the web component", {"web/install/c.js": "const t = 'diagrid login';\n"}, True, "CLI invocation"),
    (
        "the tunnel skill may name the tunnel commands",
        {
            "skills/catalyst-app-tunnels/SKILL.md": "Run `diagrid version`, `diagrid login`, `diagrid whoami`,\n"
            "`diagrid dev run --id x --app-port 8000` and `diagrid listen --id x`.\n",
            "evals/tunnel-mcp/graders/g.md": "diagrid dev run --id travel\n",
        },
        False,
        "",
    ),
    ("the tunnel skill may not name other CLI commands", {"skills/catalyst-app-tunnels/SKILL.md": "Run `diagrid mcpserver create x`.\n"}, True, "diagrid mcpserver"),
    ("a tunnel eval may not name other CLI commands", {"evals/tunnel-mcp/prompt.md": "diagrid project list\n"}, True, "diagrid project"),
    ("another skill may not name the tunnel commands", {"skills/catalyst-develop/SKILL.md": "Run `diagrid dev run`.\n"}, True, "diagrid dev"),
    ("an eval outside the tunnel prefix may not name them", {"evals/other/prompt.md": "diagrid listen --id x\n"}, True, "diagrid listen"),
    ("the tunnel skill may still not name a local MCP server", {"skills/catalyst-app-tunnels/SKILL.md": "Start the local MCP server.\n"}, True, "local MCP server"),
    ("local MCP server in the web demo", {"web/demo.html": "<p>Start the local MCP server.</p>\n"}, True, "local MCP server"),
    ("staging host in the web component", {"web/install/data.js": "x = 'https://mcp.cloud.staging.diagrid.dev/mcp'\n"}, True, "non-production"),
    ("unlisted host in the embed snippet", {"web/embed/diagrid-io.html": "<a href='https://api.r1.diagrid.io'>\n"}, True, "not an allowed host"),
    ("unknown tool in web data", {"web/install/install.json": '{"t": "catalyst_frobnicate"}\n'}, True, "catalyst_frobnicate"),
    ("web node_modules is skipped", {"web/install/node_modules/x/i.js": "diagrid login\n"}, False, ""),
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

    extra = 1

    def expect(name: str, found: list, needle: str) -> None:
        nonlocal extra
        extra += 1
        text = "\n".join(str(f) for f in found)
        if needle and needle not in text:
            failures.append(f"{name}: expected a finding mentioning {needle!r}, got {text or 'none'}")
        if not needle and found:
            failures.append(f"{name}: expected a pass, got {text}")

    expect("a tree without commands/ and evals/ fails", missing_roots(tree({"skills/a/SKILL.md": "x\n", "README.md": "x\n"})), "commands")
    expect("the real repo has every scanned root", missing_roots(REPO), "")
    command = "---\ndescription: d\n---\n\nDo the thing.\n"
    expect(
        "a matching starter eval passes",
        starter_eval_drift(tree({"commands/try-x.md": command, "evals/starter-x-loads-a-skill/prompt.md": "---\nname: e\n---\n\nDo the thing.\n"})),
        "",
    )
    expect(
        "a drifted starter eval fails",
        starter_eval_drift(tree({"commands/try-x.md": command, "evals/starter-x-loads-a-skill/prompt.md": "---\nname: e\n---\n\nDo another thing.\n"})),
        "body differs",
    )
    expect("a command with no eval fails", starter_eval_drift(tree({"commands/try-x.md": command})), "has no eval")
    expect(
        "a starter eval with no command fails",
        starter_eval_drift(tree({"evals/starter-y-loads-a-skill/prompt.md": "---\nname: e\n---\n\nx\n", "commands/other.md": "x\n"})),
        "does not exist",
    )
    expect("the real repo's starter evals match", starter_eval_drift(REPO), "")

    if failures:
        print("FAILED:\n" + "\n".join(f"  {f}" for f in failures), file=sys.stderr)
        return 1
    print(f"{len(CASES) + extra} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
