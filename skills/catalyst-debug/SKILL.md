---
name: catalyst-debug
description: Diagnose why something in Diagrid Catalyst is broken or stuck, then stop, kill, rerun or purge a workflow run. Covers a run that failed or hangs, an App ID not ready, an agent not answering, a component that will not connect.
---

# Diagnose a Catalyst failure

Goal: end this skill with a named cause and the line of evidence that proves it, or an
explicit statement of what you could not see and why. "Try restarting it" is not a
diagnosis, and neither is a plausible story with no read behind it.

## 1. Route by symptom

| Symptom | Start with | Then |
| --- | --- | --- |
| A workflow run failed, or hangs | `catalyst_get_workflow_run` | section 3 |
| An App ID never became ready | `catalyst_get_appid` | section 4 |
| An agent does not answer | `catalyst_get_agent`, `diagrid agent registry list` | section 5 |
| A component will not connect | `catalyst_get_component` | section 6 |
| Nothing named — "is anything broken?" | `diagrid project list`, then the project | below |

Prefer the `catalyst_*` MCP tools; fall back to the `diagrid` CLI, which is the only
route to logs. Say which one produced each finding — the CLI session and the MCP
connection are separate identities and can be pointed at different organizations, which
is invisible unless you attribute your evidence.

### One project, named

A question with no symptom in it — "is anything broken", "is my project healthy" — is
about **one** project: the one the session is pointed at. Resolve it, name it in your
answer, say which projects you did not look at, and stay inside it. An organization holds
other people's projects, and sweeping them turns a bounded diagnosis into a survey nobody
asked for.

The CLI's current project is marked with a leading `*` in `diagrid project list` — that
marker is in the table and not in `-o json`, so take it from the table. The MCP surface
has no current project at all, so an unqualified question means `default` there.

Widening is legitimate and is a decision you state first: "anything broken anywhere",
"across the organization", a named second project, or any plural or comparing question
("which of my projects uses the most quota") all need more than one project, and some
need every one of them. Say how many you are about to read before you start. Note that
`staging` and `prod` are usually Catalyst **environments**, not projects — a different
axis, one login at a time, covered by `catalyst-setup`. Do not go hunting for a project
by those names.

Read the project first, in every case: `catalyst_get_project`, or
`diagrid project get <name> -o json`. Managed workflow storage and agent infrastructure
are project settings, and when one is off the symptoms are indistinguishable from broken
resources. The project named `default` already has managed pub/sub, KV, workflow store
and agent infrastructure attached. **Never create a project** while debugging — a new
project with different settings turns one unexplained failure into two.

## 2. Rules of evidence

- **Status before logs.** Status tells you whether the platform ever got as far as running
  the thing. Logs only tell you what happened if it did. Opening with logs is how a "never
  scheduled" resource gets diagnosed as an application bug.
- **The reason is rarely at the top.** A status carries messages at up to three levels,
  and for anything scoped to App IDs the useful one is the deepest:

  | Where | Field | When it holds the answer |
  | --- | --- | --- |
  | Resource | `status.messages[].message` | Control-plane level failures |
  | Per region | `status.instances[].messages[].message` | One region reconciled and another did not |
  | Per App ID | `status.appIdStatus[].messages[].message` | **Components and MCP servers.** A component that fails to load is only reported as such by the sidecar of each scoped App ID, so this is usually the only place the reason exists |

  Two more error strings sit outside that structure and are easy to miss: a pub/sub's
  `status.topicError` and a KV store's `status.itemsError`.
- **`catalyst_get_logs` works only at `full` data sharing.** Log lines carry whatever
  the application chose to print, so at the default `metadata` level the tool returns
  `DATA_SHARING_RESTRICTED`. That is policy, not a fault: do not retry it. Run
  `diagrid project logs` or `diagrid appid logs` instead.
- **`-o json` on every CLI read.** The default table view drops fields, including the
  ones carrying the failure reason. A conclusion drawn from the table view is a
  conclusion drawn from a truncated object. One exception: `diagrid workflow get` has
  no `--output` flag at all and always prints YAML, so `-o json` there fails to parse
  rather than reformatting.
- **The App ID flag is `--id`, not `--app-id`.** On `workflow`, `listen`, `dev` and
  `call invoke/publish/state/bindings/conversation`, `--app-id` survives only as a
  hidden deprecated alias — it still works, prints a deprecation notice, and is absent
  from `--help`, so nobody can confirm it from the CLI. Write `--id`. (`diagrid call
  workflow ...`, a different subtree, does take `--app-id` as its real flag.)
- **Confirm a command before you quote it: `diagrid <noun> --help`.** The CLI moves.
  `agent` referred to the Catalyst-hosted Durable Agent in older versions and refers to a
  front for your own application in newer ones; `managed-agent` and `tokenbudget` are
  absent from older ones entirely. A flag quoted from the wrong version reads to the user
  as your mistake, and they stop trusting the rest of your answer.
- **One change at a time, and only with consent.** Everything in section 3 that is not a
  read mutates a live run.

## 3. A workflow run that failed

1. Find it: `catalyst_list_workflow_runs`, or
   `diagrid workflow list --status failed --id <app-id> --start-after <RFC3339>`.
   Statuses are `running`, `completed`, `failed`, `terminated`, `suspended`, `canceled`.
2. Read it: `catalyst_get_workflow_run`. It returns the execution graph showing which
   step the run is on or failed at, which is the answer to "where is it stuck" and has no
   CLI equivalent. `diagrid workflow get <run-id> --id <app-id>` is the fallback; it
   takes no `--output` flag and always prints YAML.
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
one". And credentials are scrubbed at every level, `full` included — `apiToken`,
`appToken`, `token`, `apiKey`, `clientSecret`, `privateKey` — so a missing `apiToken`
never means the App ID has no token. Secret *references* survive, so "which secret does
this use" is still answerable.

Say the field was withheld and why — then try the CLI before you stop. Withholding is
applied by the MCP server to MCP responses; `diagrid workflow get <workflow-id> --project
<project> --id <app>` does not pass through that filter, and returns `input`, `output` and
`customStatus` for the run and for every activity in its history. That is usually the
payload you came here for. Two conditions: confirm the CLI is logged into the same
organization — the CLI session and the MCP connection are separate identities and can
sit in different ones — and say which surface the value came from. Never forge a
data-sharing header, and never ask an administrator to raise the organization's level so
you can finish an answer.

If the CLI is unavailable too, hand over a console link to the run so the user can read it
themselves — see section 8. Do not try to route around the level itself; it is a deliberate
control, not an obstacle. Reading the same data through a surface the user already has is
not routing around it.

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

These mutate. Ask first, and state the consequence up front.

**State the consequence even when you cannot run the command yourself.** Handing the
user a terminate they will paste into their own shell is still the moment they need to
know it cannot be undone — and a session with no shell and no `catalyst_*` tools is the
common case, not the exception. "I can't run this, here is the command" with no
consequence attached has skipped the gate rather than passed it, and it reads as
permission because nothing in it suggests otherwise.

| Intent | MCP tool | CLI | Consequence to state |
| --- | --- | --- | --- |
| Hold it | `catalyst_pause_workflow_run` / `catalyst_resume_workflow_run` | `diagrid workflow pause --id <app> --instance-id <run-id>`, and `resume` with the same flags | Reversible; history is kept. |
| Unblock a waiting run | `catalyst_raise_workflow_event` | `diagrid workflow raise-event --id <app> --instance-id <run-id> --event-name <name> --data '<json>'` | Not idempotent: a run awaiting two events consumes two. |
| Retry from a point | `catalyst_rerun_workflow_run` | `diagrid workflow rerun --id <app> --instance-id <run-id> --event-id <n> --new-workflow-id <new-run-id>` | Creates a **new** run from the original's input, resuming from a chosen event. Both the event and an id for the new run are required — nothing generates the id. The original is untouched, so any id the user recorded still points at the failure. |
| Retry many from the same point | `catalyst_rerun_workflow_runs` | none | Starts new runs from several existing ones, all resuming from one event. The new runs execute for real, so side effects run again. Two calls: the first changes nothing and lists every run it would restart; show the user that list, and call again with the returned confirmation value only after they agree. |
| Stop it | `catalyst_terminate_workflow_run` | `diagrid workflow terminate --id <app> --instance-id <run-id>` | Irreversible: it cannot be resumed. History is kept. Confirm before calling. |
| Delete history | `catalyst_purge_workflow_runs` | `diagrid workflow purge --id <app> --instance-id <run-id>`, or `--bulk` with `--status`/`--name`/`--older-than` filters | Irreversible, and it destroys the evidence for this diagnosis. Over MCP it is always two calls: the first changes nothing and lists every run it would purge; show the user that list, and call again with the returned confirmation value only after they agree. Export first if the user may need the record: `catalyst_export_workflow_run`, which works only at `full` data sharing, or `diagrid workflow archive export`. A single purge takes `-y` and `--bulk` takes `--approve` to skip the confirmation it would otherwise ask for — both are purge-only, neither exists on `terminate`, and neither is yours to reach for on the user's behalf. |

**The CLI column is the one that works in a session with no `catalyst_*` tools**, which is
most of them. Do not report a run as unstoppable because the MCP tool is absent.

**Every lifecycle verb takes the run in `--instance-id`. `get` is the only one that takes
it positionally.** `diagrid workflow get <run-id> --id <app>` has no `--instance-id` at
all, and `terminate`, `pause`, `resume`, `rerun`, `raise-event` and `purge` accept no
positional argument — carrying `get`'s shape across to any of them fails with
`required flag(s) "instance-id" not set`, or on the unexpected argument. It is the same
trap as `workflow start`, which also requires `--instance-id`. Getting this wrong on
`terminate` is the worst place to get it wrong: the user reads a plausible command,
runs it, sees an error, and no longer trusts the diagnosis it came with.

If `workflow list` or `workflow get` fails outright rather than returning nothing, the
project has no managed workflow store and the Workflows API is unavailable there. That is
a project setting, not a broken run.

## 4. An App ID that is not ready

Read `catalyst_get_appid`, or `diagrid appid get <id> --all -o json`, then work down this
list. Stop at the first thing that explains it.

1. **Its own status and messages.** The vocabulary is `ready`, `pending`, `processing`,
   `provisioning`, `updating`, `deleting`, `deleted`, `error`, `unknown` — but the set is
   not closed and the API declares the field as a bare string, so report whatever value
   and message you were given, verbatim. Paraphrasing a platform error is how the detail
   that mattered gets lost. Agents report from a narrower set: `ready`, `error`, `pending`,
   or empty before their first reconcile.
2. **The components it depends on.** An App ID that cannot initialise a component does
   not come up. `catalyst_list_components`, then section 6.
3. **The sidecar's own output.** `diagrid project logs --ids <id> --type dapr` carries
   component initialisation and connection errors; `--type app` carries your
   application's output. They fail differently and the distinction is usually the answer.
4. **Recent activity.** `diagrid appid get <id> --include-activity` and
   `diagrid appid logs <id> -t 50`.
5. **Whether requests reach it at all.** `diagrid listen --id <app-id> --invoke <method>`
   streams inbound requests to your terminal without deploying application code. If
   nothing arrives the problem is upstream of the app; if requests arrive and it still
   fails, it is not.
6. **Whether the API path works from outside.** `diagrid call invoke`, `call publish`,
   `call state`, `call bindings` and `call conversation` each exercise one API directly
   and separate the platform from the application.

A missing tunnel is an ordinary answer, not an error: `catalyst_get_appid` reporting no
tunnel means no local `diagrid dev` or `diagrid listen` session is attached.

## 5. An agent that is not responding

Establish which resource you are looking at before reading anything. They fail for
entirely different reasons and their names are one word apart.

| | `diagrid agent` | `diagrid managed-agent` |
| --- | --- | --- |
| What it is | A Catalyst front for an agent **you** run | A Catalyst-hosted Durable Agent |
| Identifying flags | `--endpoint`, `--archive-binding-name`, `--archive-completed/-failed/-terminated` | `--llm-provider`, `--llm-model`, `--sandbox`, `--github-app-id`, `--git-repo` |
| It stops answering when | Your application is down, or `--endpoint` points somewhere unreachable | Its conversation component, sandbox, tools or token budget stop it |
| Availability | Generally available | Restricted; hidden from help and gated at execution |

Never write "create an agent" or "the agent is broken" without qualifying which.
`catalyst_list_agents` returns both kinds — read the type on the record rather than
guessing from the name.

Then check `diagrid agent registry list`. The registry is the project's runtime view and
includes externally deployed OSS Dapr agents, so it separates the two failures you cannot
otherwise tell apart: a declared agent with no running workload, versus a running
workload nobody declared.

By resource:

- **`agent`** — the failure is nearly always the endpoint or the application behind it.
  Confirm the endpoint on the resource, confirm the app is up and reachable, then
  `diagrid listen --id <app-id>` to see whether the request even arrives.
- **`managed-agent`** — check, in order: the conversation component named by
  `--llm-component` or created by `--llm-provider`, because a rejected or expired provider
  key presents as an agent that silently stops answering; whether `--sandbox` is set on an
  agent whose tools need it, and whether the region supports sandboxing at all; the
  per-tool authorization on any MCP server it uses — read it with
  `catalyst_get_access_policy` or `diagrid mcpserver access get <mcpserver>`, and grant a
  missing tool with `catalyst_grant_access` only after the user agrees; then
  the run history, `diagrid managed-agent runs list --agent <name> --thread <id>`.
  `runs` is a command group, not a command — `list`, `show`, `cancel` and `tail` sit
  under it, and each requires both `--agent` and `--thread`. All of it is restricted to
  Diagrid accounts, per the availability row above.
- **Token budgets** apply to either. A budget in `enforce` mode **rejects** requests once
  the window's allowance is spent, which looks like an unresponsive agent rather than an
  error. Read them with `catalyst_list_token_budgets`, which shows the limit, the spend in
  the current window and whether the cap is reached, or `diagrid tokenbudget list` —
  functional, but hidden from help and absent from older CLI versions.

## 6. A component that will not connect

1. `catalyst_get_component`, or
   `diagrid component get <name> --include-activity -o json`. Read the status, then the
   messages under `status.appIdStatus[]` — for a component that is where the reason nearly
   always is, per section 2. Inline setting values are withheld over MCP; secret references
   are shown, which is enough to tell whether it points at the secret you think it does.
2. `diagrid project logs --ids <id> --type dapr`. Component initialisation failures
   land here, named, with the underlying broker or store error attached.
3. Check the credential without printing it. `--show-sensitive-values` exists on
   `diagrid component get`; leave it off unless the user asks, and never paste the result
   into a summary that outlives the answer.
4. If this is a second pub/sub or a second KV store in one project, read the limit before
   concluding anything. It is 1 per project on **every** plan, so the create normally fails
   no matter how often you retry — but the per-project limits carry a per-organization
   override, so read the live quota rather than asserting the 1. When it really is 1, say
   so as a platform default and describe the shape that works: one broker, many topics; one
   store, many keys. Do not call it a free-tier limit and do not suggest an upgrade — no
   plan upgrade raises it.

An MCP server is the same shape of problem with one extra trap: a **disabled** MCP server
reports `ready`, because disabled is a fully reconciled state. Its message says it is
disabled and loaded by no App ID. `ready` is not the answer to "is it serving" — read the
message before looking for a connection fault that does not exist. The remedy is
`diagrid mcpserver enable`, which is a change, so propose it rather than running it.

`diagrid diagnose` collects Catalyst diagnostics, but only from a Kubernetes cluster
running the Catalyst operator. It is not a tool for a cloud project.

## 7. When a call refuses

A refusal is not an outage, and it is not the failure you were sent to debug. Each one
names its own kind and carries an instruction addressed to you. Act on the instruction.
Improvising here usually means asking the user for an API key, which is never the right
next step — the client's auth flow supplies credentials.

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
| `denied` | The whole response was withheld at this level. No MCP call gets it — but the CLI does not pass through this filter, so try `diagrid workflow get` (see section 3) before reporting a dead end. Only an organization administrator can raise the level, and asking for that is not your move. |
| `no-policy` | A server-side gap — the operation has no reviewed data-sharing policy. Not something the caller can work around. Report it as a platform gap. |
| `unfilterable` | The response could not be parsed, usually because it was truncated at the size limit. Ask for fewer results per page. |

## 8. Link to the console

Give the user a link to the resource you are talking about, so they can look at what you
looked at. This is what makes a withheld field an honest answer rather than a dead end.

Never hardcode the host — production, staging, development and local are different hosts.
Do not hand-derive it either: **`diagrid web` opens the console for the environment you are
logged in to**, and `catalyst-setup` section 3 carries the mapping when you need the URL
itself. If you cannot establish the host confidently, give the identifiers in plain text
rather than a broken link.

Use only these routes:

| Resource | Route |
| --- | --- |
| App ID | `/apps/details/:id` |
| Workflow run | `/workflows/:appId/:runId`, optionally `/:tab` |
| Agent, either kind | `/agents/:appId/:id` |
| MCP server | `/mcp-servers/:id` |
| Metrics for one App ID | `/metrics/appids/:id` |
| Metrics for the project | `/metrics`, or `/metrics/appids` |
| Project list | `/admin/projects` |

Two pages you may expect do not exist. There is **no project detail view** — only the
list, and `/admin/projects/:id/users` — and there is **no quota page** for a project or an
App ID. Linking to either one 404s.

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

- **Never report an absent field as an empty value.** See section 3. It is the one error
  here the user cannot catch.
- **Stay in one project unless asked otherwise, and say which.** A question with no
  symptom is about the current project. Name it, name what you did not look at, and widen
  only on request — or when the question is plural or comparing, which needs more than one
  project by its nature. See section 1.
- **Do not guess a cause to fill a gap.** "The reason field is empty and the dapr logs
  show nothing in that window" is a useful answer. An invented mechanism is not.
- **Do not mutate to investigate.** Terminating, purging, redeploying and recreating all
  destroy the state you are diagnosing. Read first, propose changes with their
  consequences stated, then wait for consent.
- **Do not write files.** Report in your answer, unless the user asked for a file.
- **Do not create a project.** Ever, in this skill. See section 1.
- **Do not print secrets** into a summary, a log, or a commit.
