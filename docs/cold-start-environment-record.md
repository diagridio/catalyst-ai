# Environment record for the cold-start measurement

The audit trail for
[`cold-start-measurement.md`](./cold-start-measurement.md): what was on the
machine before, what the measurement touched, and the verification that it was
put back. Captured 2026-08-23, `claude` 2.1.241, `diagrid` 1.66.0.

No credential value is recorded here, and none was read.

## Claude Code plugin state, before

```
$ claude plugin list
  catalyst-ai@diagrid          Version: 0.2.2   Scope: user   ✔ enabled

$ claude plugin details catalyst-ai@diagrid
catalyst-ai 0.2.2
  Skills (9)  catalyst-activity-idempotency, catalyst-agent-scaffold,
              catalyst-debug, catalyst-deploy, catalyst-develop,
              catalyst-operate, catalyst-setup,
              catalyst-workflow-determinism, catalyst-workflow-scaffold
  Always-on:  ~929 tok
```

| | |
| --- | --- |
| marketplace registration | `diagrid` → `github:diagridio/catalyst-ai`, in `~/.claude/settings.json` under `extraKnownMarketplaces` |
| marketplace clone | `~/.claude/plugins/marketplaces/diagrid`, HEAD `c7494c85b8b538477ca1806f3c06ff7d166d266f` (#12), declaring `0.2.2`, 9 skill directories |
| cached versions | `~/.claude/plugins/cache/diagrid/catalyst-ai/` — `0.2.2` only |
| installed record | `installed_plugins.json`: version `0.2.2`, `gitCommitSha c7494c8…`, installed 2026-08-23T09:23:31Z, scope user |
| enabled | `~/.claude/settings.json` → `enabledPlugins["catalyst-ai@diagrid"] = true` |

Three version bumps behind `main` — 0.2.2 against 0.3.2, with 0.3.0 (#13) and
0.3.1 (#15) in between — and self-consistently so: clone, cache and record all
agree on 0.2.2. This is finding #2 in the measurement, not the stale-cache
trap — and it is why the session taking the measurement had 9 catalyst skills
available rather than 10.

## What the measurement touched

| | |
| --- | --- |
| `~/.claude/**` | **nothing.** Every Claude Code install ran under an isolated `CLAUDE_CONFIG_DIR` in a scratch path; the real question ran via `--plugin-dir` plus inline `--settings`, which installs nothing. |
| Codex / Copilot config | Skills installed into throwaway directories; both client CLIs installed into scratch `npm --prefix` trees, never globally. One slip: the second Copilot run was launched without `COPILOT_HOME`, so it wrote `config.json`, `logs/`, `session-store.db*` and one `session-state/` entry into the existing `~/.copilot`. All five were preserved to the evidence directory and removed; `~/.copilot` is back to the four entries it had (`ide`, `session-state` with its two pre-existing sessions, `vscode.session.metadata.cache.json`). |
| Catalyst (production) | **read only.** Every `diagrid` call went through a shim that refuses mutating verbs. 78 commands issued by the skills across three sessions, 0 refusals — nothing the skills chose to run was a write. |
| `$HOME` | two directories, both created by this measurement and both removed: `~/.agents/` from a `--global` probe (finding #3), and `~/.codex/` — which the Codex launcher creates for a scratch file the moment you run `codex --version`, before any login. |

## Verification, after

```
$ ls -la ~/.claude/settings.json
-rw-r--r--  5216  Aug 23 11:23        # mtime predates this session
$ ls ~/.claude/plugins/cache/diagrid/catalyst-ai/
0.2.2                                 # unchanged, no 0.3.2 created
$ claude plugin list | grep -A1 catalyst-ai
  catalyst-ai@diagrid
    Version: 0.2.2                     # unchanged
$ ls -a ~ | wc -l
76                                     # 76 before, 76 after; both probe dirs removed
$ ls -d ~/.agents ~/.codex
ls: no such file or directory          # as found
$ ls -a ~/.copilot
. .. ide session-state vscode.session.metadata.cache.json     # as found
```

Captured as `snapshot-after.txt` alongside the before-snapshot in the evidence
directory, so the two can be diffed rather than taken on trust.

## One thing for the owner of this machine to decide

The install is at 0.2.2 and `main` is 0.3.2, so this machine is missing
`catalyst-workflow-from-diagram` and the fixes in #14 and #15. It was left as it
was found, deliberately. Upgrading is two commands and under a second:

```bash
claude plugin marketplace update diagrid
claude plugin update catalyst-ai@diagrid
claude plugin list                       # expect Version: 0.3.2
```

`claude plugin install` will not do it — it reports "already installed" and
changes nothing.
