# diagrid-ai

[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.diagrid%2Fmcp-blue)](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.diagrid/mcp)
[![npm](https://img.shields.io/npm/v/@diagrid/catalyst-ai-install)](https://www.npmjs.com/package/@diagrid/catalyst-ai-install)
[![lint](https://github.com/diagridio/diagrid-ai/actions/workflows/lint.yaml/badge.svg)](https://github.com/diagridio/diagrid-ai/actions/workflows/lint.yaml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Skills and a remote MCP server that give coding assistants durable execution on
[Diagrid](https://docs.diagrid.io), built on Dapr: build Dapr Workflows and Durable Agents,
and operate the running system, by prompting. Works in Claude Code, Codex, GitHub Copilot,
VS Code and any client that speaks remote MCP.

**Related:** SDKs for
[Python](https://github.com/diagridio/python-ai),
[TypeScript](https://github.com/diagridio/typescript-ai),
[.NET](https://github.com/diagridio/dotnet-ai),
[Go](https://github.com/diagridio/go-ai),
[Java](https://github.com/diagridio/java-ai) and
[Rust](https://github.com/diagridio/rust-ai), and runnable examples in
[catalyst-quickstarts](https://github.com/diagridio/catalyst-quickstarts).

> **Early release.** The skills drive Diagrid through the remote Diagrid MCP server:
> you add the server and sign in once. The one exception is an app tunnel, which lets
> Diagrid call into a process on your machine. No MCP tool opens one, so
> `diagrid-app-tunnels` installs the Diagrid CLI and uses it for that alone. Read
> [What works today](#what-works-today) for what is and is not available over MCP yet.

## Install

Pick your client. Each block installs the skills, then connects the Diagrid MCP server,
then signs you in. You need a Diagrid account to sign in. Diagrid has a permanent free
tier: [sign up in the Diagrid Console](https://catalyst.diagrid.io).

Every client connects to the same remote server, `https://mcp.cloud.r1.diagrid.io/mcp`
(the `r1` is required), and signs in with OAuth in the browser. There is no API key. The
authorization server does not accept dynamic registration, so each client uses its own
registered client ID: `claude-code`, `codex`, `copilot-cli`, `vscode`, or `claude-web`
for claude.ai. VS Code and the Copilot CLI can also sign in without one, because the
server reads the client metadata they publish.

The Codex, Copilot CLI and VS Code snippets set an `X-Diagrid-Plugin-Version` header to
the plugin version, so the server can see which version of these instructions a client
was set up from. It goes only on the MCP requests the client already makes. When you
update the skills, update the header to match.

### Claude Code

1. **Skills.** Install the plugin:

   ```bash
   claude plugin marketplace add diagridio/diagrid-ai
   claude plugin install diagrid@diagrid
   ```

   Check it landed. Run both commands, not just the second:

   ```bash
   claude plugin list                     # expect Version: 0.10.0 or later
   claude plugin details diagrid@diagrid  # expect 12 skills
   ```

   `list` reports the version you have; `details` reports the one the marketplace offers.
   If either looks wrong, see [If your install is behind](#if-your-install-is-behind).

2. **MCP.** The plugin registers the Diagrid MCP server for you. If you added it yourself
   earlier with `claude mcp add`, remove that entry (`claude mcp remove catalyst --scope user`),
   or you get two copies of every Diagrid tool.

3. **Sign in.** Run `/mcp`, pick `plugin:diagrid:diagrid` and complete the browser
   sign-in. Then ask: *"Who am I in Diagrid?"* The answer comes from `diagrid_whoami`.

The plugin requests the scopes `catalyst:read catalyst:write offline_access`. Without
`offline_access` there is no refresh token, so you sign in again each time the session
expires. Write tools, such as `diagrid_apply`, are left out of the tool list when your
role is read-only or the sign-in did not grant write scope. If they are missing, sign in
again and approve write access; if they are still missing, your role is read-only.

If you installed `catalyst-ai@diagrid` before, that is this plugin under its old name: see
[Moving from catalyst-ai](#moving-from-catalyst-ai). The repo used to be
`diagridio/catalyst-ai`; GitHub redirects the old name, so a marketplace added from it
keeps updating.

### Codex

1. **Skills.** From your repository's root:

   ```bash
   npx -y skills add diagridio/diagrid-ai --agent codex --skill '*' --yes
   ```

   The skills land in `.agents/skills/`, which is Codex's project skills directory. No
   `.codex/` directory is created, and that is expected.

2. **MCP.**

   ```bash
   codex mcp add diagrid --url https://mcp.cloud.r1.diagrid.io/mcp --oauth-client-id codex
   ```

   `codex mcp add` has no header flag, so add this to `~/.codex/config.toml` under the
   server it just wrote:

   ```toml
   [mcp_servers.diagrid.http_headers]
   X-Diagrid-Plugin-Version = "0.10.2"
   ```

3. **Sign in.**

   ```bash
   codex mcp login diagrid
   ```

### GitHub Copilot CLI

1. **Skills.** From your repository's root:

   ```bash
   npx -y skills add diagridio/diagrid-ai --agent github-copilot --skill '*' --yes
   ```

   This writes all 12 skills to `.agents/skills/`, one of Copilot's project skills
   directories. Run `/skills list` inside Copilot and expect all 12. Don't add `--global`:
   it writes `~/.agents/skills/`, which Copilot does not read; see
   [Copilot sees no skills](docs/troubleshooting.md#copilot-sees-no-skills).

2. **MCP.** Add the server to `~/.copilot/mcp-config.json`. `copilot mcp add` has no
   client-ID flag, so set `oauthClientId` here:

   ```json
   {
     "mcpServers": {
       "diagrid": {
         "type": "http",
         "url": "https://mcp.cloud.r1.diagrid.io/mcp",
         "headers": { "X-Diagrid-Plugin-Version": "0.10.2" },
         "oauthClientId": "copilot-cli",
         "tools": ["*"]
       }
     }
   }
   ```

3. **Sign in.** Run `/mcp` inside Copilot and authenticate the server in the browser.

### VS Code (Copilot Chat)

1. **Skills.** From your workspace root:

   ```bash
   npx -y skills add diagridio/diagrid-ai --agent github-copilot --skill '*' --yes
   ```

   This writes `.agents/skills/`. Whether VS Code also reads `~/.copilot/skills/` is not
   yet verified, so install per workspace.

2. **MCP.** In `.vscode/mcp.json` or your user MCP configuration:

   ```json
   {
     "servers": {
       "diagrid": {
         "type": "http",
         "url": "https://mcp.cloud.r1.diagrid.io/mcp",
         "headers": { "X-Diagrid-Plugin-Version": "0.10.2" },
         "oauth": { "clientId": "vscode" }
       }
     }
   }
   ```

   See the
   [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

3. **Sign in.** VS Code opens a browser for authorization on the first connection.

### Gemini CLI, Zed, Antigravity and other clients

1. **Skills.** These read the shared `.agents/skills/` project directory. From your
   repository's root:

   ```bash
   npx -y skills add diagridio/diagrid-ai --agent github-copilot --skill '*' --yes
   ```

   Without `--global`, the `github-copilot` target writes that shared directory.

2. **MCP.** Add `https://mcp.cloud.r1.diagrid.io/mcp` as a remote (streamable HTTP) MCP
   server in the client's own MCP setup.

3. **Sign in.** Use the client's MCP sign-in.

### claude.ai and Claude Desktop

This route gives you the MCP tools only. Custom connectors cannot carry skills, so for
the skills use one of the clients above.

1. **MCP.** In claude.ai, open **Settings → Connectors → Add custom connector** and enter
   the server URL. Under **Advanced settings**, set the OAuth client ID to `claude-web`.
   Without it the connector tries to register itself and the sign-in fails. Claude
   Desktop uses the connectors of the same account.
2. **Sign in.** Click **Connect** and sign in.

Custom connectors cannot set request headers, so this one sends no
`X-Diagrid-Plugin-Version`.

### Find the server in the MCP Registry

The server is listed in the official MCP Registry as `io.diagrid/mcp`
([search the registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.diagrid/mcp)),
so clients with a registry-backed server gallery can find it there. The earlier entry,
`io.diagrid/catalyst`, points at the same URL and is superseded by `io.diagrid/mcp`.

### Verified per client

| client | skills installed | skills loaded by the client | a Diagrid question answered |
| --- | --- | --- | --- |
| Claude Code | ✅ 12/12 | ✅ | ✅ the right skill fires unprompted |
| Codex | ✅ 12/12 | ✅ in the model-visible prompt | not yet verified |
| GitHub Copilot CLI | ✅ 12/12 | ✅ per-project install; `--global` is not read | not yet verified |
| VS Code (Copilot Chat) | ✅ 12/12 | not yet verified | not yet verified |
| claude.ai | MCP only | MCP only | ✅ answered who was signed in |

CI runs the real installer for Claude Code, Codex and Copilot on every pull request and
checks that every skill in `skills/` lands. Loading in each client was last checked by
hand before `diagrid-app-tunnels` and `diagrid-agent-harness` were added. If you get Codex or Copilot to answer a
Diagrid question, please [report it](#feedback) with the wording you used and which
skill fired.

## Upgrading

### Moving from catalyst-ai

0.10.0 renamed the plugin from `catalyst-ai` to `diagrid`. Claude Code treats a renamed
plugin as a new one, so `claude plugin update` does not move you across. The
`catalyst-ai` entry stays in the marketplace, held at its final release, 0.9.1. That release
still works, gets no new skills, and at the start of every session shows these steps
as one command, with a reminder to sign in again through `/mcp`.

```bash
claude plugin marketplace update diagrid
claude plugin install diagrid@diagrid
claude plugin uninstall catalyst-ai@diagrid
```

Uninstall the old plugin. With both installed, every skill and every tool shows up twice.
Then run `/mcp`, and if `plugin:diagrid:diagrid` shows it needs authentication, pick it
and sign in. The commands are now `/diagrid:try-workflow` and `/diagrid:try-agent`, and the
skills are `diagrid:diagrid-deploy`, `diagrid:diagrid-setup` and so on.

In Codex, Copilot and the other clients that install with `npx skills add`, run your
client's install command again. It adds the `diagrid-*` skills but leaves the old
`catalyst-*` folders in place, so the agent sees every skill twice until you delete them
from the directory the installer wrote:

```bash
rm -rf .agents/skills/catalyst-*        # a per-project install
rm -rf ~/.copilot/skills/catalyst-*     # a Copilot install with --global
```

### Upgrading from 0.8.x

0.9.0 renamed two things. A client set up for 0.8.x needs both of them changed.

- **The header.** The server chooses tool names by the header a request sends. A request
  that still sends the old `X-Catalyst-Plugin-Version` header gets the old `catalyst_*`
  tool names. The 0.9.0 skills call only `diagrid_*` tools, so every call they make fails
  as an unknown tool. Updating the version number on the old header does not fix this.
  Replace the header itself with `X-Diagrid-Plugin-Version`, set to the current version:
  - Codex: in `~/.codex/config.toml`, find the `http_headers` table under your Diagrid
    server and change the key to `X-Diagrid-Plugin-Version`.
  - Copilot CLI (`~/.copilot/mcp-config.json`) and VS Code (`mcp.json`): change the key
    in that server's `headers`.

  You can also remove the old entry and add the server again from the snippets above.
- **The server name in Claude Code.** 0.9.0 registered the server as
  `plugin:catalyst-ai:diagrid`, and 0.10.0 renamed the plugin itself. Follow
  [Moving from catalyst-ai](#moving-from-catalyst-ai).

To check, ask *"Who am I in Diagrid?"* The answer should come from `diagrid_whoami`.

## Also in this marketplace: dapr-skills

This marketplace lists a second plugin,
[`dapr-skills`](https://github.com/diagrid-labs/dapr-skills): the same subjects on
**open-source Dapr** — scaffold a new app, add Dapr to an existing one, migrate a
TypeScript service onto Dapr building blocks, and review Dapr Workflow, pub/sub and
durable agent code that runs on your own machine under the Dapr CLI or .NET Aspire.

```bash
claude plugin install dapr-skills@diagrid
```

They are built to sit side by side. Each `dapr-skills` skill that overlaps with one here
says so in its description and points at this plugin for anything that runs on Diagrid,
which is meant to keep the two from both firing on the same question. Nothing in CI checks
that across repos yet, so if both plugins answer one request, please report it. The
`dapr-skills` source is pinned to a commit in
[`marketplace.json`](.claude-plugin/marketplace.json) and moves only through a reviewed
change here.

## Then just ask

New to Diagrid? In Claude Code, type one of these to see a crash-and-recover run end to
end. Each is a single line, so there's nothing to paste:

- `/diagrid:try-workflow`: a durable workflow crashes mid-run and resumes where it
  stopped.
- `/diagrid:try-agent`: the same for a durable AI agent. It defaults to LangGraph,
  which needs no API key. Name a framework from
  [catalyst-quickstarts](https://github.com/diagridio/catalyst-quickstarts/tree/main/agents)
  to get that one instead: `/diagrid:try-agent crewai`.

In other clients, paste the matching prompt from [`commands/`](commands/). It's the same
text. The agent prompt opens with "Use the agent framework I named in my message", so add
that name to what you paste — `Use crewai.` on the end does it.

After that, you don't learn commands. Try:

> Set up Diagrid, then show me what's in my project.

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
| `diagrid-setup` | Connect this session to Diagrid and confirm it works |
| `diagrid-workflow-scaffold` | Add a Dapr Workflow — orchestrator, activities, project wiring |
| `diagrid-workflow-from-diagram` | Turn a flowchart, sequence diagram, BPMN file or whiteboard photo into a workflow |
| `diagrid-agent-scaffold` | Stand up a Durable Agent as your own app, fronted by a Diagrid agent |
| `diagrid-agent-harness` | Make your own agent loop durable — every model call and tool call its own activity |
| `diagrid-develop` | The edit → rerun → observe loop against live Diagrid infrastructure |
| `diagrid-app-tunnels` | Let Diagrid call into a process on your machine: app to app invocation, pub/sub delivery, an agent calling an MCP server you run locally |
| `diagrid-deploy` | Move an application from your laptop into Diagrid |
| `diagrid-operate` | Inspect a running project, read-only |
| `diagrid-debug` | Diagnose why something isn't working |
| `diagrid-workflow-determinism` | Replay-safety rails for an orchestrator body |
| `diagrid-activity-idempotency` | Make activities safe to run twice |

Language and framework are **detected, not asked**. There is no `catalyst-workflow-python`
skill — the workflow skill reads your repo and works out that it's a Python project.

The skill descriptions add a small, fixed token cost to every session; see
[Token cost](docs/troubleshooting.md#token-cost).

## What works today

Being explicit, because the gap matters and you'll notice it:

| | status |
| --- | --- |
| Authoring — workflows, agents | ✅ works now |
| Operating — inspect, debug, read runs | ✅ works now, through the MCP server |
| Determinism and idempotency review | ✅ works now |
| Creating, changing, deleting and deploying resources | ✅ `diagrid_apply` and `diagrid_delete_resource`, for a role that can write |
| Workflow-run actions and access control | ✅ for a role that can write |
| Running your app, agent or MCP server locally, calling out to Diagrid | ✅ works now, through `diagrid_get_connection` |
| Letting Diagrid call into a process on your machine — an invocation target, a subscriber, an agent endpoint, the MCP server behind an `MCPServer` — and printing inbound requests | ✅ through an app tunnel, the one step that uses the Diagrid CLI (`diagrid-app-tunnels`) |
| An agent calling an MCP server on your machine through Diagrid's workflow path (`dapr.internal.mcp.*` child workflows) | ⛔ the workflow path does not reach a tunneled MCP server yet; the skill points agents at Diagrid's HTTP MCP endpoint, which works |
| Logs | ⚠️ `diagrid_get_logs` only at the `full` data-sharing level, and only the sidecar's API calls |
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
  per-region limit you can read with `diagrid_get_usage`.
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
- **The skills use the Diagrid MCP tools for everything in Diagrid**, except opening an
  app tunnel. Never a public tunnel (cloudflared, ngrok) for that: it bypasses the App
  ID's identity and access policy.

## If your install is behind

Start with `claude plugin list`, which reports the version you actually have.

**Your version is older than `main`.** `claude plugin install` will not move it; it
reports "already installed" and changes nothing. Update instead:

```bash
claude plugin marketplace update diagrid
claude plugin update diagrid@diagrid
claude plugin list                     # expect Version: 0.10.0 or later
```

**Your version is right but skills are missing.** Delete the cached copy and install
again:

```bash
rm -rf ~/.claude/plugins/cache/diagrid/diagrid
claude plugin install diagrid@diagrid
claude plugin details diagrid@diagrid  # expect 12 skills
```

Why this happens, how to fix `dapr-skills` the same way, and the installer pitfalls for
the other clients are in [docs/troubleshooting.md](docs/troubleshooting.md).

## Feedback

The most useful thing you can report is **a skill that didn't fire when it should have**,
with the exact wording you used. That failure is invisible from our side — it looks
identical to a session where nothing relevant happened — and the wording is the whole
diagnosis.

Also worth reporting, in rough order of value:

1. A tool a skill named that **didn't exist or didn't work**. Every `diagrid_*` name is
   checked in CI against `contracts/diagrid-mcp-tools.txt`, so a mismatch means the
   server changed or the check has a hole. Both are worth catching.
2. A skill that fired when a **different** one should have.
3. Anything a skill told you that turned out to be wrong.

Open an issue on this repository.

For a security problem, don't open an issue. See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the checks every pull request runs and the
version bump a skill change needs.

## License

Apache-2.0. See [LICENSE](LICENSE).
