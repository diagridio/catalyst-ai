# catalyst-ai

Build and operate [Diagrid Catalyst](https://diagrid.io) by prompting — Dapr Workflows,
Durable Agents, and the running system.

**Verified working in Claude Code** (9 skills registered) **and GitHub Copilot**. Codex is
[not yet verified](#-codex-not-verified-and-the-installers-own-report-disagrees-with-itself).

> **Internal preview.** This is the first internal rollout. Read
> [What works today](#what-works-today) before you start, because one significant piece
> is deliberately not in it yet.

## Install

### Claude Code

```bash
claude plugin marketplace add diagridio/catalyst-ai
claude plugin install catalyst-ai@diagrid
```

Then check it landed:

```bash
claude plugin details catalyst-ai@diagrid
```

You should see **9 skills**. If you see fewer, jump to
[If you installed an early version](#if-you-installed-an-early-version).

**This repo is still private**, so the install clones over SSH
(`git@github.com:diagridio/catalyst-ai.git`). You need an SSH key that can read
`diagridio` — if `ssh -T git@github.com` greets you by name, you're set. That requirement
disappears when the repo goes public.

### GitHub Copilot (and Gemini CLI, Zed, Antigravity)

```bash
npx skills add diagridio/catalyst-ai -a github-copilot
```

Use **repeated `-a` flags** if you pass more than one. The comma form
(`-a codex,github-copilot`) is what the upstream README documents and it silently installs
nothing — verified, not assumed.

This writes all nine skills to `.agents/skills/`, the shared location that Copilot reads.
`npx skills list` confirms them as available to **Antigravity, Gemini CLI, GitHub Copilot
and Zed**.

### ⚠️ Codex: not verified, and the installer's own report disagrees with itself

**We cannot currently say Codex works, so don't assume it does.** Tested on `skills`
1.5.23 against this repo:

| | |
| --- | --- |
| `npx skills add … -a codex` prints | `copy → Codex` for every skill |
| directories created | `.agents/skills/` only — **no `.codex/`** |
| `npx skills list` reports | Antigravity, Gemini CLI, GitHub Copilot, Zed — **Codex absent** |

So the installer claims success, creates nothing Codex-specific, and its own listing
doesn't count Codex as wired up. It's possible Codex reads `.agents/skills/` anyway and
only the listing is incomplete — but nobody has run Codex against these skills to find
out, and "the install said OK" is exactly the evidence that has been wrong before here.

If you use Codex, please try it and tell us what happens. A skill that never fires looks
identical to a session where nothing relevant came up, which is why this needs a human to
confirm rather than an installer's exit code.

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
| `catalyst-agent-scaffold` | Stand up a Durable Agent, Catalyst-hosted or your own app |
| `catalyst-develop` | The edit → rerun → observe loop against live Catalyst infrastructure |
| `catalyst-deploy` | Move an application from your laptop into Catalyst |
| `catalyst-operate` | Inspect a running project, read-only |
| `catalyst-debug` | Diagnose why something isn't working |
| `catalyst-workflow-determinism` | Replay-safety rails for an orchestrator body |
| `catalyst-activity-idempotency` | Make activities safe to run twice |

Language and framework are **detected, not asked**. There is no `catalyst-workflow-python`
skill — the workflow skill reads your repo and works out that it's a Python project.

**Cost:** roughly **930 tokens always-on** across all nine (~103 each), added to every
session whether or not a skill fires. Each skill costs a few thousand more only when it
actually fires.

## What works today

Being explicit, because the gap matters and you'll notice it:

| | status |
| --- | --- |
| Authoring — workflows, agents, the local dev loop | ✅ works now |
| Operating — inspect, debug, read logs and runs | ✅ works now, via the CLI |
| Determinism and idempotency review | ✅ works now |
| **The Catalyst MCP server** | ❌ **not yet** |

So today the skills drive the **`diagrid` CLI**. They know the commands, the flag names,
the ordering constraints and the traps — but they're shelling out, not calling a typed API.

The MCP server is close and lands separately. It's not here yet because the OAuth
authorization server it needs is a multi-week component
([CAT-1728](https://linear.app/diagrid/issue/CAT-1728)), and rather than block on that
we're shipping a local stdio path — `diagrid mcp serve`, running in-process with your
existing CLI credentials, no deployment
([CAT-1731](https://linear.app/diagrid/issue/CAT-1731)).

**You need a working `diagrid` CLI**, logged in:

```bash
diagrid login
diagrid project list
```

If the second command works, you're ready. The skills assume CLI **v1.63.0 or later** —
several flags moved between 1.51 and 1.63, and every command in these skills is pinned to
1.63.0 behaviour.

## Things the skills know that you might not

These are in the skills already; listed here because they're the ones that cost people
hours, and they all fail *silently* or with an unhelpful error.

- **Don't create a project.** Your org already has a `default` project, provisioned at
  signup, with managed pub/sub, KV, workflow store and agent infrastructure. Free plans
  allow **3 projects per region**, and `dev run` will **create one if you typo
  `--project`** — spending a slot without asking.
- **One pub/sub and one KV store per project, on every plan.** `cra:free`,
  `cra:enterprise` and `cra:internal` alike. This is architectural, not a free-tier limit
  — paying does not raise it. A multi-agent topology shares one pub/sub across topics.
- **`diagrid agent` and `diagrid managed-agent` are different resources.** `agent` fronts
  *your* app; `managed-agent` is Catalyst-hosted and takes the LLM flags. "Create an
  agent" unqualified picks the wrong one.
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

## If you installed an early version

`claude plugin details` showing fewer than 9 skills means you have a stale cache.

Claude Code caches a plugin under its declared version at
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and **will not refresh a
version directory it already has** — `marketplace update` reports success and changes
nothing. If you installed while the version was `0.1.0`, you're pinned to whatever it held
then.

```bash
rm -rf ~/.claude/plugins/cache/diagrid/catalyst-ai
claude plugin marketplace update diagrid
claude plugin details catalyst-ai@diagrid    # expect 9 skills
```

CI now fails any change to plugin content that doesn't bump the version, so this shouldn't
recur.

## Feedback

The most useful thing you can report is **a skill that didn't fire when it should have**,
with the exact wording you used. That failure is invisible from our side — it looks
identical to a session where nothing relevant happened — and the wording is the whole
diagnosis.

Also worth reporting, in rough order of value:

1. A command or flag a skill emitted that **didn't work**. Every one is pinned to CLI
   v1.63.0, so a mismatch means either drift or a mistake, and both are worth catching.
2. A skill that fired when a **different** one should have.
3. Anything a skill told you that turned out to be wrong.

File in Linear against the *AI-Native Catalyst* project, or post in
`#catalyst-discussions`.

## Contributing

Four gates run on every PR, and each one exists because something got past
`claude plugin validate --strict` in practice:

```bash
python3 scripts/lint_skills.py            # the real gate
python3 scripts/test_lint_skills.py       # proves the gate still catches what it claims
python3 scripts/check_version_bump.py     # a plugin change must bump the version
python3 scripts/test_check_version_bump.py
```

`lint_skills.py` enforces what a client actually needs: `name` matching its directory, a
parseable description under 260 characters, a frontmatter allow-list, no `../` links, every
link resolving when the skill is installed *alone*, and a **0.20 similarity cap between any
two descriptions** so skills don't compete for the same trigger.

If you add a skill, bump `version` in `.claude-plugin/plugin.json`. Everyone who already
installed keeps the old content otherwise, and nothing tells them.
