# MCP client conformance — Codex, Copilot, Claude

CAT-1728 item 9. What each client needs in order to sign in to Catalyst's remote
MCP server at `https://mcp.cloud.r1.diagrid.io/mcp`, and a ten-minute test per
client.

Companion to [`directory-auth-assessment.md`](./directory-auth-assessment.md),
which covers dynamic client registration and the Claude directory. This one is
narrower: the four clients we care about now, against the server as it is built.

## The answer first

**No code change, no DCR, no CIMD.** Every client is onboardable through the
pre-registered public-client path the authorization server already implements.
The whole production change is one line in one values file
(cloudgrid#11735, draft).

| Client | `client_id` | Redirect URI it presents | Status |
|---|---|---|---|
| Claude Code | `claude-code` | `http://127.0.0.1:<port>/callback`, `http://localhost:<port>/callback` | works today, signed in against production |
| claude.ai, Desktop, mobile, Cowork | `claude-web` | `https://claude.ai/api/mcp/auth_callback` | needs the values entry |
| Codex | `codex` | `http://127.0.0.1:<port>/callback` | needs the values entry, and a pinned callback |
| VS Code / Copilot | `vscode` | `http://127.0.0.1:33418`, `https://vscode.dev/redirect` | needs the values entry, registered at the **root** path |

### Why a static client works everywhere

Our RFC 8414 document advertises no `registration_endpoint` and no
`client_id_metadata_document_supported`, deliberately — an open `/register` is
the one endpoint on an authorization server that invites abuse, and the reasons
are recorded in `metadata.ts`. Every client here falls back to a user-supplied
`client_id` when it sees that:

- **Codex** — `codex mcp add <name> --url <url> --oauth-client-id <id>`, or
  `client_id` under `[mcp_servers.<name>.oauth]`. A configured client ID always
  takes precedence over DCR and CIMD.
- **Claude** — a custom connector's advanced settings take an OAuth client ID,
  with the client secret optional; left blank, Claude uses the ID as a public
  client, which is exactly what we want.
- **VS Code** — on an authorization server with no `registration_endpoint` it
  prompts: *"does not support automatic client registration. Do you want to
  proceed by manually providing a client registration (client ID)?"*

## The two traps

Redirect matching compares scheme, host, **path** and query exactly. Only the
port is flexible, and only for loopback — RFC 8252 §7.3, because a native app
binds an ephemeral port it cannot know at registration time. Path is where both
of these bite.

**VS Code's redirect has no path.** It presents `http://127.0.0.1:33418`, whose
pathname is `/`. Registered against `http://127.0.0.1/callback` it does not
match and sign-in dies at the redirect. It is therefore registered as
`http://127.0.0.1/`. That is not a relaxation: any port on loopback already
matches by spec, and mandatory S256 PKCE is what makes that safe — a process
squatting a loopback port still cannot exchange the code without the verifier.

**Codex has two callback shapes.** The default
`http://127.0.0.1:<port>/callback` matches. The server-specific
`http://127.0.0.1:<port>/callback/<callback_id>` does not — different path,
different redirect URI — and it cannot be registered server-side because the id
is per-server and unknown at registration time. Pin it client-side instead; the
config below does.

## Before any test

The client entries must be live. `cloudgrid#11735` is a draft, because adding
OAuth clients to production is Casper's call.

```
curl -s https://api.r1.diagrid.io/mcp-auth/.well-known/oauth-authorization-server | jq .
```

Expect `200`, `issuer: "https://api.r1.diagrid.io/mcp-auth"`,
`code_challenge_methods_supported: ["S256"]`, and no `registration_endpoint`.
That last absence is intended — it is what sends each client down the
static-client path.

Use the URL **exactly** as written below, including `/mcp` and no trailing
slash. The RFC 8707 `resource` is compared byte for byte against the one
configured resource, with no normalisation, so a trailing slash is a different
resource and is refused with `invalid_target`.

---

## Claude Code — 2 minutes

Already proven against production; run it first anyway as the control. If this
fails, the server is wrong, not the client.

```
claude mcp add --transport http catalyst https://mcp.cloud.r1.diagrid.io/mcp --client-id claude-code
```

1. Browser opens on `login.diagrid.io`. Sign in.
2. Consent screen names **Claude Code** and your org.
3. Approve. The browser says you can close it.
4. `/mcp` in Claude Code shows `catalyst` connected.
5. Ask it to list your Catalyst projects. Real data comes back.

---

## Codex — 10 minutes

`~/.codex/config.toml`:

```toml
[mcp_servers.catalyst]
url = "https://mcp.cloud.r1.diagrid.io/mcp"

[mcp_servers.catalyst.oauth]
client_id = "codex"
callback_url = "http://127.0.0.1:1455/callback"
```

The `callback_url` line is the trap above — without it Codex may use
`/callback/<callback_id>`, which no registration can match.

1. Start Codex. It should prompt to authenticate the `catalyst` server.
2. Browser opens on `login.diagrid.io`. Sign in.
3. Consent screen names **Codex**.
4. Approve; the loopback page confirms.
5. Ask Codex to list your Catalyst projects.

---

## VS Code / Copilot — 10 minutes

`.vscode/mcp.json` in any workspace:

```json
{
  "servers": {
    "catalyst": {
      "type": "http",
      "url": "https://mcp.cloud.r1.diagrid.io/mcp"
    }
  }
}
```

1. Click **Auth** on the CodeLens above the server entry, or start the server.
2. VS Code says the server does not support automatic client registration and
   asks for a client ID. Enter **`vscode`**.
3. Browser opens on `login.diagrid.io`. Sign in.
4. Consent screen names **Visual Studio Code**.
5. Approve. VS Code shows `catalyst` running.
6. In Copilot Chat, agent mode, check the tool picker lists the Catalyst tools,
   then ask for your Catalyst projects.

If step 2 never appears and it fails straight away, that is the DCR path being
attempted regardless — worth knowing, and it is the one outcome that would send
us back to the assessment doc.

---

## claude.ai / Claude Desktop — 10 minutes

Settings → Connectors → **Add custom connector**.

- URL: `https://mcp.cloud.r1.diagrid.io/mcp`
- Advanced settings → OAuth Client ID: **`claude-web`**
- OAuth Client Secret: **leave blank**. Blank means Claude uses the ID as a
  public client, which is what the server expects; it advertises
  `token_endpoint_auth_methods_supported: ["none"]`.

1. Add the connector.
2. Browser flow on `login.diagrid.io`. Sign in.
3. Consent screen names **Claude**.
4. Approve; it returns to Claude and the connector shows connected.
5. Enable it in a chat and ask for your Catalyst projects.

Note this covers Desktop and mobile too — they share the hosted callback
`https://claude.ai/api/mcp/auth_callback`. Anthropic's docs flag that this host
may move to `claude.com`; if it does, that is one more redirect URI on the same
entry.

---

## If one fails

Send back, in this order — the first two usually settle it on their own:

1. **The full URL of the browser tab at the moment it failed.** An
   `error=invalid_client` means the `client_id` never matched; `invalid_target`
   means the resource URL was not byte-identical; `invalid_scope` means the
   client asked for a scope beyond `catalyst:read`, `catalyst:write`,
   `offline_access`. A redirect that fails before reaching `login.diagrid.io` at
   all is the path-matching trap.
2. **The exact redirect URI the client used**, if the client shows it — Codex
   and VS Code both name it in their output.
3. Whether the consent screen appeared, and what name it showed.
4. The client's own log: Codex `~/.codex/log/`, VS Code Output → MCP.

Tool calls failing *after* a successful sign-in is a different problem —
that is the token exchange or per-user RBAC, not client conformance.

## What this does not cover

- **The Claude directory listing** (CAT-1734) — a directory connector needs DCR,
  CIMD or Anthropic-held credentials, none of which a static client satisfies.
  That is [`directory-auth-assessment.md`](./directory-auth-assessment.md).
- **Custom URI schemes.** `myapp://` is a legitimate native redirect under RFC
  8252 §7.1 and the server refuses it today, on purpose. Nothing in this matrix
  needs one; a client that did would need a code change, not a values entry.
