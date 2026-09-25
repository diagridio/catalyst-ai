# Submitting the connector to the Claude directory: what is ready, what is not

Preparation for [CAT-1734](https://linear.app/diagrid/issue/CAT-1734), taken against
`catalyst-ai` **0.3.3** (`be295ae`, 10 skills) and `diagridio/cloudgrid` **`origin/main`**
(`6d91112cdb`). Everything in this document that can be checked, was checked against one of
those two refs or against Anthropic's published criteria; every claim below names its source
so a reader can disagree with the evidence rather than with me.

> **Why `docs/`.** Same convention as
> [`docs/cold-start-measurement.md`](./cold-start-measurement.md): one file per measurement
> or finding, named for what it covers. Nothing here reaches an installed plugin, so it is
> exempt from `check_version_bump.py` — `VERSIONED_PREFIXES` is `("skills/",
> ".claude-plugin/")` only (`scripts/check_version_bump.py:34`). Verified, not assumed.

**Nothing was submitted, published or registered. No reviewer org was seeded.** The seeding
script is written and was not run; see [§7](#7-the-reviewer-org-seeding-script). No Catalyst
resource was created, updated or deleted in the course of writing this — the only CLI calls
made were `diagrid version`, `diagrid org list`, and `--help` probes.

---

## Verdict

**5 done · 3 blocked · 8 need a human · 1 at risk.** The single most important gap is not on
this list as a line item, because it is not a checklist row: **the connector cannot be
submitted from this account at all** until someone with Owner or Directory permission on a
Diagrid **Team or Enterprise** Claude organization opens the portal. That is a prerequisite
the issue does not mention, it is nobody's engineering task, and it has a lead time nobody
has started.

| # | Requirement | Status | Where the evidence is |
| --- | --- | --- | --- |
| 1 | Production HTTPS endpoint | ✅ **done** — `https://mcp.cloud.r1.diagrid.io/mcp` | [§3.1](#31-production-https) |
| 2 | Streamable HTTP transport | ✅ **done** | [§3.2](#32-streamable-http) |
| 3 | OAuth 2.0 with user consent | ⛔ **blocked** | [§3.3](#33-oauth-20-with-user-consent) |
| 4 | Per-tool `title` | ✅ **done** | [§4](#4-the-annotation-claim-verified) |
| 5 | `readOnlyHint` / `destructiveHint` | ✅ **done** | [§4](#4-the-annotation-claim-verified) |
| 6 | Tool names ≤ 64 characters | ✅ **done** | [§4](#4-the-annotation-claim-verified) |
| 7 | Read and write are separate tools | ✅ **done** | [§4](#4-the-annotation-claim-verified) |
| 8 | Privacy policy | 🙋 **needs a human** — draft below, legal review then publish | [§5](#5-privacy-policy--draft-for-legal-review) |
| 9 | Support contact | 🙋 **needs a human** — one line to confirm | [§6](#6-support-contact) |
| 10 | Icon | 🙋 **needs a human** — none found anywhere | [§8](#8-icon--not-found) |
| 11 | 1–5 categories | 🙋 **needs a human** — recommendation below | [§9](#9-categories--recommendation) |
| 12 | Reviewer test account, fully populated | 🙋 **needs a human** — script written, org does not exist | [§7](#7-the-reviewer-org-seeding-script) |
| 13 | 10-second OAuth latency budget | ⛔ **blocked** (and **not** an Anthropic requirement — [§10.3](#103-the-10-second-oauth-latency-budget-is-ours-not-anthropics)) | [§3.3](#33-oauth-20-with-user-consent) |
| 14 | `catalyst-ai` public (D8) | 🙋 **needs a human** — repo is `PRIVATE` today | [§3.4](#34-catalyst-ai-public-d8) |
| 15 | Submission portal access: Team/Enterprise org + Directory permission | 🙋 **needs a human** — **not in the issue** | [§10.1](#101-a-requirement-the-issue-does-not-have-portal-access) |
| 16 | Public documentation by publish date | 🙋 **needs a human** — **not in the issue** | [§10.2](#102-a-second-missing-requirement-public-documentation) |
| 17 | Every tool answers successfully with valid parameters | ⚠️ **at risk** on a `metadata` org | [§10.4](#104-the-functional-quality-criterion-collides-with-the-default-data-sharing-level) |

Rows 15, 16 and 17 are not in CAT-1734. They come from Anthropic's own two pages —
[submission](https://claude.com/docs/connectors/building/submission) and the
[pre-submission checklist](https://claude.com/docs/connectors/building/review-criteria) — read
on 2026-08-23. Reading them was the highest-value thing in this exercise: the issue's
requirement list is accurate as far as it goes, and it is not complete.

---

## 1. What this document is for

A human should be able to sit down with this file and either submit, or see exactly what is
missing and who has to do it. It is deliberately not a plan: sequencing the blocked items is
CAT-1728's job, and the Preview-track decision ([§11](#11-open-decision-the-preview-track))
is not mine to take.

## 2. What was deliberately not done

| Not done | Why |
| --- | --- |
| Seed the reviewer org | It creates real resources in a real organization. The script is in `scripts/seed_reviewer_org.py`, defaults to a dry run, and prints every command it would issue. |
| Publish a privacy policy | [§5](#5-privacy-policy--draft-for-legal-review) is a draft with unfilled placeholders, for legal. Publishing a guess is worse than publishing nothing. |
| Register or submit anything with Anthropic | Not this issue, and not possible from this account — [§10.1](#101-a-requirement-the-issue-does-not-have-portal-access). |
| Generate an icon | An icon was reported to exist. It does not, anywhere I could look — [§8](#8-icon--not-found). Inventing one and calling it *found* would be the worst outcome. |
| Run any mutating CLI command | The CLI is v1.66.0 logged into **production**, current org `engineering-shared`. Read-only only. |

---

## 3. The requirements that depend on the authorization server

### 3.1 Production HTTPS

✅ **Done, and serving.**

The canonical URL is **`https://mcp.cloud.r1.diagrid.io/mcp`**, and it must never change,
because RFC 8707 makes that string the permanent token audience (CAT-1728 item 7). A
client pointed at any other host gets a token for the wrong audience, which fails as an
auth error that reads like a permissions problem.

`mcp.r1.diagrid.io`, the name this section used to give, is **not** the URL: it does not
resolve. Do not copy it from older notes.

- **The route** landed in `cloudgrid#10355` (merged 2026-08-28), off by default.
  Production turns it on with `mcpPublicDomain: "mcp.cloud.r1.diagrid.io"` in
  `deploy/config/catalyst-dataplane/production-r1/catalyst-dataplane.yaml`.
- **The certificate problem is gone** because of the name. The dataplane gateway already
  serves `*.cloud.r1.diagrid.io` from the delegated `cloud.r1.diagrid.io` zone, so a host
  under it needs no new zone, issuer or record in the parent zone.
- **The audience matches everywhere:** the MCP server's `--public-url` and
  `--edge-auth-audience`, admingrid's protected-resource `resource`, and the production
  Auth0 audience in `infrastructure/auth0/locals.tf` all say
  `https://mcp.cloud.r1.diagrid.io/mcp`.
- **Verified live:** an unauthenticated request gets `401` with
  `WWW-Authenticate: Bearer resource_metadata=...`; the protected-resource and
  authorization-server metadata both answer; and a production sign-in from Claude Code
  completed and returned the user's projects.

Staging is `https://mcp.cloud.staging.diagrid.dev/mcp`, with its own audience.

### 3.2 Streamable HTTP

✅ **Done.** `services/catalyst/mcp/internal/transport/http.go:70` on `origin/main`:

```go
return mcp.NewStreamableHTTPHandler(getServer, &mcp.StreamableHTTPOptions{Stateless: true})
```

The submission portal asks you to confirm "streamable HTTP or SSE". It is streamable HTTP,
stateless. This is the one transport-level requirement that needs nothing.

### 3.3 OAuth 2.0 with user consent

⛔ **Blocked, at the root.** CAT-1728's item 1 — *can an Auth0 Token Exchange Profile mint for
`admingrid-api` while preserving the user's `sub`?* — is **unproven**, and CAT-1728 says in
its own words that "everything else depends on the answer". The experiment is written and
waiting on a `terraform apply` (`cloudgrid#10349`, staging only, **open**).

Everything downstream is written and unmerged. All four checked with `gh pr view`:

| PR | What it is | State |
| --- | --- | --- |
| `#10349` | Auth0 custom token-exchange profile, staging only | merged 2026-08-27 |
| `#10350` | asymmetric signing keys + JWKS for the AS | merged 2026-08-25 |
| `#10357` | AS request path — PKCE, discovery, refresh rotation | merged 2026-08-25 |
| `#10360` | consent screen, org resolved at consent time | merged 2026-08-28 |
| `#10355` | the public route, off by default | merged 2026-08-28 |

So: **user consent is shipped**, and a production sign-in from Claude Code has completed. Anthropic's requirement is "Use OAuth 2.0 for
authenticated services" and the portal asks which client-registration mode you use (DCR, CIMD,
or a static client ID held by Anthropic). CAT-1728's 2026-08-22 finding — that Claude Code
accepts a pre-registered `--client-id` and does *not* require CIMD — makes the third option
viable, which is worth carrying into the portal answer.

The **10-second OAuth latency budget** (row 13) is a property of this flow and therefore
blocked with it. It is also not Anthropic's requirement — see
[§10.3](#103-the-10-second-oauth-latency-budget-is-ours-not-anthropics).

### 3.4 `catalyst-ai` public (D8)

🙋 **Needs a human.** Checked, not assumed:

```
$ gh repo view diagridio/catalyst-ai --json visibility,isPrivate
{"isPrivate":true,"visibility":"PRIVATE"}
```

Two notes. Anthropic's *"Plugins must link a public GitHub repo; closed-source is not
accepted"* applies to plugin submissions, and this is a **remote MCP server** submission — so
the directory does not force the flip. But CAT-1732 (the one-click install control) is
explicitly blocked on it, and [§10.2](#102-a-second-missing-requirement-public-documentation)
does need *something* public by the publish date. The repo also has no `description` and no
`homepageUrl` set, which is a two-minute fix worth doing in the same pass as the flip.

---

## 4. The annotation claim, verified

CAT-1734 asserts the annotation criteria are "all now enforced as red tests in
`internal/toolset`". **I checked each criterion against a named test on `origin/main` rather
than repeating the claim. It holds for all six — and it does not cover the thing that would
actually get us bounced.**

The curated surface on `origin/main` is **22 tools: 16 read, 6 write, exactly one
destructive** (`catalyst_terminate_workflow_run`).

### Criterion by criterion

| Anthropic's criterion | Enforced? | Test |
| --- | --- | --- |
| Every tool has a `title` (in the manifest) | ✅ | `TestEveryToolIsDescribedForAHuman` — `toolset_test.go`. Also asserts a 40-character description floor. |
| Every tool has a `title` **on the wire** | ✅ | `TestAnnotationsAreAlwaysExplicit` — `bind_test.go`. Connects a real `mcp.Server`, calls `ListTools`, asserts `tool.Title != ""`. |
| `readOnlyHint` correct on the wire | ✅ | Same test: `tool.Annotations.ReadOnlyHint != !want.Write` fails. |
| `destructiveHint` present and correct | ✅ | Same test asserts it is **non-nil** — the wire default is `true`, so an omitted hint tells a client a read tool may destroy things — and that it matches the manifest. |
| Names ≤ 64 characters | ✅ | `TestNamesMeetTheDirectoryContract` — plus the `catalyst_` prefix, the `^catalyst_[a-z0-9_]+$` shape, and duplicate detection. |
| Read and write must be separate tools | ✅ | `TestReadAndWriteAreNeverMixed`. **The strongest of the six**: it derives read/write from the HTTP methods of the operations in the loaded specs rather than trusting the `Write` flag, so a mislabelled tool fails the build. This is exactly the criterion Anthropic states most explicitly ("Do not ship a catch-all `api_request` tool"). |

Four more tests harden the destructive contract beyond what Anthropic asks:
`TestDestructiveIsOnlyClaimedForWrites`, `TestExactlyTheIntendedDestructiveTools` (pins the
set by name, so adding one is a visible diff), `TestDestructiveVerbsAreFlagged` (the
false-negative half — an operationId containing `delete`/`terminate`/`revoke`/… on a
non-destructive tool fails), and `TestEveryOperationHasAPolicyThatPermitsIt` (a tool built on
an operation the data-sharing filter denies would refuse for every org on the default
posture).

**Verdict: the claim is accurate.** Both the manifest and the wire are asserted, and the
read/write split is derived rather than declared.

### 🔴 Finding 1: nothing in `internal/toolset` covers the surface a directory client would actually see

Those tests iterate `toolset.Tools`. The server can *also* register the **generated** surface —
one tool per OpenAPI operation, **186 tools whose names are raw operationIds, with no titles,
no annotations, and 25 deletes among them** (`toolset.go`'s own package comment). Every
criterion in the table above is silent about those 186.

What protects them is not a toolset test. It is a config guard:

```go
// internal/config/config.go
if c.PublishesDiscovery() && c.ExposeRawOperations {
    return errors.New("--public-url requires --expose-raw-operations=false: ...")
}
```

tested by `TestPublicURLRefusesTheRawOperationSurface` and `TestDefaultWithholdsTheRawSurface`
in `internal/config`, with the default being `false` (`DefaultConfig()` leaves it at the zero
value). That is a good guard and it is tested. **It is also narrow, and the code says so in
its own comment:**

> it checks what the operator DECLARED, not whether the endpoint is reachable. A Service type
> flipped to LoadBalancer, or an Ingress placed in front, exposes this server with
> `--public-url` unset and the guard silent. Reachability is not observable from inside the
> process.

So the honest form of the claim is: *the annotation criteria are enforced for the curated
surface, and the unannotated surface is kept off the public route by a declaration-level
config guard rather than by an assertion about what is served.* That is one step removed from
the property Anthropic tests, which is "what does `tools/list` return on the URL I connected
to". **This is the class of gap that costs a re-submission cycle**, because a reviewer sees
tools, not flags.

*Recommended, and small:* a boot-time assertion that a server built for a `PublishesDiscovery()`
configuration lists only tools carrying a `Title` and a non-nil `DestructiveHint` — the same
property `TestAnnotationsAreAlwaysExplicit` checks, asserted about the server that is actually
being served rather than about the manifest. It would also catch an Ingress placed in front,
because it asserts on the built surface.

### Finding 2: the `--expose-raw-operations` flag help contradicts the code

```go
// cmd/catalyst-mcp/main.go:43
flag.BoolVar(&cfg.ExposeRawOperations, "expose-raw-operations", cfg.ExposeRawOperations,
    "Also register one tool per OpenAPI operation alongside the curated toolset. On by default; refused together with --public-url")
```

It is **off** by default. `DefaultConfig()` does not set it, `config.go:110` documents
"Defaults to FALSE", and `TestDefaultWithholdsTheRawSurface` pins it. The help string is stale
in the one direction that matters: an operator reading it believes 186 unannotated tools are
already being served and may "fix" that by passing the flag explicitly. One-line fix, worth
doing before anyone reads it during review prep.

### Residual risk, not a defect: five writes declare `destructiveHint: false`

`catalyst_start_workflow`, `pause`, `resume`, `raise_workflow_event` and `rerun` are writes
with `Destructive: false`; only `terminate` is `true`. That matches the MCP definition
(`destructiveHint` means *may perform irreversible updates*, and pause/resume are each other's
inverse). Anthropic's wording is looser — *"`destructiveHint: true` for tools that modify or
delete data"* — and a reviewer applying it literally could object to five tools at once.

Do not pre-emptively flip them: marking a `pause` destructive makes every client prompt before
a reversible call, which is a worse product. But it is the most likely annotation objection,
so put the reasoning in the portal's "Use cases" step, where it is read before review rather
than after a bounce.

---

## 5. Privacy policy — DRAFT FOR LEGAL REVIEW

> # 🚧 DRAFT — NOT APPROVED, NOT PUBLISHED, NOT LEGAL ADVICE 🚧
>
> **This is engineering's factual account of what the connector transmits, written so legal
> has something accurate to work from. It has not been reviewed by legal, it is not
> approved, and it must not be published or linked from a submission in this state.**
>
> Every value that must come from legal or product is an unfilled placeholder written
> `⬛⬛⬛`. **Do not fill one in with a plausible guess.** A retention period, a jurisdiction
> or a DPA claim that is wrong is worse than an obvious blank, because a blank gets asked
> about and a plausible wrong answer gets relied on.

### 5.0 Why this is a new document rather than a link to the existing one

Diagrid already has a corporate privacy policy at
<https://www.diagrid.io/privacy-policy>, effective **3/11/24**. Read on 2026-08-23, it:

- has **no mention of AI assistants, model providers, MCP or connectors** of any kind;
- names no AI/LLM sub-processor (its third-party section is "Service Providers: Hosting,
  technology and communication providers" and "Analytics Partners");
- states retention as "as long as reasonably necessary" with no timeframe;
- references no DPA;
- gives `legal@diagrid.io` and a Federal Way, WA postal address.

Anthropic requires the policy to cover *data collection, usage and storage, third-party
sharing, data retention, and contact information*, and states plainly that **"missing or
incomplete privacy policies result in immediate rejection."** The corporate policy does not
disclose the one thing this connector does that is genuinely new: **it sends customer
operational data into an AI assistant's context, and therefore to that assistant's model
provider.** Linking the existing policy as-is is the single most likely way to be rejected on
paperwork.

So the recommendation is a **connector-specific privacy notice**, published at its own URL,
which incorporates the corporate policy by reference and adds the connector-specific
disclosure. That is also the cheaper path through legal: it changes nothing about the
corporate policy.

---

### Diagrid Catalyst Connector — Privacy Notice *(draft)*

**Last updated: ⬛⬛⬛** · Applies to the Diagrid Catalyst connector for Claude.
This notice supplements the [Diagrid Privacy Policy](https://www.diagrid.io/privacy-policy),
which governs everything not described here.

#### What the connector is

The Catalyst connector lets an AI assistant read and operate your Diagrid Catalyst resources
on your behalf. It exposes **22 tools — 16 read-only and 6 that write.** The writes are
workflow lifecycle only: start, pause, resume, raise an event, rerun, terminate. **There are
no create, update or delete tools for any Catalyst resource.**

#### What is transmitted, and to whom

When you or your assistant invokes a tool, the connector calls the Diagrid Catalyst
**Management API** and **control plane** under **your own identity** and returns the result to
the assistant. Two consequences follow, and both are the point of this notice:

1. **The connector holds no credential of yours.** It forwards the identity established when
   you authorized it; it does not store a Catalyst API key or a control-plane token on your
   behalf.
2. **Tool results enter the assistant's conversation context, and therefore reach the
   assistant's model provider** (for the Claude directory listing, Anthropic). This is
   inherent to any connector and is the reason the filtering described below exists.

#### What is withheld before anything leaves the platform

Every response is filtered **inside Diagrid**, on the response, before it is returned to the
assistant. The level is a property of **your organization**, not of your assistant and not of
the request — a caller cannot ask for a wider level than the organization is set to.

There are two levels.

**`metadata` — the conservative default.**
You receive names, statuses, timestamps, durations, error messages and resource
configuration. Removed before transmission:

| Removed | Where |
| --- | --- |
| Workflow `input`, `output` and `customStatus` | every workflow run, every list and every single read |
| Activity, child-workflow and external-event `input` and `output` | every history event, at any depth of an execution graph |
| Raw workflow history event dumps | reduced to a reviewed set of diagnostic keys |
| Agent prompt text, behavioural instructions, prompt templates and the user-supplied metadata map | durable agent reads |
| A captured MCP server's prompts and resources, and any non-protocol tool annotation | MCP server reads |
| Application log lines, and workflow export | these operations are **refused** entirely rather than filtered |

Removal means the field is **absent**, not empty. Anything that cannot be parsed and therefore
cannot be filtered is refused rather than passed through.

**`full` — opt-in, per organization.**
Business data is returned: workflow `input`, `output` and `customStatus`, agent
configuration, log lines. **Be aware that at this level the per-field withholding above does
not apply** — if your workflow payloads contain personal data, or your applications print
personal data to their logs, that data will reach the assistant and its model provider. An
organization on `full` has made that trade deliberately, and only an organization
administrator can make it.

**Credentials are removed at every level, including `full`.** This is governed separately from
data sharing on purpose: `full` means *you may read the inputs and outputs of my workflows*,
never *you may read my LLM API key*. Removed at both levels: API tokens, app-channel tokens,
tunnel and join tokens, OAuth2 client secrets, LLM provider API keys, GitHub App private keys,
webhook URLs and webhook headers. References to secrets — the *name* of the secret a component
uses — are kept, because a name is not a secret.

*One residual gap, stated rather than omitted:* at the `full` level a response body that is
not valid JSON is passed through without credential scrubbing, because there is nothing to
parse a credential out of. At the `metadata` level such a body is refused instead.

#### What the connector does not do

- It does not read your Claude conversation history, memory, conversation summaries or files.
- It does not collect conversation data beyond the arguments of the tool call being made.
- It does not create, modify or delete any Catalyst resource other than the workflow lifecycle
  operations listed above.
- It does not transfer funds or generate media.

#### Storage and retention

Tool calls and their outcomes are recorded in Diagrid's operational logging for the purpose of
service operation, security and support. **Retention period: ⬛⬛⬛.** Data already held in
Catalyst — your workflow history, resource configuration and logs — is retained under the
existing Catalyst terms and is not changed by your use of this connector.

Data that has entered your assistant's conversation is retained by **your assistant provider**
under **their** policy, not Diagrid's, and Diagrid cannot delete it on your behalf.

#### Sub-processors and third-party sharing

Diagrid does not sell your data. Beyond the sub-processors listed in the corporate policy, use
of this connector involves: **⬛⬛⬛** *(legal to confirm whether the assistant provider is
named as a recipient, a sub-processor, or neither, and whether the corporate policy's
sub-processor list needs the addition)*.

#### Data location and transfers

Catalyst services are hosted and operated in **⬛⬛⬛** *(the corporate policy says the United
States; confirm for the region serving the connector, which is `r1`)*. Your assistant
provider's processing location is governed by their own policy.

#### Governing law and data processing agreement

**Governing law: ⬛⬛⬛.**
**DPA: ⬛⬛⬛** *(do not assert that a DPA covers this connector until legal confirms it. The
corporate policy references none.)*

#### Your choices

- **Disconnect at any time** from your assistant's connector settings. Disconnecting revokes
  the connector's access; it does not delete data already in your conversation history.
- **Lower your data-sharing level.** An organization administrator can set the organization to
  `metadata`, which withholds the payload fields listed above from every tool result. It is the
  default.
- **Do not connect.** Every read the connector performs is also available through the `diagrid`
  CLI and the Catalyst console, neither of which sends anything to a model provider.

#### Contact

Privacy questions: `legal@diagrid.io`. Product and support: `support@diagrid.io`.
**Postal: ⬛⬛⬛** *(the corporate policy's Federal Way, WA address, if legal wants it repeated
here.)*

*— end of draft —*

### 5.1 Where every factual claim above comes from

So legal can check the engineering half rather than take it on trust. All paths in
`diagridio/cloudgrid` at `origin/main`, under `services/catalyst/mcp/`:

| Claim | Source |
| --- | --- |
| Filtering is on the response, inside the platform | `internal/filter/level.go` package comment: *"a model cannot be talked past a field that was never sent"* |
| Two levels; `metadata` is the default | `internal/filter/level.go`, `LevelMetadata` / `LevelFull`; `config.DefaultConfig()` |
| The level comes from the organization, not the request | `internal/orgpolicy/orgpolicy.go`; `--derive-data-sharing` |
| Absent, not empty; unparseable is refused | `internal/filter/filter.go`, `FilterBody` → `RefusalUnfilterable` |
| Workflow `input`/`output`/`customStatus` removed | `internal/filter/policy.go`, `workflowExecutionRules` |
| Activity and event payloads removed at any depth | `internal/filter/policy.go`, `historyEventRules`, `graphRules` |
| Agent prompt text and instructions withheld | `internal/filter/policy.go`, `agentMetadataRules` |
| MCP prompts/resources withheld | `internal/filter/policy.go`, `mcpCapabilityRules` |
| Logs and workflow export refused at `metadata` | `internal/toolset/tools.go:257–267` (the "deliberately absent" block) |
| At `full`, rules do not apply — only credential scrubbing | `internal/filter/filter.go`, `Apply` returns immediately after `scrubCredentials` when `level == LevelFull` |
| Credentials removed at **every** level | `internal/filter/scrub.go` package comment, and the `Apply` ordering above |
| The specific credential fields | `internal/filter/scrub.go`, `credentialValueKeys` and `credentialsByParent` |
| Secret *references* kept | `internal/filter/scrub.go`: scalar at a credential key is removed, object is a reference wrapper and is kept |
| Non-JSON at `full` is passed through unscrubbed | `internal/filter/filter.go`, the `if !isJSON` branch inside the `LevelFull` block — the code calls it "a residual gap" itself |
| No credential is held on the user's behalf | CAT-1728's design: *"MCP access tokens are Diagrid-minted RS256 … carrying no upstream credential"* |
| 22 tools, 16 read / 6 write / 1 destructive | `internal/toolset/tools.go` |
| No create/update/delete tools | `internal/toolset/tools.go:268–295` |
| No conversation data, memory or files | Nothing in the toolset reads them; Anthropic's criteria forbid it |

⚠️ **One thing legal must be told, not shielded from:** the notice above describes the
platform's behaviour, but the reviewer org will be on `data_sharing: full`
([§7](#7-the-reviewer-org-seeding-script)), and A2 (CAT-1727) decided that data sharing
"must be enabled" to make the product work at all. So the `full` paragraph is not an edge
case — it is likely to be the common case. It is written to be honest about that.

---

## 6. Support contact

🙋 **Needs a human — one line to confirm.** Recommendation:

| Field | Value |
| --- | --- |
| Support contact | `support@diagrid.io` |
| Privacy contact (in the notice) | `legal@diagrid.io` |
| Documentation URL | `https://docs.diagrid.io/` (specific page TBD — see [§10.2](#102-a-second-missing-requirement-public-documentation)) |
| Company | Diagrid, `https://www.diagrid.io` |

`support@diagrid.io` is the address published in Diagrid's own docs for customers raising
incidents (`docs/dapr-open-source/dapr-support.mdx:85`,
`docs/operate/hosting/enterprise-self-hosted/aws-marketplace-installation-guide.mdx:134`), so
it is the right *published* answer. The thing needing a human is whether that queue should
receive **free-tier connector users** who may have no support contract at all — the same
document ties response times to the customer's contract. If the answer is no, the connector
needs its own address before submission, because it is displayed on the listing.

`catalyst@diagrid.io` also exists in the docs and may be the better fit; that is a decision for
whoever owns the support rota, not a guess I should make.

---

## 7. The reviewer-org seeding script

**Written, not run.** `scripts/seed_reviewer_org.py`, with `scripts/test_seed_reviewer_org.py`
covering it. It **defaults to a dry run**: `--apply` is required to execute anything, and it
refuses to apply unless `--org` matches `diagrid org current`, so it cannot silently seed
`engineering-shared`.

**It applies in two phases, and the reason is worth knowing before you run it.**
`diagrid dev run` blocks in the foreground and v1.66.0 has no detach flag, so a script
that shells out to it never returns. The first version did exactly that: it would have
created the App ID, agent and MCP server, then hung before starting a single workflow
run — leaving an organization with no runs at all and no error to explain why.

So the plan stops at the worker instead of trying to supervise it:

```
# phase 1 — creates the App ID, agent and MCP server, then hands you the worker command
python3 scripts/seed_reviewer_org.py --org <org> --mcpserver-url <url> \
    --apply --prereqs-confirmed

# then, in its own terminal, the command phase 1 printed:
diagrid dev run --project default --id catalyst-demo -- python scripts/seed/app.py

# phase 2 — starts the 24 runs and verifies the result
python3 scripts/seed_reviewer_org.py --org <org> --mcpserver-url <url> \
    --apply --prereqs-confirmed --phase runs
```

Each phase is independently re-runnable, so a failure part-way through is recovered by
re-running that phase rather than by unpicking a half-seeded organization.

**Phase 2 verifies rather than asserts.** It reads the runs back, parses them, and exits
non-zero unless the organization actually carries at least 24 runs across 3 workflow
names with at least 2 in `failed`. An exit code of 0 from every CLI call is not the same
as an organization fit to demo, and the failed-run count is the first thing a reviewer
will look for.

Run it with no arguments to get the plan:

```
python3 scripts/seed_reviewer_org.py --org <reviewer-org> --project default
```

### What it would create

The issue asks for **≥3 workflows, ≥20 runs including ≥2 real failures, 1 agent, 1
MCPServer.** The plan:

| Step | Command | Idempotent by |
| --- | --- | --- |
| Verify the org | `diagrid org current` | read-only; aborts on mismatch |
| Verify `default` exists | `diagrid project get default` | read-only; **does not create a project** — see below |
| One App ID for the workflow worker | `diagrid app create catalyst-demo --project default --ignore-if-exists` | the CLI's own `--ignore-if-exists` |
| 1 Durable Agent | `diagrid managed-agent create demo-assistant …` | guarded by `managed-agent get` first — **the CLI has no `--ignore-if-exists` here** |
| 1 MCPServer | `diagrid mcpserver create demo-tools --url … --project default` | guarded by `mcpserver get` first — likewise no `--ignore-if-exists` |
| Run the worker | `diagrid dev run --project default --id catalyst-demo -- python seed/app.py` | a worker; **no `--app-port`** |
| 24 workflow runs across 3 names | `diagrid workflow start <name> --project default --id catalyst-demo --instance-id seed-<name>-<nn> -d '<json>'` | run ids are **deterministic**, so a re-run collides rather than doubling the count |
| Verify | `diagrid workflow list --project default --status failed` etc. | read-only |

Three details are load-bearing and were checked against the pinned CLI's `--help` rather than
remembered:

- **`--ignore-if-exists` exists on `project create` and `app create`, and does not exist on
  `managed-agent create` or `mcpserver create`.** So idempotency is the CLI's job for two
  steps and the script's job for two. Getting this backwards is how a re-run fails halfway.
- **`workflow start` requires `--instance-id`** and nothing generates one. The script names
  every run deterministically (`seed-<workflow>-<nn>`), which is what makes re-running safe:
  a second run of the script re-uses the same 24 ids rather than creating 24 more.
- **It does not create a project.** Every organization gets a `default` with the managed
  workflow store already attached, and workflow reads require that store — a hand-rolled
  project is the most common reason a run starts and never appears
  (`skills/catalyst-workflow-scaffold/SKILL.md` §3). If `default` is missing, the script
  **aborts and says so** rather than creating one.

### The ≥2 genuine failures

`scripts/seed/app.py` registers three workflows, and one of them — `reconcile-invoice` — has an
activity that raises when its input says to:

```python
@wfr.activity(name="charge_card")
def charge_card(ctx, payload: dict):
    if payload.get("card") == "expired":
        raise RuntimeError("card declined: expired (seed: deliberate failure)")
    ...
```

The script starts two runs with `{"card": "expired"}`. Those runs fail the way a real run
fails: the activity raises, the orchestrator surfaces it, the run reaches `Failed`, and
`catalyst_get_workflow_run` shows *which step* failed with the real error text — which is what
a reviewer asking "show me something that went wrong" actually wants to see.

**Nothing writes a failure state into a store.** A forged `Failed` record has no history, no
failing step and no error, so the graph a reviewer opens would be empty — a demo that is worse
than no demo, and dishonest besides.

### 🔴 Two prerequisites the script cannot satisfy itself

1. **The org must be on `data_sharing: full`** (the A2 decision, CAT-1727). At `metadata`,
   workflow `input`, `output` and `customStatus` are **absent**, so a reviewer asking "what did
   this run receive?" gets nothing and concludes the connector is broken — CAT-1727 says
   exactly that. **There is no CLI command for this.** Verified: `diagrid org` has only
   `list`, `current`, `use`, `usage`, and no `--help` output under `org` or `project` mentions
   sharing. The level is a control-plane property read from
   `/apis/cra.diagrid.io/v1beta1/reagent` (`internal/orgpolicy/orgpolicy.go`) and set through
   admingrid. Someone with control-plane access has to set it, and the script's first
   verification step should be a tool call confirming a payload comes back.
2. **The reviewer org does not exist.** `diagrid org list` today:
   `engineering-shared` (internal, current), `bandicoot-poggle-the-lesser` (Cloud),
   `Synergy Logistics` (Enterprise), `guppy-jocasta-nu` (free, Conductor). None is a reviewer
   org. Creating one is a signup flow, not a CLI call.

### One honest wart in the seeded result

The seed worker runs under `diagrid dev run` on whoever's machine executes the script. The
**run records persist** in the org afterwards, which is what a reviewer reads — but once the
process stops, the `catalyst-demo` App ID reports no live connection. A reviewer who inspects
the App ID rather than the runs sees something that looks unhealthy.

Two ways out, and it is a decision rather than a bug: accept it and say so in the reviewer
notes ("the demo worker is not running; the run history is the artefact"), or host the seed
worker somewhere so the App ID is live for the review window. The second is better and is
real work. Anthropic's criterion *"every tool must return a successful response when called
with valid parameters"* does not require a live app — the read tools answer from stored
state — so this is presentation, not compliance.

---

## 8. Icon — not found

🙋 **Needs a human. I could not find it, and I am not inventing one.**

The brief said an icon had already been produced for this project — square, 512×512 to
2000×2000, under 2 MB. **No such asset exists anywhere I could look.** What does exist is
brand artwork a designer can work from, which is a better answer than "nothing", so both
halves are recorded.

### Where I looked, and found nothing connector-specific

- `diagridio/catalyst-ai`, every branch and every commit: `git log --all --diff-filter=A
  --name-only` matches **no** `.png`, `.svg`, `.jpg`, `.webp` or `.ico` at any point in the
  repo's history. The repo has never contained an image.
- `~/Downloads`, `~/Desktop`, `~/Documents`: no image created since 2026-07-01.
- All 7 published Artifacts on this account: HTML documents, no image assets.
- Slack, searched for the connector icon: nothing.
- `.claude-plugin/plugin.json` and `marketplace.json`: no icon field, and neither schema
  has one.
- A whole-home-directory sweep for filenames containing `catalyst`, `icon`, `logo` or
  `connector`. Everything Diagrid-owned it returned is in the table below; the rest was
  another vendor's editor-extension icon or a docs social card.

### What does exist, and how usable each one is

| Asset | Shape | Verdict |
| --- | --- | --- |
| `diagrid-docs/static/img/catalyst/catalyst-logo.svg` | 222 × 56 vector wordmark | The Catalyst brand lockup — **on-brand but horizontal.** Squared, it letterboxes to about a quarter of the frame and is illegible at 32px. Its leading glyph is near-square and is the right thing to lift. |
| `diagrid-docs/static/img/catalyst/catalyst-logo-alt.svg` | 215 × 59 vector wordmark | Same problem, alternate treatment. |
| `diagrid-docs/static/img/diagrid-favicon.svg` | **41 × 41 square** vector | The only square vector we own. Scales cleanly to any size, and matches every other Diagrid surface. **The cheapest correct answer.** |
| `cloudgrid/charts/assets/img/catalyst.svg` | 2018 × 1031 excalidraw export, embedded fonts, an `invert(93%)` filter | An architecture diagram, not a mark. Not usable. |

**Recommendation, in order of cost:** ship `diagrid-favicon.svg` rasterized square for
launch; or spend a designer's hour lifting the Catalyst glyph out of `catalyst-logo.svg`
into a square mark, which is better in a directory full of company logos because it says
*Catalyst* rather than *Diagrid*. Either way it is a decision with an owner who is not me.

### What Anthropic actually specifies, checked rather than assumed

The submission page's *Asset specifications* section gives dimensions **only for MCP App
carousel screenshots** (PNG, ≥1000px wide, 3–5 images, no video or GIF). For the icon it
says only that one is required and to have it ready before starting the portal. **The
512–2000 and under-2 MB constraints are not in Anthropic's published docs.** They may well
be what the portal states at upload time — which I cannot see
([§10.1](#101-a-requirement-the-issue-does-not-have-portal-access)) — so treat them as
plausible and unconfirmed. The certain constraints are the practical ones: square, raster,
transparent-safe, legible at roughly 32px in a connector list.

---

## 9. Categories — recommendation

🙋 **A positioning decision, so: recommendation and reasoning, not a silent choice.**

The portal allows **one to five**. Anthropic publishes no category list; the list below is what
the public directory's *Use case* filter shows (read 2026-08-23): Code, Communication, Data,
Design, Education, Financial services, Health and wellness, Life sciences and healthcare,
Nonprofit, Productivity, Sales and marketing. **The portal's list is the authority and may
differ** — treat this as the shortlist to reconcile against what the form offers.

**Recommendation: two categories — `Code`, then `Data`.**

| | Why | |
| --- | --- | --- |
| **`Code`** *(primary)* | The connector's audience is developers, and its subject is code they wrote: workflows they authored, agents they built, App IDs they deployed. Every use case in the listing will be a development or operations loop. There is no *DevOps* or *Infrastructure* category, so `Code` is the one that carries developer intent. | ✅ |
| **`Data`** *(secondary)* | The read surface is 16 of 22 tools and it is largely operational data: workflow runs and their execution graphs, metrics, quota consumption, component inventory. Defensible — with the caveat below. | ✅ with a caveat |
| `Productivity` | Would be a stretch. It is where general-purpose task tooling lives, and a reviewer reads a stretch category as padding. | ⛔ |
| Everything else | Not us. | ⛔ |

**The caveat on `Data`, stated so it can be overruled:** in a connectors directory, *Data*
mostly means data platforms — warehouses, BI, analytics sources. Catalyst is not a data source;
it is a runtime whose telemetry you read. If whoever owns positioning reads `Data` as
misleading, **`Code` alone is the better answer.** Ranking is usage-based, not
category-breadth-based, so there is no discovery argument for adding categories that only
half fit — and a category that does not fit is a review objection for free.

Also for the same portal step, with character limits from the docs:

| Field | Limit | Draft |
| --- | --- | --- |
| Server name | 100 | `Diagrid Catalyst` |
| Tagline | **55** | `Build and operate Dapr workflows and durable agents` (51) |
| Description | 2,000 | needs writing — it is the listing's only real copy, and 2,000 characters is a lot of room to be vague in |
| URL slug | — | `diagrid-catalyst` — **permanent once published** |

---

## 10. What the issue's requirement list is missing, and what it gets slightly wrong

Read from Anthropic's [submission page](https://claude.com/docs/connectors/building/submission)
and [pre-submission checklist](https://claude.com/docs/connectors/building/review-criteria) on
2026-08-23. CAT-1734's list is accurate; these four are additions and corrections to it.

### 10.1 A requirement the issue does not have: portal access

> **"A Team or Enterprise organization.** Organization settings aren't available on individual
> plans." — and **"Directory management access"**, which by default is organization Owners and
> Primary owners only.

Remote MCP server submissions happen *inside* claude.ai, at
`claude.ai/admin-settings/directory/submissions/new`. So before any of the engineering above
matters, someone has to establish that Diagrid has a Team or Enterprise Claude organization
and that a named person holds Owner or a custom role carrying the **Directory** permission
(Enterprise can delegate; Team cannot, so on Team it stays with Owners).

**This is the item most likely to add weeks for a reason nobody logged**, because it is
procurement and account administration rather than engineering, nobody is assigned to it, and
it is invisible until the day someone tries to open the form. It belongs in CAT-1734 as its
own checkbox.

### 10.2 A second missing requirement: public documentation

> "**Public documentation** is required by your publish date—a blog post or help-center
> article is sufficient. You can share docs privately with Anthropic during review."

Not blocking for submission, blocking for publication. The listing also takes a documentation
URL. Interacts with D8 ([§3.4](#34-catalyst-ai-public-d8)): if `catalyst-ai` goes public, its
README plus a docs.diagrid.io page satisfies this comfortably. If it stays private, something
public has to exist anyway.

### 10.3 The 10-second OAuth latency budget is ours, not Anthropic's

The issue lists it as a directory requirement. **It is not in either Anthropic page.** Its
actual origin is CAT-1728's own design note about the OAuth callback: *"there is a 10-second
OAuth latency budget, and a slow first tool call is a far better failure than a failed
login."* That is a good constraint and it should stay — it is why the callback fires
default-project provisioning without blocking on it. It just should not be tracked as an
external gate, because nothing external will check it.

Likewise **"2–6 weeks of review queue"**: the docs say only *"Review times vary with queue
volume."* Worth knowing why: submissions are now listed as **community** connectors after an
automatic policy scan, and Anthropic *escalates* listings it judges highly useful to the
slower **verified** review, where reviewers functionally test each tool. That is not something
we opt into or can schedule. So plan for the community path, and treat verified review as an
upside with an unknown date rather than as the thing being waited on.

### 10.4 The functional-quality criterion collides with the default data-sharing level

> "Every tool must return a successful response when called with valid parameters. Generic
> errors … fail review."

On a `metadata` organization, tool results are filtered and some operations refuse outright.
The refusals are honest and well-labelled (`DATA_SHARING_RESTRICTED`), and
`TestEveryOperationHasAPolicyThatPermitsIt` already prevents shipping a curated tool built on
an operation that denies at `metadata`. So no tool is *only* ever a refusal. But payload fields
being absent is exactly the experience CAT-1727 predicted would make a reviewer conclude the
connector is broken.

This is the strongest argument for the `data_sharing: full` prerequisite in
[§7](#7-the-reviewer-org-seeding-script) being treated as a hard blocker rather than a nice-to-
have: **it is the difference between passing and failing a functional-quality review.** It is
also worth saying in the portal's "Test & launch" step that the test org is on `full`
deliberately, so a reviewer who compares against their own `metadata` intuition is not
surprised.

---

## 11. Open decision: the Preview track

**Recorded, not decided. This is not mine to take.**

CAT-1734's own recommendation still stands and nothing found here contradicts it:

> A Preview over stdio — same repo, same skills, same curated tool contract, no directory
> listing, no marketing — costs roughly two extra engineering weeks and buys the one thing
> money cannot: **the curated tool list gets validated by real users before Anthropic reviews
> it.** Submitting an unexercised surface into a 2–6 week queue is the single most likely way
> to lose a month.

| | Preview first | Submit as soon as unblocked |
| --- | --- | --- |
| Cost | ~2 extra engineering weeks before submitting | zero extra weeks |
| Buys | the 22-tool contract exercised by real users; CAT-1736's telemetry has something to measure | earlier queue entry |
| Risk | GA slips by the preview period | a re-submission cycle on a surface nobody used, at an unschedulable queue latency |
| Enabled by | already true — `diagrid mcp serve` over stdio (CAT-1731), defaulting to `full` | nothing extra |

Two things this exercise adds to the decision, both pointing the same way:

1. **The stdio path already exists and already defaults to `full`** (CAT-1727, #10345). So the
   Preview track's marginal cost is lower than "two engineering weeks" suggests — much of it
   is shipped.
2. **[§10.1](#101-a-requirement-the-issue-does-not-have-portal-access) may make the choice
   moot.** If portal access takes weeks to establish, the Preview period costs nothing in
   calendar time because it runs in parallel with an administrative wait that is happening
   anyway.

The fallback lever from the issue is unchanged and still an afternoon:
`oauth_anthropic_creds` covers claude.ai surfaces only, explicitly **not** Claude Code.

---

## 12. Every check made, so any of it can be rerun

| Check | Command / file | Result |
| --- | --- | --- |
| Version and skill count | `git log origin/main`, `.claude-plugin/plugin.json` | 0.3.3, `be295ae`, 10 skills |
| Version bump not required for `docs/` | `scripts/check_version_bump.py:34` | `VERSIONED_PREFIXES = ("skills/", ".claude-plugin/")` |
| Repo visibility | `gh repo view diagridio/catalyst-ai` | `PRIVATE` |
| CLI version | `diagrid version` | 1.66.0, API server 1.93.0 |
| Orgs available | `diagrid org list` | 4, none a reviewer org, current is `engineering-shared` |
| No data-sharing CLI command | `diagrid org --help`, grep for `shar` | `list`/`current`/`use`/`usage` only |
| Seed command shapes and flags | `diagrid {project,app,mcpserver,managed-agent} create --help`, `workflow {start,list} --help`, `dev {run,scaffold} --help` | as recorded in [§7](#7-the-reviewer-org-seeding-script) |
| Curated tool count | `internal/toolset/tools.go` at `origin/main` | 22 = 16 read + 6 write, 1 destructive |
| Annotation tests | `internal/toolset/{toolset,bind}_test.go` | 6 of 6 criteria enforced — [§4](#4-the-annotation-claim-verified) |
| Raw surface guard | `internal/config/config.go` + `config_test.go` | present, tested, declaration-level only |
| Streamable HTTP | `internal/transport/http.go:70` | `mcp.NewStreamableHTTPHandler`, stateless |
| Filter behaviour | `internal/filter/{filter,level,scrub,policy}.go` | as recorded in [§5.1](#51-where-every-factual-claim-above-comes-from) |
| AS / route PR states | `gh pr view 10349 10350 10355 10357 10360` | all five merged (checked 2026-09-25) |
| Existing privacy policy | `https://www.diagrid.io/privacy-policy` | effective 3/11/24, no AI/assistant/model-provider disclosure |
| Support address | `diagrid-docs` grep | `support@diagrid.io` (8), `sales@` (13), `catalyst@` (1) — `grep -rn '<addr>' . --exclude-dir=node_modules --exclude-dir=.git` |
| Anthropic criteria | submission + pre-submission-checklist pages | read 2026-08-23 |
| Category list | `https://claude.com/connectors` Use case filter | 11 categories, listed in [§9](#9-categories--recommendation) |
| Icon | see [§8](#8-icon--not-found) | not found anywhere |

### What was NOT checked, and why

- **The submission portal itself.** It needs Team/Enterprise + Directory permission
  ([§10.1](#101-a-requirement-the-issue-does-not-have-portal-access)), so its exact fields,
  icon constraints and category list are unverified. Anything in this document about the
  portal comes from the public docs.
- **The seeding script, executed.** By instruction. Its command shapes are verified against
  the pinned CLI's `--help`; that its 24 runs land as intended is unproven until someone
  applies it. Note also that `scripts/check_cli_surface.py` only scans `skills/`, so nothing
  under `docs/` or `scripts/` is covered by that gate — the `--help` probes in [§7](#7-the-reviewer-org-seeding-script) were done by hand for that reason.
- **Whether the five non-destructive writes survive review.** A judgement about a reviewer,
  not a fact — see the residual-risk note in [§4](#4-the-annotation-claim-verified).
