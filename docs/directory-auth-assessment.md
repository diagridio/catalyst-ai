# What the claude.ai directory actually requires of our auth

Research only. No production, Auth0 or code change is proposed here beyond one
documentation correction, which is described at the end and is not optional.

## The headline: DCR is not required, and never was

CAT-1734 has been carried as "blocked on DCR" all the way through this effort. That
premise does not survive contact with our own recon.

`docs/directory-submission.md` §3.3 records what the portal asks:

> the portal asks which client-registration mode you use (**DCR, CIMD, or a static
> client ID held by Anthropic**). CAT-1728's 2026-08-22 finding — that Claude Code
> accepts a pre-registered `--client-id` and does *not* require CIMD — makes the third
> option viable

Three accepted modes, and we already satisfy the third. We ship a pre-registered public
client today, live in production:

```
mcpAuth.clients: '[{"client_id":"claude-code",
                    "redirect_uris":["http://127.0.0.1/callback","http://localhost/callback"],
                    "name":"Claude Code"}]'
```

So the smallest change that satisfies the directory is **no auth change at all** — it is
answering the portal question with the static-client option and giving Anthropic a
client_id.

## 1. What the directory requires

DCR **or** CIMD **or** a static client ID held by Anthropic. Our submission picks the
third. Nothing in the requirement set forces RFC 7591.

## 2. What our authorization server supports today

Verified against the live production document
(`https://api.r1.diagrid.io/.well-known/oauth-authorization-server/mcp-auth`):

| Capability | State |
|---|---|
| `authorization_code` + `refresh_token` | ✅ |
| PKCE `S256` | ✅ mandatory |
| Public clients (`token_endpoint_auth_methods_supported: ["none"]`) | ✅ |
| RFC 8707 resource indicators | ✅ |
| RFC 8414 + RFC 9728 discovery | ✅ |
| Loopback redirect, any port (RFC 8252 §7.3) | ✅ |
| `registration_endpoint` (DCR) | ❌ deliberate |
| `client_id_metadata_document_supported` (CIMD) | ❌ deliberate |
| `revocation_endpoint` / `introspection_endpoint` | ❌ not implemented |

The absences are principled, not gaps. `metadata.ts` states the rule the document is built
on: *everything advertised is something the request path implements, and nothing it
implements is left out* — because an over-claim becomes a request the server rejects for
reasons the client cannot see. It also records that Auth0's own document advertises
`registration_endpoint` pointing at `GET /oidc/register`, which **404s**. We deliberately
do not repeat that.

## 3. The smallest change that satisfies the directory

**Option A — static client (recommended).** No code, no new endpoint, no new attack
surface. Answer the portal with the static-client mode and supply a client_id. If
Anthropic requires its own, that is one entry added to `mcpAuth.clients`, which is a
values-file change and already how `claude-code` is registered.

Residual risk: whether Anthropic's directory flow *in practice* accepts a static client for
a remote server, or only nominally. That is a portal question, not an engineering one, and
it should be asked before any DCR work is funded.

**Option B — implement RFC 7591 DCR.** Only if Option A is refused. This is the expensive
path, and the cost is not the endpoint — it is that an unauthenticated public endpoint that
mints client records is a durable abuse surface. CAT-1728 already listed the controls it
would need, and none are optional:

- rate limit per source
- a cap on total registered clients
- registration expiry, so abandoned records do not accumulate forever
- SSRF rules on any metadata fetch (the CIMD variant fetches a URL the caller controls —
  that is an outbound request to an attacker-chosen host from inside our network)

There is a real precedent for the rate limit: `admingridAPI.mcpAuthRateLimit` is already
enabled in staging and production for the authorization endpoint, so the pattern exists and
would extend rather than be invented.

**Option C — CIMD.** Strictly worse than A for us: it carries the SSRF surface of B while
the recon shows no client we care about requires it.

## 4. Which clients this unlocks

| Client | State |
|---|---|
| **Claude Code** | ✅ Works today, end to end, verified in production by a real sign-in. Needs no directory listing at all — it connects directly. |
| **claude.ai** | The only client the listing is actually for. Cannot use `--client-id`, which is why registration mode is a question for it and not for Claude Code. |
| **Codex** | Untested (CAT-1728 item 9). Installs skills; its MCP OAuth behaviour against a remote server is unknown. |
| **GitHub Copilot** | Untested (CAT-1728 item 9). Same. |
| **Claude Desktop** | Untested (CAT-1728 item 9). The one most likely to need DCR, since it has no flag equivalent to `--client-id`. |

**This matters for sequencing.** The directory listing buys claude.ai. It does not buy
Codex, Copilot or Desktop — those are three independent conformance questions, and the
cheapest next step is to test them against the *existing* static-client path before
concluding anything needs DCR. If Desktop turns out to need DCR, that is a far stronger
argument for Option B than the directory is.

## The correction that is not optional

`docs/directory-submission.md` §3.1 fixes the canonical URL as:

```
https://mcp.r1.diagrid.io/mcp     ← "must never change"
```

**That host does not resolve.** Production serves:

```
https://mcp.cloud.r1.diagrid.io/mcp     → HTTP 401 (live, challenge served)
```

The doc records the reason itself, in the very next paragraph: the dataplane gateway's NLB
advertises only `*.cloud.r1.diagrid.io`. The `.cloud.` form was the decision; §3.1 predates
it and was never updated. The string appears nowhere in `docs/`.

This is not cosmetic. RFC 8707 makes that string the **permanent token audience**, and the
doc says so. A submission carrying the wrong URL would either fail immediately, or — worse
— fix an audience we cannot serve into a listing that "must never change".

**Recommendation:** correct §3.1 to `https://mcp.cloud.r1.diagrid.io/mcp` before the
submission is drafted, independently of whatever is decided about DCR.
