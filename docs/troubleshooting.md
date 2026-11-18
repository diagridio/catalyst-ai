# Troubleshooting

Detail behind the short fixes in the [README](../README.md).

## Claude Code: the install is behind

Start with `claude plugin list`. It reports the version you actually have.
`claude plugin details diagrid@diagrid` reports the version the marketplace is offering,
and reads the installed copy only when the two agree, so on its own it can show you 12
skills while your session loads fewer.

### Your version is older than `main`

The marketplace is a git clone pinned at whatever commit it last fetched, so an install
from last week stays on last week's version, with last week's skills.
`claude plugin install` does not move it: it reports "already installed" and changes
nothing.

```bash
claude plugin marketplace update diagrid
claude plugin update diagrid@diagrid   # the command that actually upgrades
claude plugin list                     # expect Version: 0.10.0 or later
```

### Your version is right but skills are missing

Claude Code caches a plugin under its declared version at
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and does not refresh a version
directory it already has. A half-populated version directory keeps serving only the
skills it holds, while both `marketplace update` and `plugin install` report success and
repair nothing. Deleting the directory is the only fix:

```bash
rm -rf ~/.claude/plugins/cache/diagrid/diagrid
claude plugin install diagrid@diagrid
claude plugin details diagrid@diagrid  # expect 12 skills
```

CI fails any change to plugin content that doesn't bump the version, so this should not
recur from a release of this plugin.

### The same for dapr-skills

Both fixes work the same way for the other plugin in this marketplace. Substitute
`dapr-skills@diagrid` and `~/.claude/plugins/cache/diagrid/dapr-skills`. The version it
reports is its own, set in its repository, not this one's.

## `npx skills add` installed nothing

- **Pass `-y`.** Where nothing can answer the installer's prompt, which is every CI
  runner, a run without `-y` prints `Done!`, installs zero skills and exits 0. In
  scripts, check the number of skills installed, not the exit code.
- **Repeat `--agent` for more than one client.** The comma form (`-a codex,github-copilot`)
  is read as one unknown agent name: it prints `Invalid agents:`, installs nothing and
  exits 1. Use `--agent codex --agent github-copilot`.
- **Don't rely on `npx skills list`.** Its "Agents:" line names only the agents it detects
  as installed on your machine, so it leaves out a client you haven't installed yet.

## Copilot sees no skills

With `--global`, the skills go to `~/.copilot/skills/`. That the installer writes this
directory is verified; that Copilot loads skills from it is not yet. If
`copilot skill list` shows none, install per project instead, from the repository root:

```bash
npx -y skills add diagridio/diagrid-ai --agent github-copilot --skill '*' --yes
```

Without `--global` the skills go into `.agents/skills/` under the folder you ran the
command in. Copilot reads project skills only at the root of the repository it is working
in, so an install from a subfolder leaves it with no skills and no error.

## Codex: checking the skills reach the model

The installer writes Codex's skills to `.agents/skills/`, its project skills directory,
and creates no `.codex/` directory. To confirm Codex reads them, run
`codex debug prompt-input`: it renders the model-visible prompt, and every skill appears
in its `<skills_instructions>` block with its description.

## Token cost

Every installed skill adds its description to every session, whether or not a skill
fires. Estimated at about 103 tokens a skill on Sonnet 5 and Opus 5, that is roughly
1,240 across all 12; on Haiku 4.5 it is about 68 a skill. A skill costs a few thousand tokens more only when it
fires.

The figure depends on the model. `claude plugin details` counts tokens with your active
model's tokenizer, so quote the model alongside any number you report.
