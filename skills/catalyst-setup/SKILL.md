---
name: catalyst-setup
description: Connect this session to Diagrid Catalyst and confirm it works. Use when Catalyst tools are missing, a Catalyst call fails with an auth or organization error, the user is new to Catalyst, or they ask to log in, set up, or check their connection.
---

# Connect to Catalyst

Goal: end this skill able to name the user's organization and project, having made one
real read against Catalyst. Anything less is not connected, however healthy it looks.

## 1. Establish what is already true

Do not start by installing or logging in. Start by finding out, because most sessions
are already most of the way there and a redundant login is the fastest way to make a
working setup stop working.

Check in this order and stop at the first that answers:

1. **Are Catalyst MCP tools available?** If tools named `catalyst_*` are listed, the
   connection exists. Call `catalyst_whoami`. If it returns an organization, you are
   done — report the org and project and stop.
2. **Is the CLI present and logged in?** `diagrid version`, then
   `diagrid project list`. If that returns projects, the CLI path works and you can
   answer questions today even with no MCP tools. `version` is a subcommand, not a
   flag — there is no `--version` on the root command, and reaching for one fails
   with `unknown flag` before you learn anything. Compare what `version` prints against
   the floor in section 2 while you are here; it costs nothing, and it is the check that
   explains most "this command does not exist" surprises later.
3. Otherwise continue below.

## 2. The CLI version floor

These skills are written against **`diagrid` CLI v1.66.0**. Every command and flag they
quote was verified against that release.

`diagrid version` prints the installed one. If it is older than the floor, the remedy is a
single command, and it is the whole fix:

```
diagrid update --approve
```

Run that check *before* concluding a skill is wrong. Below the floor, commands and flags
these skills document may genuinely not exist yet, and the natural inference is backwards:
the binary is the thing you just ran successfully, so the document looks like the
unreliable party. Usually it is the binary that is behind.

Above the floor, keep confirming commands against `--help` before you run them — a CLI
newer than the floor can still have moved on. The ordering is the part that matters:
**compare the version against the floor first, and only then treat a rejected flag as
documentation drift.** Reversing those two turns a one-command fix into a rewrite of
something that was already correct.

## 3. Know which environment you are in

Diagrid runs several environments, and they are separate worlds: different API host,
different auth issuer, different console, different credentials. Getting this wrong looks
like a permissions problem and is not one.

- **`DIAGRID_URL` is the switch.** `diagrid login` has no `--api-url` flag; set
  `DIAGRID_URL` before `diagrid login` to point the CLI at another environment. (A hidden
  `--api` flag on `login` sets the same value. It is a development affordance, not the
  supported route — use `DIAGRID_URL`.)
- **`GET <api-host>/cli.envs.json` is the authoritative descriptor** for any environment.
  It returns `apiUrl`, `issuerUrl` and `authClientId`. Read it rather than inferring an
  environment from a hostname.
- **Production is `api.r1.diagrid.io`.** `api.diagrid.io` does not resolve at all — the
  `r1` is load-bearing, and it is the name everyone guesses first.
- **The auth issuer differs per environment**, so these are genuinely separate credentials
  rather than one account with several views.
- **Never derive or hardcode the console host — run `diagrid web`,** which opens the
  console for the environment you are actually logged in to. When you need the URL rather
  than a browser, the CLI maps the API host onto `catalyst.<env>`: `staging.diagrid.dev` →
  `catalyst.staging.diagrid.dev`, `.stg.diagrid.io` → `catalyst.stg.diagrid.io`,
  `.dev.diagrid.io` → `catalyst.dev.diagrid.io`, `.local.diagrid.io` **or a
  `.7f000001.nip.io` loopback host** → `catalyst.local.diagrid.io`, and everything else →
  `catalyst.diagrid.io`. Do not drop the nip.io branch when you compute this by hand:
  `7f000001` is hex for `127.0.0.1` and it is how onebox and self-hosted clusters are
  addressed, so missing it sends a self-hosted user to the **production** console.

**Say the cost before you switch, not after.** The CLI stores one login at a time, so a
login against another environment replaces the one you had, and returning to it is another
interactive login. That is worth a sentence to the user in advance.

## 4. Read the error, do not guess

Every Catalyst refusal names its own kind and carries an instruction addressed to you.
Act on the instruction rather than improvising — improvising here usually means asking
the user for an API key, which is never the right next step.

| Kind | What it means | Do |
| --- | --- | --- |
| `NOT_AUTHENTICATED` | No credential, or it does not verify | The client's own auth flow handles this. Do not ask the user for a credential. If the client has not prompted, say so and stop. |
| `NO_ORG` | Verified, but no organization resolved | Ask the user which organization, or run `diagrid org list`. |
| `ORG_MISMATCH` | A supplied org disagrees with the credential | Stop. Report both values. Do not retry with either. |
| `ORG_UNAVAILABLE` | Organization blocked or being deleted | Terminal. Tell the user to contact Diagrid support. Do not retry. |
| `CATALYST_NOT_ENABLED` | No Catalyst entitlement, or an expired trial | Report which. These need different remedies — enabling versus renewing. |

If a refusal is marked retryable, wait briefly and retry once. If it is not, do not
retry at all: a permanent refusal retried looks to the user like a hang.

## 5. Confirm, out loud

Report three things, from a real call and not from configuration:

- the organization, by name
- the project you will work in
- how you are reaching Catalyst — MCP tools or the CLI

If any of the three is unknown, say which, and say what you tried. A confident
"connected!" that turns out to be wrong costs more than an honest "the CLI works but
MCP tools are absent".

## Rules

- **Never ask the user to paste a credential of any kind.** If one is needed, the
  client's auth flow is what supplies it.
- **Do not create a project.** Every organization gets a project named `default`
  with managed pub/sub, KV, workflow store and agent infrastructure already attached.
  Use it. A hand-made project that behaves differently is indistinguishable from a
  broken one to the person asking for help.
- **Do not install the CLI without asking.** Downloading a binary is a side effect the
  user consents to once, not something to do mid-answer.
- **Check the version before blaming the docs.** A rejected flag is a version question
  first and a documentation question second.
- **Name the proof.** This skill is done when `catalyst_whoami` or `diagrid project list`
  has actually returned something, and you have said which one it was. Configuration that
  looks right is not proof, and that is the failure this ordering exists to prevent.
