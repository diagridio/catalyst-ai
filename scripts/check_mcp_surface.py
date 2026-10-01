#!/usr/bin/env python3
"""Hold the skills, evals and README to the remote Catalyst MCP surface.

These skills drive Catalyst only through the remote MCP server. Three things
drift silently, because a skill is prose a model acts on and nothing fails to
compile:

* A `catalyst_*` tool name that is not in contracts/catalyst-mcp-tools.txt. The
  model calls it, gets "unknown tool" and improvises. lint_skills.py already
  checks this for skills/; this gate adds commands/, evals/ and README.md, which it does
  not read, and is the one place the rule is stated for the whole repo.
* A `diagrid <subcommand>` CLI invocation. There is no CLI path any more: no
  install, no login, no version pin. A skill that tells a model to run one is
  a regression to the old product.
* A local MCP server (`mcp serve`, `mcp install`) or a host outside the allowlist.
  The only server is the remote one at https://mcp.cloud.r1.diagrid.io/mcp, and
  nothing public should name another Diagrid host or environment.

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
# Case-insensitive, so `Catalyst_Apply` is found and fails; an ALL-CAPS name is an error
# kind (`CATALYST_NOT_ENABLED`), not a tool, and is skipped in check().
TOOL_REFERENCE = re.compile(r"(?<![a-z_])catalyst_[a-z0-9_]+", re.IGNORECASE)

# `diagrid`, an optional closing backtick, whitespace (a line wrap counts) and a word,
# not part of a path, scope, marketplace id or domain (`@diagrid/x`, `catalyst-ai@diagrid`,
# `diagridio/y`, `diagrid.io`, `marketplace update diagrid`). Prose says "Diagrid" with a capital. Matched over the
# whole file, not per line, so a command split across a wrap is still found.
CLI_INVOCATION = re.compile(r"(?<![\w./@-])(?<!marketplace update )diagrid`?\s+[A-Za-z-]+")
# Code under web/ (.js, .mjs, .ts, .html) is full of comments and copy that say "diagrid"
# followed by an ordinary word (`// diagrid site embed`). There only a real CLI subcommand
# after `diagrid` counts, so prose passes and `'diagrid login'` fails. Markdown and the
# other text files keep the strict CLI_INVOCATION above.
CLI_SUBCOMMANDS = (
    "login", "dev", "mcp", "project", "appid", "app", "agent", "workflow", "call", "listen",
    "apply", "component", "subscription", "web", "diagnose", "version", "update", "org",
    "region", "tokenbudget", "audit",
)
CLI_INVOCATION_CODE = re.compile(
    r"(?<![\w./@-])(?<!marketplace update )diagrid`?\s+(?:" + "|".join(CLI_SUBCOMMANDS) + r")(?![\w-])"
)
WEB_CODE_SUFFIXES = frozenset({".js", ".mjs", ".ts", ".html"})
CLI_PROSE = re.compile(r"\bdiagrid CLI\b")

LOCAL_SERVER = re.compile(r"\bmcp\s+(?:serve|install)\b|\blocal\s+MCP\s+servers?\b", re.IGNORECASE)

NON_PROD_HOSTS = re.compile(
    r"staging\.diagrid\.dev|\.stg\.diagrid\.io|\.dev\.diagrid\.io|\.local\.diagrid\.io|nip\.io"
)

# Every host under a diagrid domain that may appear in public material. Anything else
# (an internal API host, another environment) fails, whatever it is called.
DIAGRID_HOST = re.compile(r"(?<![\w-])((?:[a-z0-9-]+\.)*diagrid\.(?:io|dev))\b", re.IGNORECASE)
ALLOWED_HOSTS = frozenset(
    {
        "mcp.cloud.r1.diagrid.io",
        "catalyst.diagrid.io",
        "docs.diagrid.io",
        "diagrid.io",
        "www.diagrid.io",
        "downloads.diagrid.io",
    }
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


WEB_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml", ".js", ".mjs", ".ts", ".html", ".css"}


def _text_files(root: Path, *parts: str, suffixes: frozenset[str] | set[str] = frozenset({".md", ".json", ".txt", ".yaml", ".yml"})) -> list[Path]:
    base = root.joinpath(*parts)
    if base.is_file():
        return [base]
    if not base.is_dir():
        return []
    return sorted(
        p for p in base.rglob("*") if p.is_file() and p.suffix in suffixes and "node_modules" not in p.parts
    )


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
    text = path.read_text(encoding="utf-8")
    found: list[Finding] = []
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        shown = " ".join(match.group(0).split())
        found.append(Finding(str(path.relative_to(root)), line, message.format(match=shown)))
    return found


def _unlisted_hosts(path: Path, root: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    found: list[Finding] = []
    for match in DIAGRID_HOST.finditer(text):
        if match.group(1).lower() not in ALLOWED_HOSTS:
            line = text.count("\n", 0, match.start()) + 1
            found.append(
                Finding(
                    str(path.relative_to(root)),
                    line,
                    f"`{match.group(1)}` is not an allowed host. Public material may name only: "
                    f"{', '.join(sorted(ALLOWED_HOSTS))}.",
                )
            )
    return found


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    tools = shipped_tools(root)
    if not tools:
        findings.append(Finding(str(CONTRACT), 0, "missing or empty, so tool names cannot be checked"))
        tools = set()

    # web/ holds the install component (web/install/) and its demo and embed snippet. It
    # ships to npm and to diagrid.io, so it is held to the same surface, in code too.
    tool_files = (
        _text_files(root, "skills")
        + _text_files(root, "commands")
        + _text_files(root, "evals")
        + _text_files(root, "README.md")
        + _text_files(root, "web", suffixes=WEB_SUFFIXES)
    )
    for path in tool_files:
        text = path.read_text(encoding="utf-8")
        for match in TOOL_REFERENCE.finditer(text):
            name = match.group(0)
            if name in tools or name.isupper():
                continue
            findings.append(
                Finding(
                    str(path.relative_to(root)),
                    text.count("\n", 0, match.start()) + 1,
                    f"names `{name}`, which is not in {CONTRACT}. A model told to call it "
                    f"gets 'unknown tool' and improvises.",
                )
            )

    for path in tool_files:
        is_web_code = path.suffix in WEB_CODE_SUFFIXES and "web" in path.relative_to(root).parts[:1]
        findings += _scan(
            path, root, CLI_INVOCATION_CODE if is_web_code else CLI_INVOCATION,
            "`{match}` is a CLI invocation. Skills drive Catalyst only through `catalyst_*` tools; "
            "say the capability is not available over MCP yet instead.",
        )
        findings += _scan(
            path, root, CLI_PROSE,
            "`{match}` points at the old command-line tool. Skills drive Catalyst only through `catalyst_*` tools.",
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
        findings += _unlisted_hosts(path, root)
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
