---
name: catalyst-deploy
description: Move an application from a laptop into Diagrid Catalyst. Covers budgeting headroom before designing a topology, declaring the App ID first, attaching connections and topic subscriptions, the order these must be created in, and proving each one came up.
---

# Get an application running in Catalyst

Goal: end this skill with a named resource the user can open in the console, whose
readiness you confirmed by reading it back rather than by watching a create command
succeed. A create that returns is a create that was accepted; it is not a thing that
works.

Order matters throughout, and not as a matter of taste — several of the constraints below
leave a resource *permanently* broken when taken out of order, with no error at the moment
you got it wrong. Read sections 1 and 3 before creating anything.

## Two routes: `catalyst_apply` or the CLI

If `catalyst_apply` is in your tool list, deploy with it. It is the MCP equivalent of
`diagrid apply -f`: you send manifests, and it creates what does not exist and replaces
what does. It is only listed for users whose role can write, so if it is missing, that is
the user's role, not a broken connection: use the CLI commands in the rest of this skill.

- **Send one application's resources together, with one exception.** Within a call it
  applies them in a fixed order: project, configurations, components and subscriptions,
  agents and MCP servers, apps and App IDs, then access policies and token budgets.
  That puts a subscription *before* the App IDs, but section 3 requires the App IDs a
  subscription scopes to to exist first. So send subscriptions in a second call, after
  the call that created their App IDs. Across calls, the order is yours to get right.
- **Call `catalyst_get_resource_schema` before writing a kind for the first time.** Do
  not guess field names.
- **Run it with `dry_run` first** and show the user what will be created or replaced.
- **Replace means replace.** To change an existing resource, read it with its get tool,
  change it, and send it back whole: a field left out is dropped.
- **Settings read back without a value are refused, not erased.** At the default
  `metadata` data-sharing level a read withholds inline setting values, such as a
  component's `spec.metadata`. Sent back as they are, the call fails with *"nothing was
  applied"* and lists each setting. Ask the user for each value, or better, point the
  setting at a secret with `secretKeyRef` so the value never passes through the
  conversation. Never delete the entry to get past the check: that removes the stored
  setting on replace.
- **The first failure stops the batch.** Everything after it is reported as not
  attempted. Fix that one and send the rest again; applying the same manifests twice is
  safe.
- **Accepted is not ready.** Read each resource back (section 5), exactly as after a CLI
  create.

Deleting goes through `catalyst_delete_resource`, never as a side effect of a deploy.
It cannot be undone. **Every kind except a project is deleted on the first call**, so
ask the user before you call it, and name what goes with the resource. A project is the
one exception: the first call returns a preview of everything it would remove, plus a
confirmation token. Show the user that preview, and call again with the token only
after they agree.

## 1. Budget the headroom first

Do this before designing a topology, not after building one. Every cap here is enforced
at create time, so the cost of discovering one late is a redesign rather than a retry.

- `catalyst_get_usage`, or `diagrid org usage`, reports `used` and `limit` per key.
- `catalyst_get_metrics` reads request rates, error rates and consumption for a project
  or a single App ID.

Read the numbers. Do not recite remembered plan values — organizations get custom limits,
so a figure from memory is often wrong for the one in front of you.

### The scope of each cap is the part people get wrong

| Cap | Scope | Consequence for a design |
| --- | --- | --- |
| `number_of_appids` | Per region, **summed across every project in the organization** | Splitting a topology across two projects does not buy more |
| `number_of_connections` | Per region, org-wide | Same. A connection is a component |
| `number_of_catalyst_subscriptions` | Per region, org-wide | Same |
| `number_of_projects` | Per region | Low, and easy to spend by accident — see section 7 |
| `number_of_pubsubs_per_project` | Per project | **1 on every plan** |
| `number_of_kvstores_per_project` | Per project | **1 on every plan** |

Two of those deserve stating out loud because they change what you build:

**Apps, agents and MCP servers all consume the same allowance.** They are one namespace
of App IDs under the hood. The rejection says so, and names the breakdown: *"has reached
the maximum of N resources for its ... region ..., currently using N (...). Each agent,
MCP server, and app counts toward this limit."* A coordinator plus four specialists plus
one MCP server is six of them. The remedy in that message is to contact Diagrid support,
not to change plan — do not tell the user an upgrade fixes it without checking.

**One managed pub/sub and one managed KV store per project, on every plan**. It is a platform default rather than a free-tier
restriction, and no plan upgrade raises it. (A negotiated per-organization override does
exist, so if a live quota read disagrees with the 1, trust the live read.) A multi-service
or multi-agent design therefore separates
traffic by **topic** on the one broker and by **key prefix** in the one store. Design for
that from the start; presenting it as a limitation to work around produces a design that
cannot be built. Note also that creating a managed pub/sub or KV store spends a
*connection* slot as well as its per-project slot.

Reference figures for the free plan, per cloud region, useful as a sanity check on what
`org usage` returns rather than as a substitute for reading it — 3 projects, 10 App IDs,
21 connections, 10 subscriptions, 100,000 requests, and 500 requests
per second per App ID.

Finally, headroom is not the only per-region property. Managed pub/sub, managed KV and
the Workflows API are **regional capabilities**, and a region that lacks one gives you a
project where that API simply is not available. If workflow calls must work, confirm the
region supports them before you build on them.

There is **no quota page in the console.** Do not link to one; report the numbers.

## 2. The App ID comes first, because it is the identity

An App ID is not a deployment artifact. It is the identity the sidecar runs under: it
owns the API token, it is what components are scoped to, it is what a subscription
delivers to, and it is what a local connection attaches to. Nothing can reference an
application that has no App ID, which is why every ordering constraint in section 3
starts from it.

**Names are unique across three resource types in a project.** Creating an agent whose
name is taken by an app fails with *"the name ... is already in use in project ...; App,
Agent and MCP server names must be unique within a project"*. Pick the name once, for the
right resource type, and check `diagrid app list` and `diagrid agent list` before you do.

### Which noun to create

| Deploying | Create | Who owns the App ID |
| --- | --- | --- |
| Your own application | `diagrid app create <name>` | The App you just made |
| An agent whose code you run yourself | `diagrid agent create <name>` | The Agent provisions and manages its own |
| An MCP server | `diagrid mcpserver create <name>` | The MCP server, likewise |

`diagrid appid` still works and is the lower-level view, but on v1.66.0 it is hidden from
help in favour of `app`, `agent` and `mcpserver`. The two are not flag-compatible —
`app create` takes `--endpoint` and `--endpoint-token`, while `appid create` takes
`--app-endpoint` and `--app-token`, plus the protocol, health-check, body-size and
`--app-config` settings that `app` deliberately hides. Check `--help` rather than carrying
a flag across.

An endpoint is optional on both. Created without one you get an identity that Catalyst can
route *from* but not *to*, which is exactly what an app running behind a local connection
wants.

### The agent resource is `diagrid agent`

It fronts an agent your application runs, and takes `--project`, `--endpoint`, `--wait`,
`--ignore-if-exists` and the `--archive-*` flags.

An application that runs itself — under `diagrid dev run`, in a container, anywhere — uses
**`agent`**. There are no model flags on it, and looking for one is the signal that you
have the wrong resource.

## 3. Ordering constraints, and the mechanism behind each

Each of these has a reason, and the reason is what tells you whether a failure is
recoverable.

| Create this | Before this | Because |
| --- | --- | --- |
| The managed workflow store on the project | Any App ID that uses workflows | The sidecar reads workflow configuration **at boot**. An App ID created first comes up without workflow support and the Workflow API answers `FAILED_PRECONDITION`. Enabling the store afterwards does not retrofit the running sidecar |
| Components and subscriptions | The App ID that consumes them | So they exist when the sidecar boots and loads them |
| A Configuration | The App ID that names it via `appConfig` | The reference has to resolve at create time |
| The **Agent** or **MCP server** | Any bare App ID of that name | **This one does not self-heal.** The Agent controller refuses to adopt a same-named App ID it does not own, so a plain App ID created first leaves the Agent permanently in an error state. There is no repair short of deleting the App ID |
| The App IDs a subscription scopes to | The subscription | Scopes must already exist in the project and already have access to the broker |

`diagrid dev run` honours all of these — it enables the workflow store before creating App
IDs, creates resources before App IDs, and detects an Agent or MCP server that owns a name
and skips provisioning rather than colliding with it. Doing the same work by hand in the
wrong order gets none of that protection.

## 4. Attach the connections

A component exists in the project; it reaches an application by being **scoped** to that
application's App ID.

```
diagrid component create <name> --type <type> --metadata key=value --scopes app-a,app-b
```

- `--scopes` is the attachment. **Leaving it empty grants every App ID in the project
  access**, which is convenient and is also how a component ends up loaded by a sidecar
  nobody intended.
- Types are `pubsub.*`, `state.*`, `bindings.*`, `secretstores.*` and `conversation.*`.
- `--interactive` is the path the CLI's own help recommends. Prefer it when you do not
  already know the metadata keys a type expects, rather than guessing them.
- `--wait` blocks until the component reconciles. Use it, then still read it back.

Managed services have fixed names — `pubsub` for the broker, `kvstore` for the KV store.
The managed workflow store is wired in implicitly and has **no component name**, so do not
go looking for one.

Access between applications is a separate control from both, and it is deny-by-default:
a caller that no policy names is refused. Grant it with `catalyst_grant_access` or
`diagrid app access grant`, and take it away with `catalyst_revoke_access` or
`diagrid app access revoke`. Read the current policy first with
`catalyst_get_access_policy`: the first grant on an App with no policy creates one that
denies everyone else. Both directions change who can reach the app, so say what will
change and get the user's agreement before either call: a grant can widen access to
every caller (`*`), and a revoke breaks the caller's calls as soon as the policy reaches
the sidecar.

Subscriptions are the pub/sub half:

```
diagrid subscription create <name> --component pubsub --topic <topic> --route /<path> --scopes <app-id>
```

Four component facts that each cost a rebuild when missed:

- **A component's type is immutable.** Changing it fails with `component must be deleted
  to be updated as the component type cannot be changed once created`, and converting to
  or from a Diagrid managed type fails the same way with its own wording. Delete and
  recreate, with the user's agreement first; there is no in-place path.
- **`actorStateStore` is rejected on a managed state store.** The managed workflow store
  already fills that role.
- **`agent-registry` is managed by Diagrid.** Do not create or edit it.
- **`agent-*` components require a matching Agent resource**, because the control plane
  needs one to scope the registry store to the sidecar. Components without their Agent
  are a hard failure, not a warning.

## 5. Verify readiness, do not infer it

`--wait` on a create is the beginning of the check, not the end of it. Read the resource
back:

- `catalyst_get_appid`, `catalyst_get_component`, `catalyst_get_agent` over MCP.
- `diagrid app get <name> -o json`, or `diagrid appid get <id> --all -o json` for the full
  lower-level object.

Always `-o json`. The default table view drops fields, including the ones carrying the
reason a thing is not ready.

**Ready is not one field.** Catalyst's own readiness check requires the App ID's status to
be `ready` **and** its API token to be present; a status of `ready` with no token yet is
not usable, and that is the state a caller most often reports as "it says ready but
nothing works".

The status vocabulary is `ready`, `pending`, `processing`, `provisioning`, `updating`,
`deleting`, `deleted`, `error`, `unknown` — but the set is not closed and the API declares
the field as a bare string, so **report the value you were given verbatim** rather than
rounding it to one of the nine. Agents report from a narrower set — `ready`, `error`,
`pending`, or empty before their first reconcile.

Four readings that mislead if taken alone:

- **A component's real reason lives under `status.appIdStatus[]`.** A component that fails
  to load is only reported as such by the sidecar of each scoped App ID, so the
  resource-level message is often empty while the App-ID-level one names the broker error.
  A pub/sub's `status.topicError` and a KV store's `status.itemsError` sit outside that
  structure entirely.
- **A disabled MCP server reports `ready`**, with a message saying it is disabled and
  loaded by no App ID. Disabled is a fully reconciled state, so `ready` is honest — it is
  just not the answer to "is it serving". Read the message.
- **`updating` right after a local connection attaches is normal.** Attaching one makes
  the sidecar reconfigure, so the App ID goes `ready` → `updating` → `ready`.
- **A missing local connection is not an error.** It means nobody is running that App ID
  from a machine right now.

Then prove the path rather than trusting the status. These exercise one API each and
separate the platform from the application:

- `diagrid call invoke`, `call publish`, `call state`, `call bindings`, `call conversation`.
  The App ID goes in `--id` on all five; `--app-id` is only a hidden deprecated alias.
- `diagrid listen --id <app-id> --invoke <method>` streams inbound requests to your
  terminal with no application code deployed. Nothing arriving means the problem is
  upstream of the app; requests arriving and still failing means it is not.

Creating an App ID prints its API token to your terminal. **Do not paste it into a
summary, a file or a commit** — it is the credential for that identity.

## 6. Hand back a link so the user can see it

Once something exists, give the user a way to look at it. Naming a resource you cannot
link to is a weaker answer than naming it with a link.

Do not hardcode or hand-derive the console host — production, staging, development and
local are different hosts, so a hardcoded one is wrong for someone. **Run `diagrid web`,**
which opens the console for the environment the session is logged in to. When you need the
URL itself, `catalyst-setup` section 3 carries the full API-host → console-host mapping,
including the loopback form a hand-rolled mapping usually misses. If you cannot establish
the host confidently, print the identifiers as plain text.

Use only these routes:

| Resource | Route |
| --- | --- |
| App ID | `/apps/details/:id` |
| Agent, either kind | `/agents/:appId/:id` |
| MCP server | `/mcp-servers/:id` |
| Workflow run | `/workflows/:appId/:runId`, optionally `/:tab` |
| Metrics for one App ID | `/metrics/appids/:id` |
| Metrics for the project | `/metrics`, or `/metrics/appids` |
| Project list | `/admin/projects` |

Two pages you may expect do not exist. There is **no project detail view** — only the
list, and `/admin/projects/:id/users` — and there is **no quota page**. Linking to either
one 404s.

The project rides along as a query parameter, and the two forms do not fall back to one
another:

| What you are holding | Parameter | Example |
| --- | --- | --- |
| A name-like id | `?project=<name>` | `?project=default` |
| A numeric uid | `?projectId=<uid>` | `?projectId=165`, `prj-` prefix optional |

`projectId` wins when both are present. Put a numeric uid into `?project=` and the console
searches for a project literally named after that number, finds none, and **silently shows
the user's default project instead** — no error, just the wrong data under the right
heading. If you cannot tell which form you hold, omit the parameter.

**A link that 404s or lands on the wrong project is worse than no link.**

## 7. Do not create a project

Every organization gets one named `default`, with managed pub/sub, a managed KV store, the
workflow store and agent infrastructure already attached. Deploy into it.

It is bootstrapped once, when the organization is first reconciled, and it is not
recreated if someone deletes it. Confirm with `diagrid project list`; if it is genuinely
gone, ask which project to use rather than inventing one. A hand-made project that behaves
differently is indistinguishable from a broken one to the person asking for help, and it
spends one of three per-region slots to get there.

Be careful with `--project` on any command that writes: `diagrid dev run` **creates the
project when the name does not exist** rather than rejecting it, so a typo provisions an
empty project and then reports that nothing is in it.

## Rules

- **Check headroom before designing, not after building.** `diagrid org usage`. App IDs,
  connections and subscriptions are capped per region across the whole organization, so a
  second project buys nothing.
- **Never offer an upgrade as the fix for the single pub/sub or KV store.** It is 1 on
  every plan, so no plan change buys a second one. Read the live quota rather than
  asserting the 1. Describe the shape that works — one broker with many topics, one store
  with many key prefixes.
- **Never suggest an upgrade to clear a cap.** Read the limit, and if it is genuinely
  reached, the platform's own remedy is to contact Diagrid support.
- **Say `app` or `agent`, never just "agent".** They are different resources with
  different flags, creation paths and console routes.
- **Create the Agent or MCP server before any App ID of that name.** A bare App ID created
  first cannot be adopted, and the Agent is then permanently in error.
- **Verify by reading the resource back, with `-o json`.** A create that returned is not a
  resource that works, and `ready` without an API token is not ready.
- **Report a status verbatim.** The vocabulary is not closed, and paraphrasing a platform
  error loses the detail that mattered.
- **Do not create a project.** Use `default`, and watch for a typo in `--project` creating
  one on your behalf.
- **Do not print secrets.** Create prints the API token; `--show-sensitive-values` exists
  on `component get` and `mcpserver get`. Leave it off unless asked, and never paste the
  result into anything that outlives the answer.
- **Link only what you can link correctly**, with a route from section 6 and a project
  parameter whose form you are sure of.
