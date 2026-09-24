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

1. **Are Catalyst MCP tools available?** If `catalyst_*` tools are listed, the
   connection exists. Clients prefix them — in Claude Code they appear as
   `mcp__plugin_catalyst-ai_catalyst__catalyst_whoami` and so on — so match the ending.
   Call `catalyst_whoami`. If it returns an organization, you are done — report the org
   and project and stop.
2. **Is the server registered but not signed in?** In Claude Code, installing this
   plugin registers the Catalyst MCP server, listed as `plugin:catalyst-ai:catalyst`. Until the user signs in it
   contributes no tools, so it looks exactly like case 3 below. Ask the user to open
   `/mcp`, pick that server and complete the browser sign-in. That is the whole fix: you
   cannot do it for them, and there is nothing for them to paste. Tools appear once it
   finishes; then go back to step 1. If the user needs an answer before then, carry on to
   step 3 as well and give them the CLI command that answers it today.
3. **Is the CLI present and logged in?** `diagrid version`, then
   `diagrid project list`. If that returns projects, the CLI path works and you can
   answer questions today even with no MCP tools. `version` is a subcommand, not a
   flag — there is no `--version` on the root command, and reaching for one fails
   with `unknown flag` before you learn anything. Compare what `version` prints against
   the floor in section 2 while you are here; it costs nothing, and it is the check that
   explains most "this command does not exist" surprises later.
4. Otherwise continue below.

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

**The MCP server has its own host per environment, and its sign-in is separate from
the CLI's.**

| Environment | MCP server |
| --- | --- |
| Production | `https://mcp.cloud.r1.diagrid.io/mcp` |
| Staging | `https://mcp.cloud.staging.diagrid.dev/mcp` |

- **The plugin points at production.** Set `DIAGRID_MCP_URL` to another host before
  starting Claude Code to change that, then sign in again from `/mcp`.
- **A token only works on the host it was issued for.** Its audience is fixed at sign-in,
  so a staging token sent to production is refused as `NOT_AUTHENTICATED`. That reads like
  a permissions problem and is not one: check which host the server points at first.
- **Signed in to one does not mean signed in to the other.** `diagrid login` and the MCP
  sign-in are independent. A working CLI says nothing about the MCP server, and the
  reverse.
- **The tool list depends on the user's role.** Write tools, such as starting or
  terminating a workflow run, are left out of the list entirely for a user whose role
  cannot write. They are not refused when called — they are simply not there. If one is
  missing, that is the user's role, not a broken connection; do not go looking for it.

**Say the cost before you switch, not after.** The CLI stores one login at a time, so a
login against another environment replaces the one you had, and returning to it is another
interactive login. That is worth a sentence to the user in advance.

## 4. Read the error, do not guess

Every Catalyst refusal names its own kind and carries an instruction addressed to you.
Act on the instruction rather than improvising — improvising here usually means asking
the user for an API key, which is never the right next step.

| Kind | What it means | Do |
| --- | --- | --- |
| `NOT_AUTHENTICATED` | No credential, or it does not verify | The client's own auth flow handles this. Do not ask the user for a credential. If the client has not prompted, ask the user to sign in again from `/mcp`. If they just did, check the server points at the environment they meant (section 3). |
| `NO_ORG` | Verified, but no organization resolved | Ask the user which organization, or run `diagrid org list`. |
| `ORG_MISMATCH` | A supplied org disagrees with the credential | Stop. Report both values. Do not retry with either. |
| `ORG_UNAVAILABLE` | Organization blocked or being deleted | Terminal. Tell the user to contact Diagrid support. Do not retry. |
| `CATALYST_NOT_ENABLED` | No Catalyst entitlement, or an expired trial | Report which. These need different remedies — enabling versus renewing. |

Two things during sign-in look like errors and are not:

- **A `401` with `WWW-Authenticate: Bearer resource_metadata=...`** is how sign-in
  starts. The client follows that header to find the sign-in server. It is not a failure,
  and nothing needs fixing.
- **The consent screen.** Partway through sign-in, the browser asks the user to approve
  access for their organization. If they decline, sign-in stops and no tools appear. The
  fix is to sign in again from `/mcp` and approve.

If a refusal is marked retryable, wait briefly and retry once. If it is not, do not
retry at all: a permanent refusal retried looks to the user like a hang.

## 5. Confirm, out loud

Report three things, from a real call and not from configuration:

- the organization, by name
- the project you will work in
- how you are reaching Catalyst — MCP tools or the CLI — and, for MCP, which environment

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
