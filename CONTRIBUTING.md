# Contributing

Thanks for helping. Bugs and skills that misfire are best reported as an issue first;
see [Feedback](README.md#feedback). For a security problem, see [SECURITY.md](SECURITY.md).

## Checks

These gates run on every pull request, each with its own test suite, and each exists
because something got past review or past `claude plugin validate --strict` in practice.
Run them before you open a pull request:

```bash
python3 scripts/lint_skills.py            # the real gate
python3 scripts/test_lint_skills.py       # proves the gate still catches what it claims
python3 scripts/check_mcp_surface.py      # tools, CLI and hosts, across skills, evals and README
python3 scripts/test_check_mcp_surface.py
python3 scripts/check_version_bump.py     # a plugin change must bump the version
python3 scripts/test_check_version_bump.py
python3 scripts/check_plugin_version_header.py   # the MCP version header matches the plugin version
python3 scripts/test_check_plugin_version_header.py
python3 scripts/check_server_json.py      # server.json: registry name, and the same URL as the plugin
python3 scripts/test_check_server_json.py
python3 scripts/test_plan_registry_version.py   # the MCP Registry version planner
```

`lint_skills.py` needs PyYAML (`pip install pyyaml`). The others use the standard library
only.

`lint_skills.py` enforces what a client actually needs: `name` matching its directory, a
parseable description under 260 characters, a frontmatter allow-list, no `../` links, every
link resolving when the skill is installed *alone*, and a **0.20 similarity cap between any
two descriptions** so skills don't compete for the same trigger. It also bans a list of
substrings that each shipped somewhere and broke.

`check_mcp_surface.py` holds the skills, the evals and the README to the remote MCP
surface. Every `diagrid_*` name must appear in `contracts/diagrid-mcp-tools.txt`, which
is a copy of what the server's `tools/list` returns; update it when the server's tool list
changes. An old `catalyst_*` tool name, or the old server key `catalyst`, fails it.
`contracts/catalyst-mcp-tools.txt` keeps the same list under the old names, because
plugins up to 0.8.x still call them and the server's CI checks it still serves them; leave
it as it is until those names are retired. The gate also fails on any invocation of the
Diagrid CLI, except the tunnel commands (install check, sign-in and the two tunnel commands) inside
`skills/diagrid-app-tunnels/` and `evals/tunnel-*/`, on anything
that points at a server other than the remote one, and on any host under Diagrid's
domains that is not on its allowlist (the MCP server, the console, the docs and downloads
hosts, and the main site).
Tool names are matched case-insensitively. The skills drive Diagrid only through the
remote MCP server, so where a capability has no tool, the skill says it is not available
over MCP yet instead of reaching for something else.

## Bumping the version

If you add a skill, or change any skill's content, bump `version` in
`.claude-plugin/plugin.json`. Everyone who already installed keeps the old content
otherwise, and nothing tells them. Every bump also changes the `X-Diagrid-Plugin-Version`
header: set it to the new version under `mcpServers.diagrid.headers` in `plugin.json`, in
the three snippets in the README's install steps (Codex, Copilot CLI and VS Code), and in
the same three setups in `skills/diagrid-setup/SKILL.md`.
`check_plugin_version_header.py` checks all of them.

## Measuring a session

To measure a run of the plugin, finish the session and run this from the same directory:

```bash
python3 scripts/session_metrics.py --latest                   # Claude Code
python3 scripts/session_metrics.py --client codex --latest    # Codex
python3 scripts/session_metrics.py --client copilot --latest  # GitHub Copilot CLI
```

It reads the client's session log and prints a one-row Markdown table with the same columns for
each client: tokens, model requests, tool calls, user turns and the skills loaded. A cell the log
cannot fill shows `-`, for example Copilot's tokens when the session was killed before it could
write its totals. It prints counts and names only, never what was typed or a tool's arguments.
The Codex and Copilot readers are built from those clients' source and docs and have not yet been
checked against a real session. It is not a gate; `python3 scripts/test_session_metrics.py` tests it.
