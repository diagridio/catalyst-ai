#!/usr/bin/env python3
"""Generate the data behind `@diagrid/catalyst-ai-install` (web/install/).

Two files are written, with identical content in two shapes:

* web/install/install.json  the data, for anything that reads JSON.
* web/install/data.js       the same object as an ES module. The component imports
                            this one. `import x from './install.json' with { type:
                            'json' }` is not safe across browsers yet (Safari before
                            17.2 and Firefox before 138 reject it), and a plain ES
                            module needs no build step and no runtime fetch.

Sources of truth:

* commands/*.md  each command's name (`/catalyst-ai:<file>`), its description and its
                 body, which the page offers as the paste-in prompt for clients that
                 have no slash command.
* CLIENTS below  the per-client install steps. Every step is checked against README.md,
                 so the page cannot say something the README does not.

Run:   python3 scripts/build_install_data.py           write the files
       python3 scripts/build_install_data.py --check   fail when the files are stale or
                                                       a step has drifted from the README
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = Path("web") / "install"
MCP_URL = "https://mcp.cloud.r1.diagrid.io/mcp"
PLUGIN_NAME = "catalyst-ai"
SCHEMA = 1

# Commands the page offers, in display order. A new file in commands/ must be added
# here on purpose; the generator fails on a command it does not list, so the page never
# silently omits one or advertises an unreviewed one.
COMMAND_ORDER = ("try-workflow", "try-agent")

EXACT = "exact"  # the item's text must appear in README.md, whitespace-insensitive


def item(item_id: str, label: str, text: str, lang: str = "bash", readme: Any = None) -> dict[str, Any]:
    return {"id": item_id, "label": label, "lang": lang, "text": text, "readme": readme}


def step(step_id: str, title: str, description: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {"id": step_id, "title": title, "description": description, "items": list(items)}


def prompts_step(commands: list[dict[str, Any]]) -> dict[str, Any]:
    return step(
        "prompt",
        "Paste a starter prompt",
        "This client has no slash command, so paste the whole prompt into a chat.",
        *[item(f"prompt-{c['id']}", f"{c['id']} prompt", c["prompt"], lang="text") for c in commands],
    )


def clients(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slash = [item(c["id"], c["name"], c["name"], lang="text", readme=[c["name"]]) for c in commands]
    copilot_json = (
        "{\n"
        '  "mcpServers": {\n'
        '    "catalyst": {\n'
        '      "type": "http",\n'
        f'      "url": "{MCP_URL}",\n'
        '      "oauthClientId": "copilot-cli",\n'
        '      "tools": ["*"]\n'
        "    }\n"
        "  }\n"
        "}"
    )
    vscode_json = (
        "{\n"
        '  "servers": {\n'
        '    "catalyst": {\n'
        '      "type": "http",\n'
        f'      "url": "{MCP_URL}",\n'
        '      "oauth": { "clientId": "vscode" }\n'
        "    }\n"
        "  }\n"
        "}"
    )
    return [
        {
            "id": "claude-code",
            "label": "Claude Code",
            "steps": [
                step(
                    "install",
                    "Install the plugin",
                    "Adds the skills and the Catalyst MCP server.",
                    item("marketplace-add", "marketplace add", "claude plugin marketplace add diagridio/catalyst-ai", readme=EXACT),
                    item("plugin-install", "plugin install", f"claude plugin install {PLUGIN_NAME}@diagrid", readme=EXACT),
                ),
                step(
                    "sign-in",
                    "Sign in once",
                    "In Claude Code, run /mcp, pick plugin:catalyst-ai:catalyst and finish the browser sign-in.",
                    item("mcp", "/mcp", "/mcp", lang="text", readme=["`/mcp`"]),
                ),
                step("try", "Try it", "One line each, nothing to paste.", *slash),
            ],
        },
        {
            "id": "codex",
            "label": "Codex",
            "steps": [
                step(
                    "skills",
                    "Install the skills",
                    "Writes the skills to .agents/skills/, which Codex reads.",
                    item(
                        "skills",
                        "install skills",
                        "npx -y skills add diagridio/catalyst-ai --agent codex --skill '*' --yes",
                        readme=["npx skills add diagridio/catalyst-ai", "-a codex"],
                    ),
                ),
                step(
                    "mcp-add",
                    "Add the Catalyst MCP server",
                    "Codex uses its registered OAuth client ID.",
                    item("mcp-add", "mcp add", f"codex mcp add catalyst --url {MCP_URL} --oauth-client-id codex", readme=EXACT),
                ),
                step(
                    "mcp-login",
                    "Sign in",
                    "Opens the browser sign-in.",
                    item("mcp-login", "mcp login", "codex mcp login catalyst", readme=EXACT),
                ),
                prompts_step(commands),
            ],
        },
        {
            "id": "copilot-cli",
            "label": "Copilot CLI",
            "steps": [
                step(
                    "skills",
                    "Install the skills",
                    "Writes the skills to .agents/skills/, which Copilot reads.",
                    item(
                        "skills",
                        "install skills",
                        "npx -y skills add diagridio/catalyst-ai --agent github-copilot --skill '*' --yes",
                        readme=["npx skills add diagridio/catalyst-ai", "-a github-copilot"],
                    ),
                ),
                step(
                    "mcp-config",
                    "Add the Catalyst MCP server",
                    "Put this in ~/.copilot/mcp-config.json. The oauthClientId is Copilot CLI's registered client ID.",
                    item("mcp-config", "~/.copilot/mcp-config.json", copilot_json, lang="json", readme=EXACT),
                ),
                step(
                    "sign-in",
                    "Sign in",
                    "Run /mcp inside Copilot and choose Authenticate on the catalyst server.",
                    item("mcp", "/mcp", "/mcp", lang="text", readme=["`/mcp`"]),
                ),
                prompts_step(commands),
            ],
        },
        {
            "id": "vscode",
            "label": "VS Code",
            "steps": [
                step(
                    "mcp-config",
                    "Add the Catalyst MCP server",
                    "Put this in .vscode/mcp.json. VS Code opens the browser sign-in on first use.",
                    item("mcp-config", ".vscode/mcp.json", vscode_json, lang="json", readme=EXACT),
                ),
                prompts_step(commands),
            ],
        },
    ]


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class GenerationError(Exception):
    pass


def parse_command(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(raw)
    if not match:
        raise GenerationError(f"{path}: no frontmatter")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t")):
            raise GenerationError(f"{path}: frontmatter line {line!r} is not a single-line `key: value`")
        meta[key.strip()] = value.strip()
    description = meta.get("description", "")
    body = match.group(2).strip()
    if not description or not body:
        raise GenerationError(f"{path}: needs a description and a body")
    return {
        "id": path.stem,
        "name": f"/{PLUGIN_NAME}:{path.stem}",
        "description": description,
        "prompt": body,
    }


def load_commands(root: Path) -> list[dict[str, Any]]:
    found = {p.stem: p for p in (root / "commands").glob("*.md")}
    unlisted = sorted(set(found) - set(COMMAND_ORDER))
    missing = sorted(set(COMMAND_ORDER) - set(found))
    if unlisted or missing:
        raise GenerationError(
            f"commands/ and COMMAND_ORDER disagree (unlisted: {unlisted}, missing: {missing}); "
            "update COMMAND_ORDER in scripts/build_install_data.py"
        )
    return [parse_command(found[name]) for name in COMMAND_ORDER]


def squash(text: str) -> str:
    return " ".join(text.split())


def readme_drift(data: dict[str, Any], readme: str) -> list[str]:
    flat = squash(readme)
    problems: list[str] = []
    if data["mcpUrl"] not in readme:
        problems.append(f"README.md does not contain the MCP URL {data['mcpUrl']}")
    for client in data["clients"]:
        for st in client["steps"]:
            for it in st["items"]:
                rule = it["readme"]
                anchors = [it["text"]] if rule == EXACT else (rule or [])
                for anchor in anchors:
                    if squash(anchor) not in flat:
                        problems.append(f"{client['id']}/{st['id']}/{it['id']}: README.md does not contain {squash(anchor)[:80]!r}")
    return problems


def build(root: Path) -> dict[str, Any]:
    commands = load_commands(root)
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "mcpUrl": MCP_URL,
        "commands": commands,
        "clients": clients(commands),
    }
    problems = readme_drift(data, (root / "README.md").read_text(encoding="utf-8"))
    if problems:
        raise GenerationError("install steps drifted from README.md:\n  " + "\n  ".join(problems))
    return data


def public(data: dict[str, Any]) -> dict[str, Any]:
    """The data minus the README-check rules, which are build-time only."""
    clients_out = [
        {**c, "steps": [{**s, "items": [{k: v for k, v in i.items() if k != "readme"} for i in s["items"]]} for s in c["steps"]]}
        for c in data["clients"]
    ]
    return {**data, "clients": clients_out}


def render(data: dict[str, Any]) -> dict[str, str]:
    data = public(data)
    body = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    module = (
        "// GENERATED by scripts/build_install_data.py. Do not edit by hand.\n"
        f"export const installData = {body.rstrip()};\n\nexport default installData;\n"
    )
    return {"install.json": body, "data.js": module}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    try:
        files = render(build(REPO))
    except GenerationError as error:
        print(f"build_install_data: {error}", file=sys.stderr)
        return 1
    stale = []
    for name, content in files.items():
        path = REPO / OUT_DIR / name
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(str(OUT_DIR / name))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        print(
            "build_install_data: stale, run `python3 scripts/build_install_data.py` and commit: " + ", ".join(stale),
            file=sys.stderr,
        )
        return 1
    print("install data is up to date" if check else f"wrote {', '.join(str(OUT_DIR / n) for n in files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
