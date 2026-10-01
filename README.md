# catalyst-ai

Build and operate [Diagrid Catalyst](https://diagrid.io) by prompting — Dapr Workflows,
Durable Agents, and the running system.

**Verified end to end in Claude Code** — installs in under 5 seconds, every skill
registers, and a real Catalyst question fires the right skill and gets a grounded answer.
In **Codex** and **GitHub Copilot** the install and every skill are verified, and Codex
is confirmed to put them in front of the model; neither has yet answered a Catalyst
question here, for reasons that are
[nothing to do with the skills](#what-is-and-is-not-verified-per-client).

> **Early release.** The skills drive Catalyst through the remote Catalyst MCP server:
> you add the server and sign in once. The one exception is an app tunnel, which lets
> Catalyst call into a process on your machine. No MCP tool opens one, so
> `catalyst-app-tunnels` installs the Diagrid CLI and uses it for that alone. Read [What works today](#what-works-today) for what is and is not available
> over MCP yet.

## Install

### Claude Code

```bash
claude plugin marketplace add diagridio/catalyst-ai
claude plugin install catalyst-ai@diagrid
```

Then check it landed — **both commands, not just the second**:

```bash
claude plugin list                           # expect Version: 0.6.0 or later
claude plugin details catalyst-ai@diagrid    # expect 11 skills
```

`list` reports the version you actually have. `details` reports the version the
marketplace is offering, reading the installed copy only when the two agree — so on its
own it can show you 11 skills while your session loads 10. If either looks wrong, jump to
[If your install is behind](#if-your-install-is-behind).

#### Then sign in to the Catalyst MCP server

The plugin also registers the Catalyst MCP server, `https://mcp.cloud.r1.diagrid.io/mcp`.
It stays empty until you sign in once. In Claude Code, run `/mcp`, pick
`plugin:catalyst-ai:catalyst` and complete the browser sign-in. There is no API key.

If you already added the server yourself with `claude mcp add`, remove that entry
(`claude mcp remove catalyst --scope user`) once the plugin is installed. Otherwise you
have two copies of every Catalyst tool.

The plugin requests the scopes `catalyst:read catalyst:write offline_access`. Without
`offline_access` there is no refresh token, so you sign in again each time the session
expires. Write tools, such as `catalyst_apply`, are left out of the tool list entirely
when your role is read-only or the sign-in did not grant write scope. If they are
missing, sign in again and approve write access; if they are still missing, your role is
read-only.

Check it worked by asking: *"Who am I in Catalyst?"* The answer comes from
`catalyst_whoami`.

### Connect other clients to the remote MCP server

Every client connects to the same remote server, `https://mcp.cloud.r1.diagrid.io/mcp`
(the `r1` is required), and signs in with OAuth in the browser. The authorization server
has no dynamic registration, so each client uses its registered client ID: `codex`,
`copilot-cli`, `vscode` or `claude-code`. Install the skills for
the client first (below), then:

**Codex**

```bash
codex mcp add catalyst --url https://mcp.cloud.r1.diagrid.io/mcp --oauth-client-id codex
codex mcp login catalyst
```

**GitHub Copilot CLI**

`copilot mcp add` has no client-ID flag, so add the server and then set `oauthClientId` in
`~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "catalyst": {
      "type": "http",
      "url": "https://mcp.cloud.r1.diagrid.io/mcp",
      "oauthClientId": "copilot-cli",
      "tools": ["*"]
    }
  }
}
```

Then run `/mcp` inside Copilot and authenticate the `catalyst` server in the browser.

**VS Code** (Copilot Chat), in `.vscode/mcp.json` or your user MCP configuration:

```json
{
  "servers": {
    "catalyst": {
      "type": "http",
      "url": "https://mcp.cloud.r1.diagrid.io/mcp",
      "oauth": { "clientId": "vscode" }
    }
  }
}
```

VS Code opens a browser for authorization on the first connection. See the
[VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

**Anything else** (Gemini CLI, Zed, Antigravity and so on): add the URL as a remote
(streamable HTTP) MCP server in that client's own MCP setup and use its MCP sign-in.

### GitHub Copilot (and Gemini CLI, Zed, Antigravity)

```bash
npx -y skills add diagridio/catalyst-ai --agent github-copilot --skill '*' --yes
```

Use **repeated `--agent` flags** if you pass more than one. The comma form
(`-a codex,github-copilot`) is what the upstream README documents, and it prints
`Invalid agents:`, installs nothing and exits **1** — so it fails honestly, and a step
checking the exit code catches it. Re-measured on 1.5.22 and 1.5.23; an earlier version
of this line claimed exit 0, which was a measurement error.

The failure that *is* silent is a missing `-y` where nothing can answer the prompt, which
is every CI runner: it prints `Done!`, installs zero skills, and exits **0**. Pass `-y`,
and assert a skill count rather than an exit code.

This writes all eleven skills to `.agents/skills/`, and Copilot's own listing confirms it
reads them:

```bash
copilot skill list        # all 11 under "Project skills"
```

Copilot looks for project skills in `.github/skills/`, `.agents/skills/` and
`.claude/skills/`, so one directory covers it. Don't rely on `npx skills list` for this —
its "Agents:" line only names agents it detects as **installed on your machine**, so it
will quietly leave out a client you haven't installed yet.

### Codex

```bash
npx -y skills add diagridio/catalyst-ai --agent codex --skill '*' --yes
```

`.agents/skills/` is Codex's project skills directory too — the installer maps `codex`
there by design, so seeing no `.codex/` created is correct rather than a failed install.
Codex reads them: `codex debug prompt-input` renders the model-visible prompt, and all of them
appear in its `<skills_instructions>` block with their descriptions intact, byte for byte.
Codex's own guidance text says automatic skill selection is allowed by default, so you
shouldn't have to name a skill — though nobody has yet confirmed that from a real session.

### What is and is not verified, per client

| | skills install | skills register | a question answered |
| --- | --- | --- | --- |
| Claude Code 2.1.241 | ✅ 4.7 s | ✅ 10/10 | ✅ right skill fires unprompted, grounded answer |
| Codex 0.149.0 | ✅ 2.0 s | ✅ 10/10, in the model-visible prompt | not yet verified |
| GitHub Copilot 1.0.80 | ✅ 2.0 s | ✅ 10/10 | not yet verified |

These were measured with the first ten skills. `catalyst-app-tunnels` has not been
re-measured on these clients yet.

If you can get Codex or Copilot to answer a Catalyst question, **that is the single most
useful thing you can report** — with the wording you used and which skill fired. A skill
that never fires looks identical to a session where nothing relevant came up, which is why
this needs a human rather than an installer's exit code.

## Then just ask

New to Catalyst? In Claude Code, type one of these to see a crash-and-recover run end to
end. Each is a single line, so there's nothing to paste:

- `/catalyst-ai:try-workflow`: a durable workflow crashes mid-run and resumes where it
  stopped.
- `/catalyst-ai:try-agent`: the same for a durable AI agent (LangGraph, no API key).

In other clients, paste the matching prompt from [`commands/`](commands/). It's the same
text.

After that, you don't learn commands. Try:

> Set up Diagrid Catalyst, then show me what's in my project.

or

> Add a workflow to this repo that charges a card, books a room, and compensates if the
> booking fails.

or

> My workflow run failed. Why?

The skills fire on their own from what you ask. You shouldn't need to name one — if you
find yourself having to, that's a bug worth reporting (see [Feedback](#feedback)).

## What's in it

| skill | what it's for |
| --- | --- |
| `catalyst-setup` | Connect this session to Catalyst and confirm it works |
| `catalyst-workflow-scaffold` | Add a Dapr Workflow — orchestrator, activities, project wiring |
| `catalyst-workflow-from-diagram` | Turn a flowchart, sequence diagram, BPMN file or whiteboard photo into a workflow |
| `catalyst-agent-scaffold` | Stand up a Durable Agent as your own app, fronted by a Catalyst agent |
| `catalyst-develop` | The edit → rerun → observe loop against live Catalyst infrastructure |
| `catalyst-app-tunnels` | Let Catalyst call into a process on your machine: app to app invocation, pub/sub delivery, an agent calling an MCP server you run locally |
| `catalyst-deploy` | Move an application from your laptop into Catalyst |
| `catalyst-operate` | Inspect a running project, read-only |
| `catalyst-debug` | Diagnose why something isn't working |
| `catalyst-workflow-determinism` | Replay-safety rails for an orchestrator body |
| `catalyst-activity-idempotency` | Make activities safe to run twice |

Language and framework are **detected, not asked**. There is no `catalyst-workflow-python`
skill — the workflow skill reads your repo and works out that it's a Python project.

**Cost:** roughly **1130 tokens always-on** across all eleven (~103 each, estimated from the first ten), added to every
session whether or not a skill fires. Each skill costs a few thousand more only when it
actually fires. That figure is **per model** — `claude plugin details` resolves a tokenizer
from your active model, so the same ten descriptions cost ~103 each on Sonnet 5 and Opus 5
and ~68 each on Haiku 4.5. Quote the model with the number or it isn't reproducible.

## What works today

Being explicit, because the gap matters and you'll notice it:

| | status |
| --- | --- |
| Authoring — workflows, agents | ✅ works now |
| Operating — inspect, debug, read runs | ✅ works now, through the MCP server |
| Determinism and idempotency review | ✅ works now |
| Creating, changing, deleting and deploying resources | ✅ `catalyst_apply` and `catalyst_delete_resource`, for a role that can write |
| Workflow-run actions and access control | ✅ for a role that can write |
| Running your app, agent or MCP server locally, calling out to Catalyst | ✅ works now, through `catalyst_get_connection` |
| Letting Catalyst call into a process on your machine — an invocation target, a subscriber, an agent endpoint, the MCP server behind an `MCPServer` — and printing inbound requests | ✅ through an app tunnel, the one step that uses the Diagrid CLI (`catalyst-app-tunnels`) |
| An agent calling an MCP server on your machine through Catalyst's workflow path (`dapr.internal.mcp.*` child workflows) | ⛔ the workflow path does not reach a tunneled MCP server yet; the skill points agents at Catalyst's HTTP MCP endpoint, which works |
| Logs | ⚠️ `catalyst_get_logs` only at the `full` data-sharing level, and only the sidecar's API calls |
| Invoking an app, publishing, reading or writing state, cluster diagnostics | ⛔ not available over MCP yet |

If something is not available over MCP yet, the skills say so in one line rather than
improvising a route. If a write tool is missing, your role is read-only, not the
connection broken.

## Things the skills know that you might not

These are in the skills already; listed here because they're the ones that cost people
hours, and they all fail *silently* or with an unhelpful error.

- **Don't create a project.** Your org already has a `default` project, provisioned at
  signup, with managed pub/sub, KV, workflow store and agent infrastructure. A `Project`
  manifest in a batch creates the project it names, and projects count against a
  per-region limit you can read with `catalyst_get_usage`.
- **One pub/sub and one KV store per project, on every plan**, free and paid alike, so
  no plan upgrade buys a second one. A
  multi-agent topology shares one pub/sub across topics. These are plan values overlaid
  per organization rather than constants in the code, so the skills read the live quota
  instead of asserting the 1.
- **An `Agent` fronts *your* app.** It takes an endpoint and archive settings, not model
  settings — looking for an LLM setting means you have the wrong resource.
- **Enable the managed workflow store *before* the app exists.** The sidecar reads
  workflow config at boot, so enabling it later leaves `FAILED_PRECONDITION` on a sidecar
  that never gets retrofitted.
- **An Agent or MCP server must be created before anything else of its name.** It won't
  adopt an identity it doesn't own, and then stays in error permanently.
- **Identities are counted org-wide per region** — one per app, agent and MCP server, all
  from the same allowance — so splitting a topology across projects buys nothing.
- **Absent is not empty.** At the default `metadata` data-sharing level, workflow `input`,
  `output` and `customStatus` are *withheld*, not empty. A run that shows no output may
  have produced plenty.
- **Connection values are for local dev only.** A deployed app gets its own from the
  platform. They go inline on the launch command, into a gitignored `.env` in the app's
  folder, or through your tool's environment option, and never into chat, a pull request
  or a commit.
- **The skills use the Catalyst MCP tools for everything in Catalyst**, except opening an
  app tunnel. Never a public tunnel (cloudflared, ngrok) for that: it bypasses the App
  ID's identity and access policy.

## If your install is behind

Two different things go wrong here, with two different fixes. Start with
`claude plugin list`, because that's the command that reports what you actually have.

**Your version is older than `main`.** The marketplace is a git clone pinned at whatever
commit it last fetched, so an install from last week stays on last week's version, with
last week's skills. `claude plugin install` will *not* move it — it reports "already
installed" and changes nothing:

```bash
claude plugin marketplace update diagrid
claude plugin update catalyst-ai@diagrid     # the command that actually upgrades
claude plugin list                           # expect Version: 0.6.0 or later
```

**Your version is right but skills are missing.** Claude Code caches a plugin under its
declared version at `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and **will
not refresh a version directory it already has**. Measured: a half-populated version
directory served 4 skills of 10, while both `marketplace update` and `plugin install`
reported success and repaired nothing. Deleting the directory is the only fix:

```bash
rm -rf ~/.claude/plugins/cache/diagrid/catalyst-ai
claude plugin install catalyst-ai@diagrid
claude plugin details catalyst-ai@diagrid    # expect 11 skills
```

CI now fails any change to plugin content that doesn't bump the version, so the second one
shouldn't recur.

## Feedback

The most useful thing you can report is **a skill that didn't fire when it should have**,
with the exact wording you used. That failure is invisible from our side — it looks
identical to a session where nothing relevant happened — and the wording is the whole
diagnosis.

Also worth reporting, in rough order of value:

1. A tool a skill named that **didn't exist or didn't work**. Every `catalyst_*` name is
   checked in CI against `contracts/catalyst-mcp-tools.txt`, so a mismatch means the
   server changed or the check has a hole. Both are worth catching.
2. A skill that fired when a **different** one should have.
3. Anything a skill told you that turned out to be wrong.

Open an issue on this repository.

For a security problem, don't open an issue. See [SECURITY.md](SECURITY.md).

## Contributing

Gates run on every PR, each with its own test suite, and each exists because something
got past review or past `claude plugin validate --strict` in practice:

```bash
python3 scripts/lint_skills.py            # the real gate
python3 scripts/test_lint_skills.py       # proves the gate still catches what it claims
python3 scripts/check_mcp_surface.py      # tools, CLI and hosts, across skills, evals and README
python3 scripts/test_check_mcp_surface.py
python3 scripts/check_version_bump.py     # a plugin change must bump the version
python3 scripts/test_check_version_bump.py
python3 scripts/build_install_data.py --check   # web/install/ data matches commands/ and this README
(cd web/install && npm test)
```

`web/install/` is the npm package `@diagrid/catalyst-ai-install`, a `<catalyst-ai-install>` web
component for docs and the website. Its data is generated: after changing `commands/` or the
install steps here, run `python3 scripts/build_install_data.py` and commit the result.

`lint_skills.py` enforces what a client actually needs: `name` matching its directory, a
parseable description under 260 characters, a frontmatter allow-list, no `../` links, every
link resolving when the skill is installed *alone*, and a **0.20 similarity cap between any
two descriptions** so skills don't compete for the same trigger. It also bans a list of
substrings that each shipped somewhere and broke.

`check_mcp_surface.py` holds the skills, the evals and this README to the remote MCP
surface. Every `catalyst_*` name must appear in `contracts/catalyst-mcp-tools.txt`, which
is a copy of what the server's `tools/list` returns; update it when the server's tool list
changes. The gate also fails on any invocation of the Diagrid CLI, except the tunnel
commands (install check, sign-in and the two tunnel commands) inside
`skills/catalyst-app-tunnels/` and `evals/tunnel-*/`, on anything
that points at a server other than the remote one, and on any host under Diagrid's
domains that is not on its allowlist (the MCP server, the console, the docs and downloads
hosts, and the main site).
Tool names are matched case-insensitively. The skills drive Catalyst only through the
remote MCP server, so where a capability has no tool, the skill says it is not available
over MCP yet instead of reaching for something else.

If you add a skill, or change any skill's content, bump `version` in
`.claude-plugin/plugin.json`. Everyone who already installed keeps the old content
otherwise, and nothing tells them.

## License

Apache-2.0. See [LICENSE](LICENSE).
