# catalyst-ai

Build and operate [Diagrid Catalyst](https://diagrid.io) by prompting — Dapr Workflows,
Durable Agents, and the running system.

**Verified end to end in Claude Code** — installs in under 5 seconds, all 10 skills
register, and a real Catalyst question fires the right skill and gets a grounded answer.
In **Codex** and **GitHub Copilot** the install and all 10 skills are verified, and Codex
is confirmed to put them in front of the model; neither has yet answered a Catalyst
question here, for reasons that are
[nothing to do with the skills](#what-is-and-is-not-verified-per-client).

> **Early release.** Read [What works today](#what-works-today) before you start: the
> MCP server is new, and building and deploying still need the `diagrid` CLI.

## Install

### Claude Code

```bash
claude plugin marketplace add diagridio/catalyst-ai
claude plugin install catalyst-ai@diagrid
```

Then check it landed — **both commands, not just the second**:

```bash
claude plugin list                           # expect Version: 0.3.2 or later
claude plugin details catalyst-ai@diagrid    # expect 10 skills
```

`list` reports the version you actually have. `details` reports the version the
marketplace is offering, reading the installed copy only when the two agree — so on its
own it can show you 10 skills while your session loads 9. If either looks wrong, jump to
[If your install is behind](#if-your-install-is-behind).

#### Then sign in to the Catalyst MCP server

The plugin also registers the Catalyst MCP server, `https://mcp.cloud.r1.diagrid.io/mcp`.
It stays empty until you sign in once. In Claude Code, run `/mcp`, pick `plugin:catalyst-ai:catalyst` and complete the
browser sign-in. There is no API key and no `diagrid login` involved in this step.

If you already added the server yourself with `claude mcp add`, remove that entry
(`claude mcp remove catalyst --scope user`) once the plugin is installed. Otherwise you
have two copies of every Catalyst tool.

To point the plugin at a different Catalyst environment, set `DIAGRID_MCP_URL` before
starting Claude Code and sign in again. A sign-in only works against the environment it
was made for.

Other clients (Copilot, Codex and so on) don't read `plugin.json`. Add
`https://mcp.cloud.r1.diagrid.io/mcp` as a remote (streamable HTTP) MCP server in that
client's own MCP setup; it signs in with OAuth in the browser, with no API key. The plugin
requests the scopes `catalyst:read offline_access`; if your client lets you set scopes,
request the same. Without `offline_access` there is no refresh token, so you sign in
again each time the session expires.

### GitHub Copilot (and Gemini CLI, Zed, Antigravity)

```bash
npx skills add diagridio/catalyst-ai -a github-copilot
```

Use **repeated `-a` flags** if you pass more than one. The comma form
(`-a codex,github-copilot`) is what the upstream README documents, and it prints
`Invalid agents:`, installs nothing and exits **1** — so it fails honestly, and a step
checking the exit code catches it. Re-measured on 1.5.22 and 1.5.23; an earlier version
of this line claimed exit 0, which was a measurement error.

The failure that *is* silent is a missing `-y` where nothing can answer the prompt, which
is every CI runner: it prints `Done!`, installs zero skills, and exits **0**. Pass `-y`,
and assert a skill count rather than an exit code.

This writes all ten skills to `.agents/skills/`, and Copilot's own listing confirms it
reads them:

```bash
copilot skill list        # all 10 under "Project skills"
```

Copilot looks for project skills in `.github/skills/`, `.agents/skills/` and
`.claude/skills/`, so one directory covers it. Don't rely on `npx skills list` for this —
its "Agents:" line only names agents it detects as **installed on your machine**, so it
will quietly leave out a client you haven't installed yet.

### Codex

```bash
npx skills add diagridio/catalyst-ai -a codex
```

`.agents/skills/` is Codex's project skills directory too — the installer maps `codex`
there by design, so seeing no `.codex/` created is correct rather than a failed install.
Codex reads them: `codex debug prompt-input` renders the model-visible prompt, and all ten
appear in its `<skills_instructions>` block with their descriptions intact, byte for byte.
Codex's own guidance text says automatic skill selection is allowed by default, so you
shouldn't have to name a skill — though nobody has yet confirmed that from a real session.

Earlier versions of this README warned that Codex might not work, on the strength of
`npx skills list` omitting Codex. That turned out to mean only that Codex wasn't installed
on the machine doing the checking. Details in
[docs/cold-start-measurement.md](docs/cold-start-measurement.md).

### What is and is not verified, per client

| | skills install | skills register | a question answered |
| --- | --- | --- | --- |
| Claude Code 2.1.241 | ✅ 4.7 s | ✅ 10/10 | ✅ right skill fires unprompted, grounded answer |
| Codex 0.149.0 | ✅ 2.0 s | ✅ 10/10, in the model-visible prompt | ⛔ needs a ChatGPT/OpenAI credential we don't have |
| GitHub Copilot 1.0.80 | ✅ 2.0 s | ✅ 10/10 | ⛔ `copilot -p` gets HTTP 403 *not authorized to use this Copilot feature* on the account we tried — nothing to do with the skills |

If you can get Codex or Copilot to answer a Catalyst question, **that is the single most
useful thing you can report** — with the wording you used and which skill fired. A skill
that never fires looks identical to a session where nothing relevant came up, which is why
this needs a human rather than an installer's exit code.

## Then just ask

The point is that you don't learn commands. Try:

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
| `catalyst-agent-scaffold` | Stand up a Durable Agent as your own app behind an App ID |
| `catalyst-develop` | The edit → rerun → observe loop against live Catalyst infrastructure |
| `catalyst-deploy` | Move an application from your laptop into Catalyst |
| `catalyst-operate` | Inspect a running project, read-only |
| `catalyst-debug` | Diagnose why something isn't working |
| `catalyst-workflow-determinism` | Replay-safety rails for an orchestrator body |
| `catalyst-activity-idempotency` | Make activities safe to run twice |

Language and framework are **detected, not asked**. There is no `catalyst-workflow-python`
skill — the workflow skill reads your repo and works out that it's a Python project.

**Cost:** roughly **1030 tokens always-on** across all ten (~103 each), added to every
session whether or not a skill fires. Each skill costs a few thousand more only when it
actually fires. That figure is **per model** — `claude plugin details` resolves a tokenizer
from your active model, so the same ten descriptions cost ~103 each on Sonnet 5 and Opus 5
and ~68 each on Haiku 4.5. Quote the model with the number or it isn't reproducible.

## What works today

Being explicit, because the gap matters and you'll notice it:

| | status |
| --- | --- |
| Authoring — workflows, agents, the local dev loop | ✅ works now |
| Operating — inspect, debug, read logs and runs | ✅ works now, via the MCP server or the CLI |
| Determinism and idempotency review | ✅ works now |
| **The Catalyst MCP server** | 🆕 **registered by the plugin in Claude Code** — reads for everyone; writes for roles that allow them |
| Creating, changing, deleting and deploying resources | ✅ works now, via the MCP server for a role that can write, or the CLI |

Once you've signed in, the skills can inspect a project without the CLI. If your role in
the organization allows writes, the MCP server can also create, change and delete
resources, deploy an application, run workflow-run actions and manage access; a
read-only role sees only the read tools. It can never run your app locally, so the local
dev loop still goes through the **`diagrid` CLI**, and the skills say which path
they're taking.

**For the local dev loop, and whenever an MCP tool isn't available to you, you need a
working `diagrid` CLI**, logged in:

```bash
diagrid login
diagrid project list
```

If the second command works, you're ready. Every command in these skills is verified in CI
against the CLI release pinned in `.diagrid-cli-version`, currently **v1.66.0** — so that's
the version to be on. Several flags moved between 1.51 and 1.66, and nothing here is
checked against anything older.

## Things the skills know that you might not

These are in the skills already; listed here because they're the ones that cost people
hours, and they all fail *silently* or with an unhelpful error.

- **Don't create a project.** Your org already has a `default` project, provisioned at
  signup, with managed pub/sub, KV, workflow store and agent infrastructure. Free plans
  allow **3 projects per region**, and `dev run` will **create one if you typo
  `--project`** — spending a slot without asking.
- **One pub/sub and one KV store per project, on every plan**, free and paid alike, so
  no plan upgrade buys a second one. A
  multi-agent topology shares one pub/sub across topics. These are plan values overlaid
  per organization rather than constants in the code, so the skills read the live quota
  instead of asserting the 1.
- **`diagrid agent` fronts *your* app.** It takes `--endpoint` and the `--archive-*`
  flags, not model flags — looking for an LLM flag means you have the wrong resource.
- **Enable the managed workflow store *before* the App ID exists.** The sidecar reads
  workflow config at boot, so enabling it later leaves `FAILED_PRECONDITION` on a sidecar
  that never gets retrofitted.
- **An Agent or MCP server must precede any bare App ID of its name.** The Agent
  controller won't adopt a name it doesn't own, and the Agent stays in error permanently.
- **App IDs are counted org-wide per region**, and Apps, Agents and MCP servers all
  consume the same allowance — so splitting a topology across projects buys nothing.
- **Absent is not empty.** At the default `metadata` data-sharing level, workflow `input`,
  `output` and `customStatus` are *withheld*, not empty. A run that shows no output may
  have produced plenty.
- **The scaffolded dev file holds a live API token per App ID.** Gitignore it before you
  run anything.

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
claude plugin list                           # expect Version: 0.3.2 or later
```

**Your version is right but skills are missing.** Claude Code caches a plugin under its
declared version at `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and **will
not refresh a version directory it already has**. Measured: a half-populated version
directory served 4 skills of 10, while both `marketplace update` and `plugin install`
reported success and repaired nothing. Deleting the directory is the only fix:

```bash
rm -rf ~/.claude/plugins/cache/diagrid/catalyst-ai
claude plugin install catalyst-ai@diagrid
claude plugin details catalyst-ai@diagrid    # expect 10 skills
```

CI now fails any change to plugin content that doesn't bump the version, so the second one
shouldn't recur.

## Feedback

The most useful thing you can report is **a skill that didn't fire when it should have**,
with the exact wording you used. That failure is invisible from our side — it looks
identical to a session where nothing relevant happened — and the wording is the whole
diagnosis.

Also worth reporting, in rough order of value:

1. A command or flag a skill emitted that **didn't work**. Every one is checked in CI
   against the CLI release pinned in `.diagrid-cli-version`, so a mismatch means either
   you are on a different version or the check has a hole. Both are worth catching.
2. A skill that fired when a **different** one should have.
3. Anything a skill told you that turned out to be wrong.

Open an issue on this repository.

## Contributing

Three gates run on every PR, each with its own test suite, and each exists because
something got past review or past `claude plugin validate --strict` in practice:

```bash
python3 scripts/lint_skills.py            # the real gate
python3 scripts/test_lint_skills.py       # proves the gate still catches what it claims
python3 scripts/check_cli_surface.py      # every diagrid command, against the pinned CLI
python3 scripts/test_check_cli_surface.py
python3 scripts/check_version_bump.py     # a plugin change must bump the version
python3 scripts/test_check_version_bump.py
```

`lint_skills.py` enforces what a client actually needs: `name` matching its directory, a
parseable description under 260 characters, a frontmatter allow-list, no `../` links, every
link resolving when the skill is installed *alone*, and a **0.20 similarity cap between any
two descriptions** so skills don't compete for the same trigger. It also bans a list of
substrings that each shipped somewhere and broke.

`check_cli_surface.py` downloads the CLI release pinned in `.diagrid-cli-version`, verifies
it by sha256, and checks every `diagrid …` command in every skill against it: the command
path exists, every long flag and shorthand exists, and no invocation omits a flag the CLI
marks **required**. That last one is the reason it exists. A banned-substring list cannot
express "this flag is spelled correctly and is required" — `--help` does not render
required-ness at all, so `-i, --instance-id string   Instance ID of the workflow` reads as
optional on the page and fails at parse time in a terminal. It is also honest about what it
cannot see, and prints that list on every run: MCP tool names, console routes, package
coordinates and quota numbers are not in the CLI.

One wrinkle worth knowing, because it decides what CI can prove. CI has no `diagrid login`,
and a few hidden command paths resolve only for some logins, while `appid` and
`tokenbudget` are hidden and resolve for anyone. Those paths are declared in
`[identity_gated]` in `.diagrid-cli-version`, and the gate names their invocations as
**unverifiable** instead of reporting them absent. Run
the gate locally on a login that can see them and they are checked in full, flags and required flags
included; the pass/fail verdict is the same either way. Reporting a working command as
nonexistent would be the worst outcome available here — the fix it invites is deleting
correct content from a skill.

The same environment split runs the other way for required flags, so **a green run on your
machine does not guarantee a green run in CI**. Some requirements are applied from local
config: `dev stop` requires `--project` when no default project is configured and does not
when one is, from the same binary. CI is unconfigured, so it sees the strictest set — which
is also the set a brand-new user meets. Treat CI as authoritative and write the flag in.

Bumping the pinned CLI is a deliberate edit to `.diagrid-cli-version` — version and all
four checksums. Expect the gate to fail on whatever the new release moved; that failure is
the point, so fix the skill rather than the gate.

If you add a skill, bump `version` in `.claude-plugin/plugin.json`. Everyone who already
installed keeps the old content otherwise, and nothing tells them.
