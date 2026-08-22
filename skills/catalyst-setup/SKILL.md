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
2. **Is the CLI present and logged in?** `diagrid --version`, then
   `diagrid project list`. If that returns projects, the CLI path works and you can
   answer questions today even with no MCP tools.
3. Otherwise continue below.

## 2. Read the error, do not guess

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

## 3. Confirm, out loud

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
