---
name: catalyst-setup
description: Connect this session to Diagrid Catalyst and confirm it works. Use when Catalyst tools are missing, a Catalyst call fails with an auth or organization error, the user is new to Catalyst, or they ask to sign in, set up, or check their connection.
---

# Connect to Catalyst

Goal: end this skill able to name the user's organization and project, having made one
real call to Catalyst. Anything less is not connected, however healthy it looks.

These skills drive Catalyst only through the Catalyst MCP server, the `catalyst_*` tools.
Setup is therefore two things: the server is added to the client, and the user has signed
in to it with the client's own OAuth flow. There is nothing to install and no separate
login command.

## 1. Check the connection first

Do not start by changing anything. Most sessions are already connected, and a redundant
sign-in is the fastest way to make a working setup stop working.

Call `catalyst_whoami`. Clients prefix tool names (in Claude Code it appears as
`mcp__plugin_catalyst-ai_catalyst__catalyst_whoami`), so match the ending.

- **It returns an organization.** Connected. Report the organization and the project you
  will work in, and stop.
- **The tool is not there, or it returns `NOT_AUTHENTICATED`.** The server is missing or
  not signed in. Go to section 2.

## 2. Add the server and sign in

The server is `https://mcp.cloud.r1.diagrid.io/mcp`, a remote (streamable HTTP) MCP
server. It signs in with OAuth in the browser. There is no API key and nothing for the
user to paste.

| Client | Do |
| --- | --- |
| Claude Code | Installing this plugin registers the server, listed as `plugin:catalyst-ai:catalyst`. Open `/mcp`, pick that server and complete the browser sign-in |
| Codex | `codex mcp add catalyst --url https://mcp.cloud.r1.diagrid.io/mcp`, then `codex mcp login catalyst` |
| GitHub Copilot CLI | `copilot mcp add --transport http catalyst https://mcp.cloud.r1.diagrid.io/mcp`, then run `/mcp` inside Copilot and authenticate the `catalyst` server in the browser |
| Anything else | Add the URL as a remote (streamable HTTP) MCP server in that client's own MCP setup, then use the client's MCP sign-in |

You cannot do the sign-in for the user. Ask them to do it, and once they say it is done,
call `catalyst_whoami` again. Tools appear when it finishes.

If the client lets you set scopes, request `catalyst:read offline_access`. Without
`offline_access` there is no refresh token, so the user signs in again each time the
session expires.

If the user already added the server by hand in Claude Code and also installed the
plugin, they have two copies of every tool. Ask them to remove their own entry.

## 3. Know what the connection depends on

- **The URL must be exact.** The `r1` in `mcp.cloud.r1.diagrid.io` is required; a URL
  without it does not resolve.
- **A token only works on the server it was issued for.** A token from another server is
  refused as `NOT_AUTHENTICATED`. If sign-in succeeded but calls are refused, check the
  server URL first.
- **The tool list depends on the user's role.** Write tools, such as `catalyst_apply`, or
  starting or terminating a workflow run, are left out of the list entirely for a user
  whose role cannot write. They are not refused when called; they are simply not there. If
  one is missing, that is the user's role, not a broken connection, so do not go looking
  for it. Tell the user a write role is needed and stop.

## 4. Read the error, do not guess

Every Catalyst refusal names its own kind and carries an instruction addressed to you.
Act on the instruction rather than improvising. Improvising here usually means asking the
user for an API key, which is never the right next step.

| Kind | What it means | Do |
| --- | --- | --- |
| `NOT_AUTHENTICATED` | No token, or it does not verify | Ask the user to sign in to the MCP server again (section 2). Do not ask for a token. If they just did, check the server URL (section 3) |
| `NO_ORG` | Verified, but no organization resolved | Ask the user which organization |
| `ORG_MISMATCH` | A supplied org disagrees with the sign-in | Stop. Report both values. Do not retry with either |
| `ORG_UNAVAILABLE` | Organization blocked or being deleted | Terminal. Tell the user to contact Diagrid support. Do not retry |
| `CATALYST_NOT_ENABLED` | No Catalyst entitlement, or an expired trial | Report which. These need different remedies, enabling versus renewing |

Two things during sign-in look like errors and are not:

- **A `401` with `WWW-Authenticate: Bearer resource_metadata=...`** is how sign-in starts.
  The client follows that header to find the sign-in server. Nothing needs fixing.
- **The consent screen.** Partway through sign-in the browser asks the user to approve
  access for their organization. If they decline, sign-in stops and no tools appear. The
  fix is to sign in again and approve.

If a refusal is marked retryable, wait briefly and retry once. If it is not, do not retry
at all: a permanent refusal retried looks to the user like a hang.

## 5. Confirm, out loud

Report three things, from a real call and not from configuration:

- the organization, by name
- the project you will work in
- the MCP server URL you are connected to

If any of the three is unknown, say which, and say what you tried. A confident
"connected!" that turns out to be wrong costs more than an honest "the server is added but
not signed in".

## What is not available over MCP yet

Some things have no `catalyst_*` tool. Say so in one line and do not improvise a route
around it: invoking an app, publishing to a topic, reading or writing state through
Catalyst, streaming inbound requests, and cluster diagnostics are not available over MCP
yet.

## Rules

- **Never ask the user to paste a token or key of any kind.** If one is needed, the
  client's sign-in flow supplies it.
- **Do not create a project.** Every organization gets a project named `default` with
  managed pub/sub, KV, workflow store and agent infrastructure already attached. Use it. A
  hand-made project that behaves differently is indistinguishable from a broken one to the
  person asking for help.
- **Do not install anything.** Everything here runs through the MCP server.
- **Name the proof.** This skill is done when `catalyst_whoami` has actually returned an
  organization, and you have said so. Configuration that looks right is not proof.
