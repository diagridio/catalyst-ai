---
name: catalyst-operate
description: Inspect a running Diagrid Catalyst project, read-only — projects, apps, agents, MCP servers, components, workflow runs, logs and quotas. Use for what is deployed and its state, a limit being hit, or a pasted run or log response and whether it is clean.
---

# Inspect a running Catalyst project

Goal: end this skill able to say what exists, what state each thing is in, and which
call told you. A value you cannot attribute to a call you made is a guess, and to the
person reading your answer a guess is indistinguishable from a fact.

Everything here goes through the Catalyst MCP server, the `catalyst_*` tools. If they are
missing or refuse with `NOT_AUTHENTICATED`, this is a connection problem rather than an
inspection problem: the `catalyst-setup` skill covers it, and there is nothing useful to
read until the user has signed in. Do not guess a project's state to fill the gap.

## 1. Start at the project, not at the resource

Call `catalyst_whoami` first. It reports the organization, its projects and its regions,
so you do not have to ask the user for something the platform already knows.

### Answer about one project

An unqualified question — "my project", "is anything broken", "what is deployed" — is
about **one** project. Resolve it, name it in your answer, and stay inside it.

`catalyst_whoami` and `catalyst_list_projects` both return every project in the
organization. That is an inventory, not an instruction to read all of them. An
organization holds other people's projects, and each one you add multiplies every read in
section 3. Measured on an organization with ten projects, answering "is anything broken
in my project" by sweeping all of them spent well over half its calls on projects nobody
had asked about — and every one of those is a round trip whose result the answer then has
to carry.

**There is no current project.** Every project-scoped tool takes the project as an
explicit argument, so pass it on every call. Take the argument's *name* from the tool's
own schema rather than assuming it: the two OpenAPI specs behind the surface disagree on
capitalisation, so it is `projectId` on the management operations and `ProjectId` on the
controlplane ones, and no operation names it plain `project`. That is the console's URL
parameter, a different system — section 6 covers it, and the two are easy to confuse.

An unqualified question means `default`. Say which project you chose and why, in one
line, so a wrong assumption is visible immediately rather than buried under the reads
that follow it.

**Widening the scope is a decision you state, not a rule you have broken.** "Anything
broken anywhere", "across the organization", a named second project — and any plural or
comparing question, which needs more than one project by its nature. "Which of my
projects uses the most quota" has no single call behind it: metrics are per project or
per app, agent or MCP server, and `catalyst_get_usage` reports per scope and region, so
ranking projects means reading each one, and that is the correct answer rather than a
violation. All of these are worth one sentence first saying how many projects you are
about to read.

"Compare staging and prod" is not a comparison of two projects in one organization, so
do not go looking for a project called `prod`. If you cannot resolve which project is
meant, ask. Enumerating an organization to avoid asking a question costs the user more
than the question would have.

Then read the project with `catalyst_get_project`, even when the question is about one
app. The project is the only object that names the managed infrastructure everything else
sits on, and a large share of "X is missing" turns out to be "X's backing store was never
enabled here".

Every organization has a project named `default` with managed pub/sub, KV, workflow
store and agent infrastructure already attached. Use it. **Never create a project** — a
hand-made project that behaves differently is indistinguishable from a broken one to the
person asking for help.

Two project-scoped limits matter for designs:

| Limit | Default | What it means for a design |
| --- | --- | --- |
| `number_of_pubsubs_per_project` | 1 | Every topic shares one broker |
| `number_of_kvstores_per_project` | 1 | Every state key shares one store |

The default is 1 on every plan, and confirming it is one call to `catalyst_get_usage`. A
multi-agent topology separates traffic by topic and by key prefix, not by broker or
store. State it as a platform default. Never present it as a free-tier limit or a reason
to upgrade: no plan upgrade raises it, and a user who upgrades on your advice has been
misled. The limits carry a per-organization override, so if the live read shows a higher
number, the live value wins over this document.

## 2. Attribute every value

Name the tool that produced each answer. A value you cannot attribute to a call you made
is a guess.

## 3. The inventory

| To read | Tool |
| --- | --- |
| Org, projects, regions | `catalyst_whoami` |
| Projects | `catalyst_list_projects`, `catalyst_get_project` |
| Apps, and any tunnel on them | `catalyst_list_apps`, `catalyst_get_app` |
| Agents, declared and runtime-registered | `catalyst_list_agents`, `catalyst_get_agent` |
| The runtime agent registry | `catalyst_get_agent`, with `appId` also passed, for the registry record |
| MCP servers and their tools | `catalyst_list_mcp_servers`, `catalyst_get_mcp_server` |
| Components, pub/sub, KV, subscriptions, configurations, resiliency, HTTP endpoints | `catalyst_list_components`, `catalyst_get_component` |
| Workflow definitions and their activity graph | `catalyst_list_workflows`, `catalyst_get_workflow` |
| Workflow runs | `catalyst_list_workflow_runs`, `catalyst_get_workflow_run` |
| One region in detail | `catalyst_get_region` |
| Access policies — why a workflow or MCP call was refused | `catalyst_list_access_policies`, `catalyst_get_access_policy` |
| Dev tunnels open on a project | `catalyst_list_app_tunnels` |
| Resource templates to start from | `catalyst_list_templates`, `catalyst_get_template` |
| Who changed what, and when | `catalyst_list_audit_events` |
| Request rates, error rates, quota consumption | `catalyst_get_metrics` |
| Plan limits and how much of each is used | `catalyst_get_usage` |
| Token budgets and their spend | `catalyst_list_token_budgets` |
| Logs | `catalyst_get_logs` (full data sharing only) |

Three limits in that table are deliberate, not oversights:

- **`catalyst_get_logs` refuses at the default data-sharing level.** Log lines carry
  whatever the application chose to send, so at `metadata` the tool returns
  `DATA_SHARING_RESTRICTED` instead of a redacted, empty-looking log. That refusal is
  policy, not a fault: do not retry it. Say so, name the level, and stop. Only an org
  admin raising the level to `full` changes the answer. The tool reads the sidecar's API
  request log, which is each Dapr call with its status and error, not the application's
  own standard output. Reading the application's own output is not available over MCP
  yet.
- **This skill only reads, even where the MCP server can write.** For a role that allows
  writes, the server also has `catalyst_apply`, `catalyst_delete_resource` and workflow-run
  actions (see `catalyst-deploy` and `catalyst-debug`). This skill uses none of them.
  Anything the user wants changed goes to those skills, with their consent.
- **Some reads have no tool.** Invoking an app, publishing to a topic, reading or writing
  state, and streaming inbound requests are not available over MCP yet. Say that in one
  line; do not substitute a guess.

Apps, agents and MCP servers are each backed by an identity (an "App ID" in some APIs).
Where a tool asks for or returns `appId`, it means that identity's name. Read it from the
resource's `status.appIds` (the get tools include it). For an agent registered from your
own code, it's the `appId` on its registry record.

### Readiness

Projects, apps, MCP servers and every component kind report one of `ready`,
`pending`, `processing`, `provisioning`, `updating`, `deleting`, `deleted`, `error`,
`unknown`. Agents use a narrower set — `ready`, `error`, `pending`, or
empty before their first reconcile.

The set is not closed: an unmapped state passes through as whatever the platform called
it, and the API schema declares the field as a bare string with no enumeration. Report the
value you were given verbatim rather than rounding it to one of the nine.

One value lies if you read it alone: a **disabled MCP server reports `ready`**, with a
message saying it is disabled and loaded by no app. Disabled is a fully reconciled
state, so `ready` is correct — but "ready" is not the answer to "is it serving". Read the
message.

### Agents

An agent is an `Agent` resource: a Catalyst front for an agent **your** app runs,
identified by its endpoint and its archive settings. Say `agent` or `app`, never leave
it ambiguous: they are different resources.

`catalyst_get_agent` returns the runtime registry record when `appId` is also passed, and that is often the one
that answers the question: the registry lists what is actually registered in the project's
runtime, including externally deployed OSS Dapr agents. A name in the registry but not in
`catalyst_list_agents` is an agent nobody declared to Catalyst; the reverse is a
declaration whose workload is not running.

## 4. Workflow runs

`catalyst_get_workflow_run` returns the execution graph — which step a run is on or
failed at. Use it whenever the question is "where is it".

`catalyst_list_workflow_runs` covers every app in the project and takes filters worth
using before you ask the user to narrow anything down. Read its schema for the exact
names; they include the run's status (`running`, `completed`, `failed`, `terminated`,
`suspended`, `canceled`), the app identity, the workflow name, and start and end time
windows. `catalyst_list_workflows` and `catalyst_get_workflow` describe the definitions
and their activity graph.

Workflow reads require the project's managed workflow store. On a project without it,
these calls do not return an empty history — they fail or report the API as unsupported.
Check the project before reporting "no runs".

### An absent field is not an empty value

Catalyst enforces an organization-wide data-sharing level on every MCP response before
it leaves the platform. The default level is `metadata`, and it shares names, statuses,
timestamps, durations and error messages. It **removes** business data — a workflow run's
`input`, `output` and `customStatus`, and inline component setting values. Removed means
gone from the document, with nothing left in its place. `full` is the other level, and
only an organization administrator can raise it.

Never write "the workflow produced no output", "the input was empty" or anything else
that turns a missing field into a factual claim about the run. The user cannot detect
that error from your answer, and it sends them looking for a bug in code that worked.

| Response | Say |
| --- | --- |
| Field absent | "`output` was not shared at this organization's data-sharing level." |
| Field present, empty or null | "The run completed with an empty output." |
| Field present with a value | Report the value. |

The same trap applies twice more:

- `customStatus` absent is not "the workflow never set one", and a filter on it matching
  nothing does not prove no run carries that key. Even once fetched, an empty
  `customStatus` proves a clean run only if the workflow is documented to set one on
  failure and the `output` agrees. Do not certify a run clean on a missing field.
- Secrets are scrubbed at **every** level, `full` included — `apiToken`, `appToken`,
  `token`, `apiKey`, `clientSecret`, `privateKey`. A secret *reference* survives, so you
  can still answer "which secret does this use". An absent `apiToken` never means the app
  has no token. No read tool returns an app's token; only `catalyst_get_app_connection`
  does (see `catalyst-develop` section 3).

Tell the user the field was withheld and why: "it was not shared at this organization's
data-sharing level (`metadata`)". Name the level. The payload cannot be read through this
session at that level, and only an organization administrator can raise it to `full`;
raising it is their decision, so do not ask an administrator to change it so that you can
finish an answer, and never try to route around the level. It is a deliberate control.
If the user wants the payload, the console link in section 6 is where they can read it
themselves.

## 5. Quotas and metrics

`catalyst_get_metrics` reads request rates, error rates and quota consumption, scoped to
a project or to one app, agent or MCP server. Use it before proposing a design that adds
resources — headroom is cheaper to check than to discover.

`catalyst_get_usage` reports `used` and `limit` per key across the organization. Limits
are scoped, not global: `catalyst.per_cloud_region` and `catalyst.per_private_region` are
enforced **per region**, so usage arrives as one entry per scope and region. Summing
across regions, or reading one region's entry as the organization total, produces a wrong
headroom number.

`number_of_appids` is the Identities quota: one per app, agent and MCP server, summed
across every project in the organization, per region.

Keys you will be asked about: `number_of_projects`, `number_of_appids`,
`number_of_connections`, `number_of_catalyst_subscriptions`,
`number_of_pubsubs_per_project`, `number_of_kvstores_per_project`,
`number_of_inbound_outbound_requests`,
`max_requests_per_second_per_appid`; and at organization scope `number_of_users`,
`number_of_apikeys`, `number_of_sso_connections`.

Read the numbers rather than reciting plan values from memory. Organizations get custom
limits, so a remembered figure is often wrong for the one in front of you. The two
exceptions are the pub/sub and KV counts in section 1, which are 1 everywhere.

For anything metrics cannot answer — a specific error, an ordering question — go to
`catalyst_get_logs`, which shows each Dapr API call an app made through its sidecar with
its status and any error. It works only at `full` data sharing; at the default level say
so and stop. The application's own standard output is not available over MCP yet.

## 6. Link to the console

When you name a resource, give the user a link to it. It matters most where the
data-sharing level removed a payload: "the input was withheld at this organization's
data-sharing level, and here it is in the console" is a useful answer where both a lie
and a shrug are not.

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
list, and `/admin/projects/:id/users` — and there is **no quota page** for a project or
an app. Linking to either one 404s.

### The project is a query parameter, and there are two of them

| What you are holding | Parameter | Example |
| --- | --- | --- |
| A name-like id | `?project=<name>` | `?project=default` |
| A numeric uid | `?projectId=<uid>` | `?projectId=165`, `prj-` prefix optional |

Neither falls back to the other, and `projectId` wins when both are present. Put a
numeric uid in `?project=` and the console looks for a project literally named `165`,
fails, and **silently shows the user's default project instead** — no error, just the
wrong data under the right heading. If you cannot tell which form you are holding, omit
the parameter rather than risk it.

**A link that 404s or lands on the wrong project is worse than no link.** Emit one only
with a route from the table above and an identifier whose form you are sure of.

## Rules

- **This skill only reads.** Do not create, update, delete, start, terminate, purge or
  rerun anything. Inspecting a system is not permission to change it, and a caller who
  asked "what state is this in" has not asked for a repair.
- **Do not write files.** Report findings in your answer. A file the user did not ask for
  is a side effect they have to clean up.
- **Never report an absent field as an empty value.** See section 4. It is the one error
  here the user cannot catch.
- **Link only what you can link correctly.** A verified route, and a project parameter
  whose form you are sure of, or plain identifiers instead. A link that lands on the
  wrong project fails silently and looks right. See section 6.
- **Act on a refusal's instruction.** A refused call names its own kind and carries an
  instruction addressed to you; follow it. Never ask the user to paste a token or key —
  the client's sign-in flow supplies those. Retry once only if the refusal says it is
  retryable; retrying a permanent refusal looks to the user like a hang.
- **Stay in one project unless asked otherwise — and widen when asked.** An unqualified
  question is about the current project; name it, name what you did not look at, and stay
  there. A plural or comparing question is the exception and needs every project it
  names. Reading an organization's other projects to
  answer a question about one of them is slow, mostly about resources the user did not
  ask about, and on a shared organization it reports on other people's work. See
  section 1.
- **Read the project before reporting anything missing.** Managed workflow storage and
  agent infrastructure are project settings, and their absence looks exactly like an
  empty system.
- **Do not print secrets.** Component reads withhold inline setting values at the default
  level; never paste a secret's value, if you are ever given one, into a summary that
  outlives the answer.
