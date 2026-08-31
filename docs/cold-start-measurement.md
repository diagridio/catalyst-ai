# Cold start and warm start, measured in all three clients

The last open exit criterion on
[CAT-1730](https://linear.app/diagrid/issue/CAT-1730) — *cold start < 10 min, warm
start < 2 min, in all three clients* — had never been measured. This is the
measurement, taken against `main` at **0.3.2** (commit `0bb2d6f`), 10 skills.

> **Why `docs/`.** The repo had no convention for a document that is neither the
> rollout README nor a gate. One directory, one file per measurement or finding,
> named for what it measured. Nothing here is read by a client or a gate, so it
> is exempt from `check_version_bump.py` (`VERSIONED_PREFIXES` is `skills/` and
> `.claude-plugin/` only) — verified, not assumed.

## Verdict

| client | install + registration | first grounded answer | criterion |
| --- | --- | --- | --- |
| **Claude Code** 2.1.241 | ✅ 4.7 s skills (client already present), 10/10 skills | ✅ 21.5 s / 69.5 s / 166.1 s (3 samples) | **cold met**; **warm met on 2 of 3**, missed on the third |
| **Codex** 0.149.0 | ✅ 7.9 s (5.9 client + 2.0 skills), 10/10 ingested | ⛔ not measurable here — no credential | **unmeasurable**, no evidence of failure |
| **GitHub Copilot** 1.0.80 | ✅ 48.3 s (46.3 client + 2.0 skills), 10/10 enumerated | ⛔ HTTP 403, *not authorized to use this Copilot feature* | **unmeasurable**, blocked upstream of us |

**Cold start is met in Claude Code and unmeasurable in Codex and Copilot** — in
both of those because the client cannot be authenticated from this machine, not
because anything in this repo is broken. In both, the skills demonstrably reach
the model's context; what is unproven is only the answer that follows.

**Warm start is met for a scoped question and missed for a broad one.** With the
install already done, warm start *is* answer latency and nothing else, and the
three samples were 21.5 s, 69.5 s and **166.1 s** — the last of those is 2.8 min,
over the 2-minute bar. Calling that "met" would be picking the two samples that
suit. The variable is how much ground the question covers, not anything the repo
controls.

The headline correction: **the README's warning that Codex might not work was
wrong.** All three observations behind it are now explained and all three are
benign, and Codex demonstrably puts all ten skills in front of the model — which
is not the same as Codex having answered a question here, and this document
keeps those two apart. Conversely the README's claim that Copilot is *verified
working* was too strong: nobody has had Copilot answer a Catalyst question, and
on this account nobody can.

## What these numbers exclude

A stopwatch figure without its boundary is worse than no figure, so:

**Measured** — wall clock for each install command; whether the skills register
and how many; whether a real Catalyst question triggers the right skill and gets
a grounded answer; the answer's end-to-end latency.

**Not measured, and not estimated:**

- Installing the client itself for Claude Code (already present on this machine).
- `claude login`, `diagrid login`, `codex login`, `copilot login` — every one is
  an interactive browser round trip. None can be timed non-interactively and
  none is invented here.
- Installing the `diagrid` CLI (present at v1.66.0, logged in to production).
- Human reading, typing and thinking time. The README is ~300 lines; a colleague
  reads some fraction of it. That is not simulated.

So for Claude Code the measured path — install plus first answer — is **26 s to
2.8 min** against a 10-minute cold bar, leaving ~7 minutes of headroom for the
excluded steps. Two browser OAuth logins and skimming a 300-line README would
have to consume that whole margin to breach the criterion.

**On which clock.** Two numbers exist for each answer and they differ: the
session's own `duration_ms`, recorded in the transcript, and the shell's wall
clock — Q1 21.5 s / 22.6 s, Q2 69.5 s / 75.9 s, Q3 166.1 s / 168.1 s. Q2's 6.4 s
gap is mostly a harness artefact, that run having waited on stdin and logged *"no
stdin data received in 3s, proceeding without it"*, against 1.1 s and 2.1 s for
the other two. This document quotes `duration_ms`: it is the captured number and
it excludes the artefact. A human at a terminal feels the wall clock, a second or
two more.

## Method, and why it touched nothing

The trap named in CAT-1730 is that a "cold" install over an existing plugin
cache measures nothing. The obvious way to get a genuine cold start is to delete
the cache on the machine — which is state the user installed by hand. That was
avoided entirely:

- **Claude Code installs ran in an isolated `CLAUDE_CONFIG_DIR`** under a scratch
  path. Verified after the fact: `~/.claude/settings.json` unchanged (mtime
  11:23, before this session), `~/.claude/plugins/cache/diagrid/catalyst-ai/`
  still holding only `0.2.2`. Nothing was deleted from the real config.
- **The real question ran in the real config dir via `--plugin-dir <worktree>`**,
  which loads the 10-skill 0.3.2 plugin for one session without installing it,
  plus inline `--settings` disabling the installed 0.2.2 so only one copy of each
  skill was live.
- **Codex and Copilot ran in throwaway directories** with the client CLIs
  installed into scratch `npm --prefix` trees, never globally.
- **Every `diagrid` call went through a read-only shim** on `PATH` that logs each
  invocation and refuses mutating verbs (`create`, `delete`, `start`, `run`,
  `grant`, …). Across three sessions the skills issued **78 commands and the shim
  refused 0** — every command the skills chose was read-only on its own.

Two exceptions, recorded because they happened. A `--global` probe (finding #3)
created `~/.agents/` with ten skills in it, and running `codex --version` created
`~/.codex/` for a scratch file. Both were inventoried, copied and removed; `$HOME`
is back to the 76 entries it started with.

The pre-existing plugin state is recorded in
[`cold-start-environment-record.md`](./cold-start-environment-record.md).

## Claude Code — cold met, warm mostly met

```
claude plugin marketplace add diagridio/catalyst-ai     4.13 s
claude plugin install catalyst-ai@diagrid               0.59 s
                                          install total  4.72 s

claude plugin details catalyst-ai@diagrid               0.34 s   (the check, not the install)
```

The clone is over SSH (`git@github.com:diagridio/catalyst-ai.git`) because the
repo is private, and it worked on this machine's key with no prompt. A colleague
without read access to `diagridio` fails here — that requirement is real and the
README already states it.

Registration: **10 of 10 skills**, `gitCommitSha 0bb2d6f` matching `origin/main`.

Three real questions, each in a fresh non-interactive session, with the skills
loaded from the worktree and the read-only shim on `PATH`:

| question | `duration_ms` | wall clock | turns | `diagrid` calls | skill(s) that fired, unprompted |
| --- | --- | --- | --- | --- | --- |
| "Am I logged in to Catalyst, and which org and project am I pointed at?" | 21.5 s | 22.6 s | 6 | 3 | `catalyst-setup` |
| "Check whether this session is connected to Diagrid Catalyst, and then tell me what is in my default project." | 69.5 s | 75.9 s | 13 | 16 | `catalyst-setup` → `catalyst-operate` |
| "Is anything broken or failing in my Catalyst project right now?" | 166.1 s | 168.1 s | 16 | 59 | `catalyst-operate` |

The `diagrid` counts come from the shim's log rather than from counting command
strings in the transcript — two of the three runs used shell loops over the
project's resources, so the transcript shows 3, 13 and 26 command *strings* for
the same 3, 16 and 59 actual invocations.

**The right skill fired every time without being named**, which is the property
that cannot be checked from our side and the one the README asks people to
report on. The answers were grounded in live reads: org `engineering-shared`,
project `default` `ready`, 3 App IDs, 7 components, 9 workflow runs all
`completed`, and — correctly — that no `catalyst_*` MCP tools exist in the
session and everything came from the CLI.

One observation, not a defect: "is anything broken" fired `catalyst-operate`
rather than `catalyst-debug`. The answer was right, and the split is defensible
(`operate` reports state, `debug` diagnoses a known-broken resource), but it is
the boundary most likely to be reported as a mis-trigger.

## Codex — install and registration verified, answer not measurable

```
npm install @openai/codex          (scratch prefix)    5.88 s   → codex-cli 0.149.0
npx skills add diagridio/catalyst-ai -a codex          2.00 s   → 10 skills
                                                 total 7.88 s
```

The three unverified claims in the README are now all resolved, and the
pessimistic reading of each was wrong.

**1. `-a codex` prints `copy → Codex` and creates only `.agents/skills/`.** True,
and correct by design. In `skills` 1.5.23 the agent registry is explicit:

```js
codex: { name: "codex", displayName: "Codex", skillsDir: ".agents/skills",
         globalSkillsDir: join(codexHome, "skills"),
         detectInstalled: async () => existsSync(codexHome) || existsSync("/etc/codex") }
```

`.agents/skills` *is* Codex's project skills directory, shared with Copilot, Zed,
Gemini CLI and Antigravity. There is no `.codex/` to create for a project-scope
install.

**2. `npx skills list` omits Codex.** It omits Codex **because Codex is not
installed on this machine**, not because the install skipped it. The listing
filters to agents that `detectInstalled` finds, and Codex's check is whether
`$CODEX_HOME` (default `~/.codex`) exists. Proven by changing only that:

```
$ npx skills list                       # ~/.codex absent
  Agents: Antigravity, Gemini CLI, GitHub Copilot, Zed
$ CODEX_HOME=<existing scratch dir> npx skills list
  Agents: Antigravity, Codex, Gemini CLI, GitHub Copilot, Zed
```

There is a neat corollary. `~/.codex` gets created the first time you run `codex` at all —
`codex --version` is enough, before any login — so the listing starts naming Codex as soon
as anyone has actually run it. The README's evidence that "Codex is absent" was collected
on a machine where Codex had never been run once, which is the one condition guaranteed to
produce it.

**3. Does Codex actually ingest them?** Yes — and this is directly observable,
without a credential, because `codex debug prompt-input` renders the
model-visible prompt as JSON. All ten appear in a `developer` message:

```
<skills_instructions>
## Skills
...
### Available skills
- catalyst-activity-idempotency: Make Dapr Workflow activities safe to run twice. …
  (file: …/codex-test/.agents/skills/catalyst-activity-idempotency/SKILL.md)
```

Read from the project's `.agents/skills/`, exactly where `npx skills add` put
them. `codex features list` reports `skill_search` **stable/true** and `plugins`
**stable/true**. The binary also carries the guidance string *"Automatic skill
selection is allowed by default. Change that default only when the user
explicitly requests an explicit-only skill"* — that is Codex's own instruction
text, not something observed in this session's rendered prompt, so read it as
Codex's documented default rather than as a measurement. Nothing here is flagged
off.

### The description budget, measured against what Codex actually ingests

CAT-1730 sized the descriptions against a ~8,000-character Codex list budget
that *shortens descriptions first*, a shortened description being exactly what
stops implicit triggering. Measured:

| | chars |
| --- | --- |
| our 10 descriptions, as `lint_skills.py` counts them | 2433 |
| our 10 descriptions, as Codex ingested them | **2433 — byte-identical, all 10, no truncation** |
| Codex's own 5 bundled skills, same list | 1831 |
| the whole `<skills_instructions>` block including boilerplate | 8351 |

Two things follow. Our lint's budget number is the real number — it agrees with
the client byte for byte. And the 8,000-character shortening behaviour did
**not** occur: the block came to 8351 characters, over that figure, with every
description intact. At 12 skills (the cap this repo lints at) our share would be
2920 characters of a 4751-character list alongside Codex's bundled five. There
is room.

Also worth having on record: Codex ships five system skills of its own
(`imagegen`, `openai-docs`, `plugin-creator`, `skill-creator`,
`skill-installer`) that consume the same list. CAT-1730 budgeted as though ours
were the only entries.

### Frontmatter, checked against Codex's own validator

Codex ships a `SKILL.md` frontmatter validator, and its allow-list is literal in
the binary:

```python
allowed_properties = {"name", "description", "license", "allowed-tools", "metadata"}
unexpected_keys = set(frontmatter.keys()) - allowed_properties
```

Note what that is: **Python, from Codex's bundled skill-authoring tooling**, so it
governs creating and installing a skill rather than necessarily the loader that
reads `.agents/skills` at session start. The loader is on the Rust side — the
binary carries a `SkillFrontmatter` struct and the error *"missing YAML
frontmatter delimited by ---"* — and whether that rejects unknown keys was not
tested.

Which makes the empirical result the one that counts: all ten of our skills use
`{name, description}` and nothing else, and all ten were ingested. Nothing to fix.
The one adjacent rule seen in both places is that `disable-model-invocation` must
be false, which none of these skills sets.

### The boundary

`codex doctor` on this machine: *"auth — no Codex credentials were found."* No
`~/.codex`, no `OPENAI_API_KEY`. Asking Codex a Catalyst question needs a
ChatGPT or OpenAI credential that is not on this machine and that this
measurement did not go and obtain. **That is the whole of what is unproven for
Codex**: install, discovery, ingestion and byte-exact descriptions are all
verified; the model's reply is not.

## GitHub Copilot — registration verified, answering blocked by policy

```
npm install @github/copilot        (scratch prefix)   46.25 s   → 1.0.80
npx skills add diagridio/catalyst-ai -a github-copilot 2.00 s   → 10 skills
                                                total 48.25 s
```

`copilot skill list` — local, no credential needed — enumerates all ten under
**Project skills** with full descriptions, and documents its own discovery
order:

```
Project   .github/skills/, .agents/skills/, or .claude/skills/
Personal  ~/.copilot/skills/ or ~/.agents/skills/
```

So `.agents/skills/` is right for Copilot too, and the single committed
`skills/` tree plus one symlink covers all three clients as designed.

Then it stops. On screen:

```
$ GH_TOKEN=… copilot -p 'Reply with exactly: PONG'
Error: Access denied by policy settings (Request ID: …)
  • Your organization has restricted Copilot access
  • Your Copilot subscription does not include this feature
  • Required policies have not been enabled by your administrator
```

**That screen text is the CLI's generic 403 handler, and its three bullets are a
list of guesses, not a diagnosis.** The log says what actually happened:

```
[ERROR] Error loading models: Error: 403 "unauthorized: not authorized to use this Copilot feature\n"
```

and four lines above it, the CLI's own policy resolution:

```
[managedSettings] device MDM: no policy present on this device
[managedSettings] server policy: none for this account (404/empty) from https://github.com
[managedSettings] effective policy resolved: source=none, bypassDisabled=false, serverFetchFailed=false
[managedSettings] applied: no bypass restriction in force (managed policy absent)
```

So **no managed policy was found for this device or this account** — which points
at the account's Copilot entitlement not covering the CLI rather than at an org
policy blocking it. The honest statement is the 403 itself: *not authorized to use
this Copilot feature*. An earlier draft of this document asserted the org-policy
bullet as the cause; the log does not support it, and the distinction matters
because the two have different owners. Confirmed on a second run with
`--disable-builtin-mcps`, which produced the same 403 — so it is not the
third-party-MCP policy note that precedes it on screen.

Either way it is upstream of this repo, and it needs someone whose GitHub account
can use Copilot CLI to close.

The README's *"Verified working in … GitHub Copilot"* therefore overstates the
evidence and is corrected in this PR. Ten skills registering is not the same as
one question being answered.

## The comma form fails — loudly. Corrected.

**This section previously claimed the comma form exits 0, and that is wrong.**
Re-measured on both 1.5.22 and 1.5.23, from a clean temp directory each time:

```
$ npx skills add <source> -a codex,github-copilot -s '*' -y
■  Invalid agents: codex,github-copilot
$ echo $?
1                           # not 0
```

Exit **1**, nothing installed, on both versions — so it is not a version
difference and the original reading was a measurement error, most likely an exit
code taken through a pipe, where `$?` reports the last stage rather than `skills`.
Repeated `-a` flags remain the only correct form, but the wrong form fails
honestly and a CI step checking the exit code does catch it.

### The silent failure is a different one, and it is worse

What does exit 0 having installed nothing is a **missing `-y` where nothing can
answer the prompt** — which is every CI runner:

```
$ npx skills add <source> -a claude-code -s '*' < /dev/null
…
└  Done!  Review skills before use; they run with full agent permissions.
$ echo $?
0
$ ls .agents/skills | wc -l
0
```

It prints **`Done!`**, installs zero skills, and exits **0**. A step that trusts
either the exit code or the output sees a successful install of nothing. That is
why the installer gate added in #20 asserts a positive skill count derived from
the repo's own `skills/` directory, rather than checking the exit code — an exit
code cannot detect this and neither can reading the log.

## The token-cost figure depends on the model, not just the descriptions

CAT-1730 treats `claude plugin details`' always-on figure as the budget
instrument, having already been burned once by measuring it through a stale
cache. It moves for a second reason:

| where | version | always-on | per skill |
| --- | --- | --- | --- |
| real config, default model | 0.2.2, 9 skills | ~929 tok | ~103 |
| real config, `ANTHROPIC_MODEL=claude-sonnet-5` | 0.2.2, 9 skills | ~929 tok | ~103 |
| real config, `ANTHROPIC_MODEL=claude-opus-5` | 0.2.2, 9 skills | ~929 tok | ~103 |
| real config, `ANTHROPIC_MODEL=claude-haiku-4-5-20251001` | 0.2.2, 9 skills | ~614 tok | ~68 |
| fresh config, not logged in (any `ANTHROPIC_MODEL`) | 0.3.2, 10 skills | ~694 tok | ~69 |

The 9 shared descriptions are **byte-identical** between 0.2.2 and 0.3.2, so the
spread is the estimator, not the content: it resolves a tokenizer from the active
model, and a config that cannot resolve one falls back to the cheaper count. Both
readings sit inside the ~100/skill assumption the 12-skill cap was sized against,
so the cap holds either way — but the figure is only reproducible if you say
which model produced it.

**~1030 always-on for 10 skills on Sonnet 5 / Opus 5** is the number to quote. It
is arithmetic on a measured per-skill *average* — 929 tok over 9 byte-identical
descriptions in a logged-in config, whose own per-skill rows are ~100 and ~110
rather than a flat 103 — plus a 10th description of 246 characters sitting
mid-range — labelled as derived, because measuring it directly
would have meant installing 0.3.2 into the user's own config, which this
measurement declined to do.

## Three traps found

### 1. A partial version directory serves fewer skills, and neither repair command notices

The trap CAT-1730 names, reproduced on 2.1.241 at 0.3.2. Six of ten skill
directories removed from a cached version dir:

| step | skills reported |
| --- | --- |
| partial cache present | **4** |
| `claude plugin marketplace update diagrid` → `✔ Successfully updated` | **4** |
| `claude plugin install catalyst-ai@diagrid` → `✔ already installed` | **4** |
| `rm -rf` the version dir, then install | **10** |

Both repair commands report success and change nothing. The README's remedy —
delete the version directory — is the only one that works.

### 2. An install a few versions behind: `plugin list` and `plugin details` disagree

This is the state on the machine this was measured from, and it is **not** the
trap above. The marketplace clone is a git clone pinned at whatever commit it
last fetched; this one sits at `c7494c8` (#12), so both it and the cache hold a
self-consistent **0.2.2 with 9 skills** while `main` is 0.3.2 with 10. The
missing skill is `catalyst-workflow-from-diagram`, and the session running this
measurement had 9 catalyst skills available, confirming it.

Reproduced synthetically (cache at 0.2.2/9 skills, marketplace clone at 0.3.2):

```
claude plugin list      →  Version: 0.2.2                    ← the installed truth
claude plugin details   →  catalyst-ai 0.3.2  Skills (10)     ← the marketplace's offer
claude plugin install   →  "already installed"  (no change)
claude plugin update    →  "updated from 0.2.2 to 0.3.2"      0.55 s
```

So `plugin details` resolves the version the *marketplace* declares — reading the
cache dir if one exists for it, else the clone. When installed and marketplace
versions disagree it reports skills the session will not load. **The README's
verification step (`plugin details`, expect 10 skills) can therefore pass while
the session loads 9.** `claude plugin list` is the command that reports what is
installed, and `claude plugin update` — which the README never mentions — is the
fix, without any `rm -rf`.

### 3. `npx skills add … --global` writes to `~/.agents/skills`

Probing the global path with `-a codex --global` and `CODEX_HOME` pointed at a
scratch directory wrote ten skills into **`~/.agents/skills/`** with a
`.skill-lock.json` beside it in `~/.agents/`, and left `$CODEX_HOME/skills`
empty. The mechanism is in the installer: `ensureUniversalAgents()` appends every
agent whose `skillsDir` is `.agents/skills` to whatever you asked for, and one of
those — Zed — declares `globalSkillsDir: join(home, ".agents/skills")`. So naming
a single agent with `--global` writes that agent's *siblings'* global directory.
Anyone running `--global` should expect `$HOME` to be written whichever one agent
they named. Created and removed during this measurement.

## Corrections this produced

Applied to the README in the same PR:

1. Codex is no longer flagged as possibly-broken; the three observations behind
   that warning are explained, with the evidence.
2. Copilot's status drops from *verified working* to *skills registered; not yet
   answered*, quoting the 403 rather than guessing at its cause.
3. The verification step becomes `claude plugin list` for the version alongside
   `plugin details` for the inventory, because `details` alone can over-report.
4. `claude plugin update` is documented as the upgrade path, next to the existing
   `rm -rf` remedy for the different failure it actually fixes.
5. The token figure gets the model it was measured on.
6. `lint_skills.py` said `allowed-tools` and `model` were "Claude-Code-only", in
   both the rule's comment and its rejection message. Codex's own skill validator
   accepts `allowed-tools` and rejects `model`, so the two are not alike and
   neither is Claude-Code-only. The rule is unchanged — `{name, description}`
   only, which is the pair Codex demonstrably ingests — but the reason no longer
   claims something the measurement contradicts.

This document was itself fact-checked against the raw logs before merge, which
caught six claims measured but never captured to a file (the per-model token
figures, the installer registry, Codex's frontmatter allow-list) and one
over-reach (attributing Copilot's 403 to org policy, which its own log
contradicts). The uncaptured measurements were re-run and saved; the over-reach
is corrected above. Anything a re-run could not support was removed rather than
softened.

## Reproducing this

```bash
# Claude Code, cold, without touching your own config
export CLAUDE_CONFIG_DIR=$(mktemp -d)/.claude
claude plugin marketplace add diagridio/catalyst-ai
claude plugin install catalyst-ai@diagrid
claude plugin details catalyst-ai@diagrid      # expect 10 skills

# what Codex actually puts in front of the model
cd $(mktemp -d) && git init -q .
npx skills add diagridio/catalyst-ai -a codex
codex debug prompt-input | python3 -c 'import json,sys;print([c["text"] for m in json.load(sys.stdin) for c in m.get("content",[]) if "<skills_instructions>" in c.get("text","")][0])'

# what Copilot sees
npx skills add diagridio/catalyst-ai -a github-copilot
copilot skill list
```
