---
name: catalyst-operate
description: Inspect a running Diagrid Catalyst project, read-only. Covers projects, App IDs, agents, MCP servers, components, workflow runs, logs and quotas. Use when asked what is deployed, what state it is in, or whether a limit is being hit.
---

# Inspect a running Catalyst project

Goal: end this skill able to say what exists, what state each thing is in, and which
call told you. A value you cannot attribute to a call you made is a guess, and to the
person reading your answer a guess is indistinguishable from a fact.

## 1. Start at the project, not at the resource

Call `catalyst_whoami` first. It reports the organization, its projects and its regions,
so you do not have to ask the user for something the platform already knows. Fall back
to the `diagrid` CLI when the MCP tools are absent or refuse. If neither works this is a
connection problem rather than an inspection problem — the `catalyst-setup` skill covers
it, and there is nothing useful to read without a credential.

### Answer about one project

An unqualified question — "my project", "is anything broken", "what is deployed" — is
about **one** project: the one the session is pointed at. Resolve it, name it in your
answer, and stay inside it.

`catalyst_whoami` and `diagrid project list` both return every project in the
organization. That is an inventory, not an instruction to read all of them. An
organization holds other people's projects, and each one you add multiplies every read in
section 3. Measured on an organization with ten projects, answering "is anything broken
in my project" by sweeping all of them spent well over half its calls on projects nobody
had asked about — and every one of those is a round trip whose result the answer then has
to carry.

**Which project is the current one.** The CLI has one, set by `diagrid project use
<project>`, and `diagrid project list` marks it with a leading `*`. That is the single
read where the table carries something `-o json` does not: the marker is absent from the
JSON, so take it from the table and read the JSON for everything else.

The MCP surface has no current project — every project-scoped tool takes the project as
an explicit argument. Take the argument's *name* from the tool's own schema rather than
assuming it: the two OpenAPI specs behind the surface disagree on capitalisation, so it
is `projectId` on the management operations and `ProjectId` on the controlplane ones, and
no operation names it plain `project`. That is the console's URL parameter, a different
system — section 6 covers it, and the two are easy to confuse.

An unqualified question means `default` on the MCP path. Say which project you chose and
why, in one line, so a wrong assumption is visible immediately rather than buried under
the reads that follow it.

**Widening the scope is a decision you state, not a rule you have broken.** "Anything
broken anywhere", "across the organization", a named second project — and any plural or
comparing question, which needs more than one project by its nature. "Which of my
projects uses the most quota" has no single call behind it: metrics are per project or
per App ID and `diagrid org usage` reports per scope and region, so ranking projects
means reading each one, and that is the correct answer rather than a violation. All of
these are worth one sentence first saying how many projects you are about to read.

`staging` and `prod` are usually Catalyst **environments**, not projects — separate host,
issuer and credentials, one login at a time, covered by `catalyst-setup`. "Compare
staging and prod" is that axis, not a second project name. Do not go looking for a
project called `prod`. If you cannot resolve the current
project, ask which one. Enumerating an organization to avoid asking a question costs the
user more than the question would have.

Then read the project, even when the question is about one App ID. The project is the
only object that names the managed infrastructure everything else sits on, and a large
share of "X is missing" turns out to be "X's backing store was never enabled here".

Every organization has a project named `default` with managed pub/sub, KV, workflow
store and agent infrastructure already attached. Use it. **Never create a project** —
a hand-made project that behaves differently is indistinguishable from a broken one to
the person asking for help.

Two project-scoped limits are fixed and never worth investigating:

| Limit | Value | What it means for a design |
| --- | --- | --- |
| `number_of_pubsubs_per_project` | 1 | Every topic shares one broker |
| `number_of_kvstores_per_project` | 1 | Every state key shares one store |

Both are 1 on every plan — free, enterprise and internal alike. A multi-agent topology
separates traffic by topic and by key prefix, not by broker or store. State it as a
platform default. Never present it as a free-tier limit or a reason to upgrade: no plan
upgrade raises it, and a user who upgrades on your advice has been misled.

These are plan limits with a per-organization override, not constants in the code. If a
live quota read shows a higher number, that organization has a negotiated limit and the
live value wins over this document. Read the budget rather than asserting the 1.

## 2. Attribute every value

Name the source of each answer — the MCP tool, or the CLI command.

The CLI session and the MCP connection are separate identities. They can be logged into
different organizations, and when they are, both return internally consistent answers
that disagree with each other. Attribution is the only thing that surfaces that.

## 3. The inventory

| To read | MCP tool | CLI |
| --- | --- | --- |
| Org, projects, regions | `catalyst_whoami` | `diagrid org current`, `diagrid org list` |
| Projects | `catalyst_list_projects`, `catalyst_get_project` | `diagrid project list`, `diagrid project get <name>` |
| App IDs, and any tunnel on them | `catalyst_list_appids`, `catalyst_get_appid` | `diagrid appid list`, `diagrid appid get <id> --all` |
| Agents, both kinds | `catalyst_list_agents`, `catalyst_get_agent` | `diagrid agent list`, `diagrid agent get <name>` |
| The runtime agent registry | `catalyst_get_agent` with the hosting App ID | `diagrid agent registry list` |
| MCP servers and their tools | `catalyst_list_mcp_servers`, `catalyst_get_mcp_server` | `diagrid mcpserver list`, `diagrid mcpserver get <name> --tools` |
| Components, pub/sub, KV, subscriptions, configurations, resiliency, HTTP endpoints | `catalyst_list_components`, `catalyst_get_component` | `diagrid component list`, `diagrid subscription list`, `diagrid pubsub list`, `diagrid kv list` |
| Workflow definitions and their activity graph | `catalyst_list_workflows`, `catalyst_get_workflow` | — |
| Workflow runs | `catalyst_list_workflow_runs`, `catalyst_get_workflow_run` | `diagrid workflow list`, `diagrid workflow get <run-id> --id <app-id>` |
| One region in detail | `catalyst_get_region` | `diagrid region get <region-id>` |
| Access policies — why a workflow or MCP call was refused | `catalyst_list_access_policies`, `catalyst_get_access_policy` | `diagrid workflow access-policy list`, `diagrid mcpserver access get <mcpserver>` |
| Dev tunnels open on a project | `catalyst_list_app_tunnels` | `diagrid appid get <id> --all` |
| Resource templates to start from | `catalyst_list_templates`, `catalyst_get_template` | — |
| Who changed what, and when | `catalyst_list_audit_events` | `diagrid audit list` |
| Request rates, error rates, quota consumption | `catalyst_get_metrics` | `diagrid org usage` (org-wide only) |
| Logs | `catalyst_get_logs` (full data sharing only) | `diagrid project logs`, `diagrid appid logs <id>` |

Two limits in that table are deliberate, not oversights:

- **`catalyst_get_logs` refuses at the default data-sharing level.** Log lines carry
  whatever the application chose to print, so at `metadata` the tool returns
  `DATA_SHARING_RESTRICTED` instead of a redacted, empty-looking log. That refusal is
  policy, not a fault: do not retry it. Fall back to the CLI, and only an org admin
  raising the level to `full` changes the answer.
- **The MCP surface reads; it does not manage.** There are no create, update or delete
  tools. Only workflow lifecycle calls write, and this skill does not use them. Anything
  the user wants changed goes through the CLI or the console, with their consent.

`-o json` on any CLI read gives you the full object; the default table view drops
fields. Read the JSON before concluding that a field does not exist. One read runs the other way:
`diagrid project list` marks the current project with a leading `*` in the table and not
at all in the JSON, so take that marker from the table and every other field from the
JSON. See section 1. `diagrid workflow
get` is the exception — it has no `--output` flag and always prints YAML, so `-o json`
there is an unknown flag rather than a formatting choice.

The App ID goes in `--id` throughout. `--app-id` lingers as a hidden deprecated alias on
`workflow`, `listen`, `dev` and the `call` verbs: it works, warns, and does not appear in
`--help`, so write `--id` and nobody has to take your word for it.

### Readiness

Projects, App IDs, MCP servers and every component kind report one of `ready`,
`pending`, `processing`, `provisioning`, `updating`, `deleting`, `deleted`, `error`,
`unknown`. Agents use a narrower set — `ready`, `error`, `pending`, or
empty before their first reconcile.

The set is not closed: an unmapped state passes through as whatever the platform called
it, and the API schema declares the field as a bare string with no enumeration. Report the
value you were given verbatim rather than rounding it to one of the nine.

One value lies if you read it alone: a **disabled MCP server reports `ready`**, with a
message saying it is disabled and loaded by no App ID. Disabled is a fully reconciled
state, so `ready` is correct — but "ready" is not the answer to "is it serving". Read the
message.

### Agents

An agent is a `diagrid agent` resource: a Catalyst front for an agent **your** app runs,
identified by `--endpoint` and the `--archive-*` flags. Say which resource you mean,
since the CLI also has a hidden `managed-agent` command that is not available to users;
do not report on it or suggest it.

`diagrid agent registry list` is the second thing, and often the one that answers the
question: it lists what is actually registered in the project's runtime, including
externally deployed OSS Dapr agents. A name in the registry but not in `agent list` is an
agent nobody declared to Catalyst; the reverse is a declaration whose workload is not
running.

## 4. Workflow runs

`catalyst_get_workflow_run` returns the execution graph — which step a run is on or
failed at. The CLI has no equivalent, so prefer it whenever the question is "where is it".

`diagrid workflow list` covers every App ID in the project and takes filters worth using
before you ask the user to narrow anything down:

- `--status` — `running`, `completed`, `failed`, `terminated`, `suspended`, `canceled`
- `--id`, `--name`, both repeatable
- `--start-after`, `--start-before`, `--end-after`, `--end-before`, RFC3339
- `--custom-status key=value`
- `--sort-by name|createdAt|startAt|endAt|status|appId` with `--order asc|desc`
- `--limit`, capped at 250

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

- `customStatus` absent is not "the workflow never set one", and a `--custom-status`
  filter matching nothing does not prove no run carries that key.
- Credentials are scrubbed at **every** level, `full` included — `apiToken`, `appToken`,
  `token`, `apiKey`, `clientSecret`, `privateKey`. A secret *reference* survives, so you
  can still answer "which secret does this use". An absent `apiToken` never means the App
  ID has no token.

Tell the user the field was withheld and why — then, before you stop, try the CLI. The
data-sharing level is applied by the MCP server to MCP responses; the CLI talks to the
management API and never passes through that filter. `diagrid workflow get <workflow-id>
--project <project> --id <app>` returns `input`, `output` and `customStatus` for the run
*and for every activity in its history*, with no flag and no change to the org's level. If
the CLI is unavailable too, hand them a console link so they can read it themselves — see
section 6.

Two conditions on that fallback. **Confirm the CLI is logged into the same organization** —
section 2 notes the CLI session and the MCP connection are separate identities that can sit
in different organizations, and a payload read from the wrong one is a worse answer than a
refusal. And **say which surface the value came from**, so the user can tell a CLI read from
a tool read.

Do not attempt to route around the *level* itself — do not forge a data-sharing header, and
do not ask an administrator to raise the org so you can finish an answer. It is a
deliberate control. Reading the same data, in the same organization, through a surface the
user is already entitled to use is not routing around it; it is using the product.

## 5. Quotas and metrics

`catalyst_get_metrics` reads request rates, error rates and quota consumption, scoped to
a project or to one App ID. Use it before proposing a design that adds resources —
headroom is cheaper to check than to discover.

`diagrid org usage` reports `used` and `limit` per key across the organization. Limits
are scoped, not global: `catalyst.per_cloud_region` and `catalyst.per_private_region` are
enforced **per region**, so usage arrives as one entry per scope and region. Summing
across regions, or reading one region's entry as the organization total, produces a wrong
headroom number.

Keys you will be asked about: `number_of_projects`, `number_of_appids`,
`number_of_connections`, `number_of_catalyst_subscriptions`,
`number_of_pubsubs_per_project`, `number_of_kvstores_per_project`,
`number_of_durable_agents`, `number_of_inbound_outbound_requests`,
`max_requests_per_second_per_appid`; and at organization scope `number_of_users`,
`number_of_apikeys`, `number_of_sso_connections`.

Read the numbers rather than reciting plan values from memory. Organizations get custom
limits, so a remembered figure is often wrong for the one in front of you. The two
exceptions are the pub/sub and KV counts in section 1, which are 1 everywhere.

For anything metrics cannot answer — a specific error, a stack trace, an ordering
question — go to the logs: `diagrid project logs --type app` for application output and
`--type dapr` for sidecar output. They fail differently, and the distinction is usually
the answer.

## 6. Link to the console

When you name a resource, give the user a link to it. It matters most where the
data-sharing level removed a payload: "the input was withheld at this organization's
data-sharing level, and here it is in the console" is a useful answer where both a lie
and a shrug are not.

Never hardcode the host — production, staging, development and local are all different
hosts. Do not hand-derive it either: **`diagrid web` opens the console for the environment
you are actually logged in to**, and `catalyst-setup` section 3 carries the API-host →
console-host mapping when you need the URL itself rather than a browser. If you cannot
establish the host confidently, give the identifiers in plain text rather than a broken
link.

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
list, and `/admin/projects/:id/users` — and there is **no quota page** for a project or
an App ID. Linking to either one 404s.

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
  instruction addressed to you; follow it. Never ask the user to paste a credential — the
  client's auth flow supplies those. Retry once only if the refusal says it is retryable;
  retrying a permanent refusal looks to the user like a hang.
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
- **Do not print secrets.** `--show-sensitive-values` exists on `diagrid component get`
  and `diagrid mcpserver get`; leave it off unless the user asked for the value, and never
  paste the result into a summary that outlives the answer.
