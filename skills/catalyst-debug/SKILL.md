---
name: catalyst-debug
description: Diagnose why something in Diagrid Catalyst is broken or stuck, then stop, kill, rerun or purge a workflow run. Covers a run that failed or hangs, an app not ready, an agent not answering, a component that will not connect.
---

# Diagnose a Catalyst failure

Goal: end this skill with a named cause and the line of evidence that proves it, or an
explicit statement of what you could not see and why. "Try restarting it" is not a
diagnosis, and neither is a plausible story with no read behind it.

Everything here goes through the Catalyst MCP server, the `catalyst_*` tools. If they are
missing or refuse with `NOT_AUTHENTICATED`, that is a connection problem, not the failure
you were sent to debug: the `catalyst-setup` skill covers it.

## 1. Route by symptom

| Symptom | Start with | Then |
| --- | --- | --- |
| A workflow run failed, or hangs | `catalyst_get_workflow_run` | section 3 |
| An app never became ready | `catalyst_get_app` | section 4 |
| An agent does not answer | `catalyst_get_agent` | section 5 |
| A component will not connect | `catalyst_get_component` | section 6 |
| Nothing named — "is anything broken?" | `catalyst_list_projects`, then the project | below |

Say which call produced each finding.

### One project, named

A question with no symptom in it — "is anything broken", "is my project healthy" — is
about **one** project. Resolve it, name it in your answer, say which projects you did not
look at, and stay inside it. An organization holds other people's projects, and sweeping
them turns a bounded diagnosis into a survey nobody asked for.

The MCP surface has no current project: every project-scoped tool takes the project as an
explicit argument, so pass it on every call. An unqualified question means `default`.

Widening is legitimate and is a decision you state first: "anything broken anywhere",
"across the organization", a named second project, or any plural or comparing question
("which of my projects uses the most quota") all need more than one project, and some
need every one of them. Say how many you are about to read before you start. Do not go
hunting for a project called `staging` or `prod`: those are usually separate
deployments, not projects in this organization.

Read the project first, in every case: `catalyst_get_project`. Managed workflow storage
and agent infrastructure are project settings, and when one is off the symptoms are
indistinguishable from broken resources. The project named `default` already has managed
pub/sub, KV, workflow store and agent infrastructure attached. **Never create a project**
while debugging — a new project with different settings turns one unexplained failure
into two.

## 2. Rules of evidence

- **Status before logs.** Status tells you whether the platform ever got as far as running
  the thing. Logs only tell you what happened if it did. Opening with logs is how a "never
  scheduled" resource gets diagnosed as an application bug.
- **The reason is rarely at the top.** A status carries messages at up to three levels,
  and for anything scoped to apps, agents or MCP servers the useful one is the deepest:

  | Where | Field | When it holds the answer |
  | --- | --- | --- |
  | Resource | `status.messages[].message` | Control-plane level failures |
  | Per region | `status.instances[].messages[].message` | One region reconciled and another did not |
  | Per identity | `status.appIdStatus[].messages[].message` | **Components and MCP servers.** A component that fails to load is only reported as such by the sidecar of each identity it is scoped to, so this is usually the only place the reason exists |

  Two more error strings sit outside that structure and are easy to miss: a pub/sub's
  `status.topicError` and a KV store's `status.itemsError`.
- **`catalyst_get_logs` works only at `full` data sharing.** It returns the sidecar's API
  request log, each Dapr call an app made with its status and error, not the
  application's own standard output. At the default `metadata` level the tool returns
  `DATA_SHARING_RESTRICTED`. That is policy, not a fault: do not retry it. Say the logs
  were not shared at this organization's data-sharing level, name the level, and continue
  with status and metrics. Reading the application's own output is not available over MCP
  yet.
- **Apps, agents and MCP servers are each backed by an identity** (an "App ID" in some
  APIs). Where a tool asks for or returns `appId`, it means that identity's name. Read it
  from the resource's `status.appIds` (the get tools include it). For an agent registered
  from your own code, it's the `appId` on its registry record.
- **One change at a time, and only with consent.** Everything in section 3 that is not a
  read mutates a live run.

## 3. A workflow run that failed

1. Find it: `catalyst_list_workflow_runs`, filtered to failed runs for the app's identity
   and a start-time window. Statuses are `running`, `completed`, `failed`, `terminated`,
   `suspended`, `canceled`.
2. Read it: `catalyst_get_workflow_run`. It returns the execution graph showing which
   step the run is on or failed at, which is the answer to "where is it stuck".
3. Diagnose at the failing step, not at the top. The run-level failure is almost always
   an activity's error re-surfaced. Quoting the top-level message alone tells the user
   their workflow failed, which they knew.

### An absent field is not an empty value

Catalyst enforces an organization-wide data-sharing level on every MCP response before it
leaves the platform. At the default `metadata` level you still get everything a diagnosis
usually needs — names, statuses, timestamps, durations and **error messages**. What is
**removed** is business data: a run's `input`, `output` and `customStatus`, and inline
component setting values. Removed means gone from the document, with nothing in its
place. Only an organization administrator can raise the level to `full`.

Never write "the workflow produced no output", "it returned nothing" or "the input was
empty" on the strength of a missing field. The user cannot detect that mistake from your
answer, and it sends them hunting for a bug in code that worked correctly.

| Response | Say |
| --- | --- |
| Field absent | "`output` was not shared at this organization's data-sharing level." |
| Field present, empty or null | "The run completed with an empty output." |
| Field present with a value | Report the value. |

Asking for the data does not defeat the level: a run listed with `includeData` still comes
back with the payload removed at `metadata`. Removal happens on the response, after the
upstream answered.

The same trap appears twice more. `customStatus` absent is not "the workflow never set
one", and an empty one proves a clean run only if the workflow is documented to set one
on failure and `output` agrees. And secrets are scrubbed at every level, `full` included —
`apiToken`, `appToken`, `token`, `apiKey`, `clientSecret`, `privateKey` — so a missing
`apiToken` never means the app has no token. Secret *references* survive, so "which secret
does this use" is still answerable.

Say the field was withheld, name the level, and stop there. The payload cannot be read
through this session at that level. Only an organization administrator can raise it, and
that is their decision: do not ask for it so that you can finish an answer, never forge a
data-sharing header, and do not try to route around the level. It is a deliberate control,
not an obstacle. Hand the user a console link to the run (section 8) so they can read it
themselves.

### When the failure is in the orchestration, not the activity

Two causes account for most workflow failures that look impossible — a run that failed
after a redeploy, threw on retry, replayed into a different branch, or duplicated an
effect nobody triggered twice:

- **Non-determinism inside the workflow function.** The body replays its history on every
  resumption, so it must reach identical decisions each time. Wall-clock reads, random
  values, generated ids, direct I/O, environment lookups and iterating an unordered
  collection to schedule work all break that. So does changing the shape of a workflow —
  reordering, adding or removing steps — while instances are in flight: the old history no
  longer matches the new code, and the run fails where they diverge rather than where the
  edit was made. Ask what was deployed and when, and compare that against the run's start
  time. Non-determinism *inside an activity* is not a defect; that is what activities are
  for.
- **Activities that are not idempotent.** Activity execution is at-least-once, and no
  configuration makes it exactly-once. A retry, a replay or a worker crash after the side
  effect committed but before the result reached history can run the same activity twice
  on the same input. If it charges a card, posts a message or increments a counter with no
  stable key and a conditional write, the duplicate is the bug and the retry is working as
  designed.

Check both before blaming infrastructure; both present as intermittent. The
`catalyst-workflow-determinism` and `catalyst-activity-idempotency` skills carry the full
hazard tables and the fixes.

### Acting on a run

These mutate. They are write tools, so they are absent from the tool list for a role that
cannot write: if one is missing, tell the user a write role is needed rather than hunting
for another route. Ask first, and state the consequence up front.

**State the consequence even when you cannot make the call yourself.** A user who will
act on your advice still needs to know a terminate cannot be undone. "I can't do this"
with no consequence attached has skipped the gate rather than passed it, and it reads as
permission because nothing in it suggests otherwise.

| Intent | Tool | Consequence to state |
| --- | --- | --- |
| Hold it | `catalyst_pause_workflow_run` / `catalyst_resume_workflow_run` | Reversible; history is kept. |
| Unblock a waiting run | `catalyst_raise_workflow_event` | Not idempotent: a run awaiting two events consumes two. |
| Retry from a point | `catalyst_rerun_workflow_run` | Creates a **new** run from the original's input, resuming from a chosen event. Both the event and an id for the new run are required — nothing generates the id. The original is untouched, so any id the user recorded still points at the failure. |
| Retry many from the same point | `catalyst_rerun_workflow_runs` | Starts new runs from several existing ones, all resuming from one event. The new runs execute for real, so side effects run again. Two calls: the first changes nothing and lists every run it would restart; show the user that list, and call again with the returned confirmation value only after they agree. |
| Stop it | `catalyst_terminate_workflow_run` | Irreversible: it cannot be resumed. History is kept. Confirm before calling. |
| Delete history | `catalyst_purge_workflow_runs` | Irreversible, and it destroys the evidence for this diagnosis. Always two calls: the first changes nothing and lists every run it would purge; show the user that list, and call again with the returned confirmation value only after they agree. Export first if the user may need the record: `catalyst_export_workflow_run`, which works only at `full` data sharing. |

Each of these names the run by its instance id and the app identity it belongs to. Read
the tool's schema for the exact argument names rather than guessing them.

If the workflow calls fail outright rather than returning nothing, the project has no
managed workflow store and the Workflows API is unavailable there. That is a project
setting, not a broken run.

## 4. An app, agent or MCP server that is not ready

Read `catalyst_get_app` (or `catalyst_get_agent`, `catalyst_get_mcp_server`), then work
down this list. The backing identity, with its own status and messages, is under
`status.appIds`. Stop at the first thing that explains it.

1. **Its own status and messages.** The vocabulary is `ready`, `pending`, `processing`,
   `provisioning`, `updating`, `deleting`, `deleted`, `error`, `unknown` — but the set is
   not closed and the API declares the field as a bare string, so report whatever value
   and message you were given, verbatim. Paraphrasing a platform error is how the detail
   that mattered gets lost. Agents report from a narrower set: `ready`, `error`, `pending`,
   or empty before their first reconcile.
2. **The components it depends on.** An app that cannot initialise a component does
   not come up. `catalyst_list_components`, reading each one's `scopes`, then section 6.
3. **Recent activity.** `catalyst_get_metrics` for that app shows, as request rates and
   error rates, whether it has served or sent anything recently. Then, if the organization
   shares at `full`, `catalyst_get_logs` for the sidecar's API calls and their errors.
4. **Whether a workflow app works end to end.** `catalyst_start_workflow` (a write) then
   `catalyst_get_workflow_run` separates the platform from the application.

Probing the app directly, publishing a test message, reading state back and streaming
inbound requests are not available over MCP yet. Say so rather than implying you ruled
them out.

A missing tunnel is an ordinary answer, not an error: `catalyst_list_app_tunnels` showing
none means no one is running that App ID from a local machine.

## 5. An agent that is not responding

The agent resource is an `Agent`: a Catalyst front for an agent **your** app runs,
identified by its endpoint and archive settings. It stops answering when your application
is down or its endpoint points somewhere unreachable.

Then check the runtime registry, which `catalyst_get_agent` returns when `appId` is also passed. The registry is the
project's runtime view and includes externally deployed OSS Dapr agents, so it separates
the two failures you cannot otherwise tell apart: a declared agent with no running
workload, versus a running workload nobody declared.

What to check:

- **The endpoint and the app.** The failure is nearly always the endpoint or the
  application behind it. Confirm the endpoint on the resource, and confirm the app's
  readiness and recent request rates with `catalyst_get_app` and `catalyst_get_metrics`.
- **Access to the MCP servers it uses.** A tool call the agent is not authorized for is
  refused, which looks like an agent that stops mid-task. Read the per-tool policy with
  `catalyst_get_access_policy`, and grant a missing tool with `catalyst_grant_access` only
  after the user agrees.
- **Token budgets.** A budget in `enforce` mode **rejects** requests once
  the window's allowance is spent, which looks like an unresponsive agent rather than an
  error. `catalyst_list_token_budgets` shows the limit, the spend in the current window
  and whether the cap is reached.

## 6. A component that will not connect

1. `catalyst_get_component`. Read the status, then the messages under
   `status.appIdStatus[]` — for a component that is where the reason nearly always is, per
   section 2. Inline setting values are withheld; secret references are shown, which is
   enough to tell whether it points at the secret you think it does.
2. If the organization shares at `full`, `catalyst_get_logs` for the scoped app carries
   the sidecar's failing calls with the underlying broker or store error. At the default
   level say it was not shared and rely on step 1.
3. If this is a second pub/sub or a second KV store in one project, read the limit before
   concluding anything. It is 1 per project on **every** plan, so the create normally fails
   no matter how often you retry — but the per-project limits carry a per-organization
   override, so read the live quota with `catalyst_get_usage` rather than asserting the 1.
   When it really is 1, say so as a platform default and describe the shape that works:
   one broker, many topics; one store, many keys. Do not call it a free-tier limit and do
   not suggest an upgrade — no plan upgrade raises it.

An MCP server is the same shape of problem with one extra trap: a **disabled** MCP server
reports `ready`, because disabled is a fully reconciled state. Its message says it is
disabled and loaded by no app. `ready` is not the answer to "is it serving" — read the
message before looking for a connection fault that does not exist. Enabling it is a
change, so propose it (an `catalyst_apply` of the read-back manifest with it enabled)
rather than making it.

Cluster-level diagnostics for a self-hosted Catalyst are not available over MCP yet.

## 7. When a call refuses

A refusal is not an outage, and it is not the failure you were sent to debug. Each one
names its own kind and carries an instruction addressed to you. Act on the instruction.
Improvising here usually means asking the user for an API key, which is never the right
next step — the client's sign-in flow supplies the token.

Two unrelated families, with different remedies. Do not conflate them.

**Connection.** `NOT_AUTHENTICATED`, `NO_ORG`, `ORG_MISMATCH`, `ORG_UNAVAILABLE`,
`CATALYST_NOT_ENABLED`. These carry a cause, an instruction written for you, and a
retryable flag. You never reached Catalyst: say so and stop, rather than reporting a
resource as broken on the strength of a call that never landed. The `catalyst-setup` skill
covers them. If the flag says retryable, wait briefly and retry once; if it does not, do
not retry at all, because a permanent refusal retried presents to the user as a hang.

**Data sharing.** These carry no retryable flag, so retrying is always wrong.

| Kind | What to do |
| --- | --- |
| `denied` | The whole response was withheld at this level. Report that, name the level, and link the console (section 8). Only an organization administrator can raise the level, and asking for that is not your move. |
| `no-policy` | A server-side gap — the operation has no reviewed data-sharing policy. Not something the caller can work around. Report it as a platform gap. |
| `unfilterable` | The response could not be parsed, usually because it was truncated at the size limit. Ask for fewer results per page. |

## 8. Link to the console

Give the user a link to the resource you are talking about, so they can look at what you
looked at. This is what makes a withheld field an honest answer rather than a dead end.

The console for the production server is `https://catalyst.diagrid.io`. If you cannot build a link you trust, give
the identifiers in plain text.

Use only these routes, appended to that host:

| Resource | Route |
| --- | --- |
| App | `/apps/details/:id` |
| Workflow run | `/workflows/:appId/:runId`, optionally `/:tab` |
| Agent | `/agents/:appId/:id` |
| MCP server | `/mcp-servers/:id` |
| Metrics for one app, agent or MCP server | `/metrics/appids/:id`, by identity |
| Metrics for the project | `/metrics`, or `/metrics/appids` |
| Project list | `/admin/projects` |

Two pages you may expect do not exist. There is **no project detail view** — only the
list, and `/admin/projects/:id/users` — and there is **no quota page** for a project or an
app. Linking to either one 404s.

The project is a query parameter, and there are two of them:

| What you are holding | Parameter | Example |
| --- | --- | --- |
| A name-like id | `?project=<name>` | `?project=default` |
| A numeric uid | `?projectId=<uid>` | `?projectId=165`, `prj-` prefix optional |

Neither falls back to the other, and `projectId` wins when both are present. Put a numeric
uid in `?project=` and the console looks for a project literally named `165`, fails, and
**silently shows the user's default project instead** — no error, just the wrong data
under the right heading, which is the worst possible outcome in the middle of a
diagnosis. If you cannot tell which form you are holding, omit the parameter.

**A link that 404s or lands on the wrong project is worse than no link.**

## 9. Report the diagnosis

Four things, in this order:

1. **The cause**, in one sentence, at the level the user can act on.
2. **The evidence** — the field or log line, quoted, with the call that produced it.
3. **What you could not see**, named: fields withheld by the data-sharing level, calls
   that refused, resources you had no access to. Silence here reads as "nothing else was
   relevant", which is a claim you have not checked.
4. **Where to look** — a console link built as in section 8, or the identifiers in plain
   text.

Then the fix, separately, and as a proposal if it mutates anything.

## Rules

- **Use only the Catalyst MCP tools for Catalyst.** Ignore any locally installed Diagrid
  CLI and its sign-in, even when it is signed in to a different organization. Never run
  it to read or change Catalyst state, and don't ask the user about it.
- **Never report an absent field as an empty value.** See section 3. It is the one error
  here the user cannot catch.
- **Stay in one project unless asked otherwise, and say which.** A question with no
  symptom is about the current project. Name it, name what you did not look at, and widen
  only on request — or when the question is plural or comparing, which needs more than one
  project by its nature. See section 1.
- **Do not guess a cause to fill a gap.** "The reason field is empty and the logs were not
  shared at this level" is a useful answer. An invented mechanism is not.
- **Do not mutate to investigate.** Terminating, purging, redeploying and recreating all
  destroy the state you are diagnosing. Read first, propose changes with their
  consequences stated, then wait for consent.
- **Do not write files.** Report in your answer, unless the user asked for a file.
- **Do not create a project.** Ever, in this skill. See section 1.
- **Do not print secrets** into a summary, a log, or a commit.
