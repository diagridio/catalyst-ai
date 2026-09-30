#!/usr/bin/env python3
"""Hold the skills, evals and README to the remote Catalyst MCP surface.

These skills drive Catalyst only through the remote MCP server. Three things
drift silently, because a skill is prose a model acts on and nothing fails to
compile:

* A `catalyst_*` tool name that is not in contracts/catalyst-mcp-tools.txt. The
  model calls it, gets "unknown tool" and improvises. lint_skills.py already
  checks this for skills/; this gate adds evals/ and README.md, which it does
  not read, and is the one place the rule is stated for the whole repo.
* A `diagrid <subcommand>` CLI invocation. There is no CLI path any more: no
  install, no login, no version pin. A skill that tells a model to run one is
  a regression to the old product.
* A local MCP server (`mcp serve`, `mcp install`) or a non-production host. The
  only server is the remote one at https://mcp.cloud.r1.diagrid.io/mcp, and
  nothing public should name another environment.

Run: python3 scripts/check_mcp_surface.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTRACT = Path("contracts") / "catalyst-mcp-tools.txt"

# Same shape as lint_skills.TOOL_REFERENCE: not preceded by a letter or underscore,
# so a client's prefixed name (`..._catalyst__catalyst_whoami`) still resolves.
TOOL_REFERENCE = re.compile(r"(?<![a-z_])catalyst_[a-z]+[a-z_]*")

# `diagrid` followed by a space and a word, not part of a path, scope or domain
# (`@diagrid/x`, `diagridio/y`, `diagrid.io`). Prose says "Diagrid" with a capital.
CLI_INVOCATION = re.compile(r"(?<![\w./@-])diagrid +[A-Za-z-]+")

# Every one of these names something that must not appear.
LOCAL_SERVER = re.compile(r"\bmcp +(?:serve|install)\b|\blocal MCP server\b", re.IGNORECASE)
NON_PROD_HOSTS = re.compile(
    r"staging\.diagrid\.dev|\.stg\.diagrid\.io|\.dev\.diagrid\.io|\.local\.diagrid\.io|nip\.io"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _text_files(root: Path, *parts: str) -> list[Path]:
    base = root.joinpath(*parts)
    if base.is_file():
        return [base]
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in {".md", ".json", ".txt"})


def shipped_tools(root: Path) -> set[str] | None:
    contract = root / CONTRACT
    if not contract.is_file():
        return None
    return {
        line.strip()
        for line in contract.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _scan(path: Path, root: Path, pattern: re.Pattern[str], message: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for match in pattern.finditer(line):
            found.append(Finding(str(path.relative_to(root)), number, message.format(match=match.group(0).strip())))
    return found


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    tools = shipped_tools(root)
    if not tools:
        findings.append(Finding(str(CONTRACT), 0, "missing or empty, so tool names cannot be checked"))
        tools = set()

    tool_files = _text_files(root, "skills") + _text_files(root, "evals") + _text_files(root, "README.md")
    for path in tool_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for name in TOOL_REFERENCE.findall(line):
                if name not in tools:
                    findings.append(
                        Finding(
                            str(path.relative_to(root)),
                            number,
                            f"names `{name}`, which is not in {CONTRACT}. A model told to call it "
                            f"gets 'unknown tool' and improvises.",
                        )
                    )

    for path in tool_files:
        findings += _scan(
            path, root, CLI_INVOCATION,
            "`{match}` is a CLI invocation. Skills drive Catalyst only through `catalyst_*` tools; "
            "say the capability is not available over MCP yet instead.",
        )
        findings += _scan(
            path, root, LOCAL_SERVER,
            "`{match}` names a local MCP server. The only server is the remote one.",
        )

    host_files = tool_files + _text_files(root, ".claude-plugin")
    for path in host_files:
        findings += _scan(
            path, root, NON_PROD_HOSTS,
            "`{match}` is a non-production host and must not appear in public material.",
        )
    return findings


def main() -> int:
    findings = check(REPO)
    if findings:
        print("MCP surface check FAILED:\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("MCP surface check passed: every tool name is in the contract, and no CLI, local-server or non-production reference remains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
