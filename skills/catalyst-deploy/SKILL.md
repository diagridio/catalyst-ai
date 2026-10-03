---
name: catalyst-deploy
description: Move an application from a laptop into Diagrid Catalyst. Covers budgeting headroom, creating the app, agent or MCP server first, attaching connections and topic subscriptions, the order these must be created in, and proving each one came up.
---

# Get an application running in Catalyst

Goal: end this skill with a named resource the user can open in the console, whose
readiness you confirmed by reading it back rather than by watching an apply succeed. An
apply that returns is an apply that was accepted; it is not a thing that works.

Order matters throughout, and not as a matter of taste — several of the constraints below
leave a resource *permanently* broken when taken out of order, with no error at the moment
you got it wrong. Read sections 1 and 3 before creating anything.

## How to deploy: `catalyst_apply`

Every create and change goes through `catalyst_apply`. You send manifests, and it
creates what does not exist and replaces what does. It accepts these kinds: `Project`,
`Configuration`, `Component`, `Pubsub`, `KVStore`, `Resiliency`, `HTTPEndpoint`,
`Subscription`, `Agent`, `MCPServer`, `App`, `WorkflowAccessPolicy`,
`MCPServerAccessPolicy` and `TokenBudget`.

It is listed only for users whose role can write. If it is missing, that is the user's
role, not a broken connection: tell the user a write role is needed and stop. There is
no other route to create a resource.

- **Send one application's resources together, with one exception.** Within a call it
  applies them in a fixed order: project, configurations, components and subscriptions,
  agents and MCP servers, apps, then access policies and token budgets. That puts a
  subscription *before* the apps, but section 3 requires the identities a subscription
  scopes to to exist first. So send subscriptions in a second call, after the call that
  created their apps, agents or MCP servers. Across calls, the order is yours to get right.
- **Call `catalyst_get_resource_schema` before writing a kind for the first time.** Do
  not guess field names: the platform rejects unknown fields, and a guessed name that
  happens to be accepted can mean something else.
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
- **Accepted is not ready.** Read each resource back (section 5).

Deleting goes through `catalyst_delete_resource`, never as a side effect of a deploy.
It cannot be undone. **Every kind except a project is deleted on the first call**, so
ask the user before you call it, and name what goes with the resource. A project is the
one exception: the first call returns a preview of everything it would remove, plus a
confirmation token. Show the user that preview, and call again with the token only
after they agree.

## 1. Budget the headroom first

Do this before designing a topology, not after building one. Every cap here is enforced
at create time, so the cost of discovering one late is a redesign rather than a retry.

- `catalyst_get_usage` reports `used` and `limit` per key.
- `catalyst_get_metrics` reads request rates, error rates and consumption for a project
  or a single app, agent or MCP server.

Read the numbers. Do not recite remembered plan values — organizations get custom limits,
so a figure from memory is often wrong for the one in front of you.

### The scope of each cap is the part people get wrong

| Cap | Scope | Consequence for a design |
| --- | --- | --- |
| `number_of_appids` — Identities: one per app, agent and MCP server | Per region, **summed across every project in the organization** | Splitting a topology across two projects does not buy more |
| `number_of_connections` | Per region, org-wide | Same. A connection is a component |
| `number_of_catalyst_subscriptions` | Per region, org-wide | Same |
| `number_of_projects` | Per region | Low, and easy to spend by accident — see section 7 |
| `number_of_pubsubs_per_project` | Per project | **1 on every plan** |
| `number_of_kvstores_per_project` | Per project | **1 on every plan** |

Two of those deserve stating out loud because they change what you build:

**Apps, agents and MCP servers all consume the same allowance.** Each is backed by one
identity, and identities are what the quota counts. The rejection says so, and names the breakdown: *"has reached
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
cannot be built. Read `catalyst_get_usage` for every other figure rather than quoting one.

Finally, headroom is not the only per-region property. Managed pub/sub, managed KV and
the Workflows API are **regional capabilities**, and a region that lacks one gives you a
project where that API simply is not available. `catalyst_get_region` says what the region
supports. If workflow calls must work, confirm the region supports them before you build
on them.

There is **no quota page in the console.** Do not link to one; report the numbers.

## 2. The app, agent or MCP server comes first, because it carries the identity

Apps, agents and MCP servers are each backed by an identity (an "App ID" in some APIs).
Where a tool asks for or returns `appId`, it means that identity's name. Read it from the
resource's `status.appIds` (the get tools include it). For an agent registered from your
own code, it's the `appId` on its registry record.

The identity is not a deployment artifact. It is what the sidecar runs under: it owns the
API token, it is what components are scoped to, it is what a subscription delivers to,
and it is what a local connection attaches to. Nothing can reference an application whose
resource does not exist yet, which is why every ordering constraint in section 3 starts
from it.

**Names are unique across three resource types in a project.** Creating an agent whose
name is taken by an app fails with *"the name ... is already in use in project ...; App,
Agent and MCP server names must be unique within a project"*. Pick the name once, for the
right resource type, and check `catalyst_list_apps` and `catalyst_list_agents` before you
do.

### Which kind to apply

| Deploying | Kind | Who owns the identity |
| --- | --- | --- |
| Your own application | `App` | The app you just made |
| An agent whose code you run yourself | `Agent` | The agent provisions and manages its own |
| An MCP server | `MCPServer` | The MCP server, likewise |

Read `catalyst_get_resource_schema` for the fields each takes. An `App` takes an
endpoint and an endpoint token; an `Agent` takes an endpoint and archive settings.

An endpoint is optional. Created without one you get an identity that Catalyst can
route *from* but not *to*, which is exactly what an app running as a pure worker wants.
Set one only when the app runs a server there for Catalyst to call. With the app's
health check enabled, while nothing answers it the app's workflows, actors and message
delivery stay blocked.

### The agent resource

`Agent` fronts an agent your application runs. An application that runs itself — locally,
in a container, anywhere — uses **`Agent`** for that. There are no model settings on it,
and looking for one is the signal that you have the wrong resource.

## 3. Ordering constraints, and the mechanism behind each

Each of these has a reason, and the reason is what tells you whether a failure is
recoverable.

| Create this | Before this | Because |
| --- | --- | --- |
| The managed workflow store on the project | Any app, agent or MCP server that uses workflows | The sidecar reads workflow configuration **at boot**. One created first comes up without workflow support and the Workflow API answers `FAILED_PRECONDITION`. Enabling the store afterwards does not retrofit the running sidecar |
| Components and subscriptions | The app, agent or MCP server that consumes them | So they exist when the sidecar boots and loads them |
| A Configuration | The app that names it via `appConfig` | The reference has to resolve at create time |
| The **Agent** or **MCP server** | Anything else of that name | **This one does not self-heal.** An Agent or MCP server will not adopt a same-named identity it does not own, so anything else created first under that name leaves it permanently in an error state. There is no repair short of deleting what took the name |
| The apps, agents or MCP servers a subscription scopes to | The subscription | Scopes must already exist in the project and already have access to the broker |

`catalyst_apply` orders one call for you as described above, but it cannot order two
calls, and it cannot fix a workflow store enabled after the app.

## 4. Attach the connections

A component exists in the project; it reaches an application by being **scoped** to that
application's identity. Apply a `Component` with its `spec.scopes` set:

- `scopes` is the attachment. **Leaving it empty grants every app, agent and MCP server
  in the project access**, which is convenient and is also how a component ends up loaded by a sidecar
  nobody intended.
- Types are `pubsub.*`, `state.*`, `bindings.*`, `secretstores.*` and `conversation.*`.
- When you do not already know the metadata keys a type expects, read
  `catalyst_get_resource_schema` and `catalyst_list_templates` rather than guessing them.

Managed services have fixed names — `pubsub` for the broker, `kvstore` for the KV store.
The managed workflow store is wired in implicitly and has **no component name**, so do not
go looking for one.

Access between applications is a separate control from both, and it is deny-by-default:
a caller that no policy names is refused. Grant it with `catalyst_grant_access`, and take
it away with `catalyst_revoke_access`. Read the current policy first with
`catalyst_get_access_policy`: the first grant on an App with no policy creates one that
denies everyone else. Both directions change who can reach the app, so say what will
change and get the user's agreement before either call: a grant can widen access to
every caller (`*`), and a revoke breaks the caller's calls as soon as the policy reaches
the sidecar.

Subscriptions are the pub/sub half: apply a `Subscription` naming the `pubsub` component,
the topic, the route, and the identities it is scoped to.

Four component facts that each cost a rebuild when missed:

- **A component's type is immutable.** Changing it fails with `component must be deleted
  to be updated as the component type cannot be changed once created`, and converting to
  or from a Diagrid managed type fails the same way with its own wording. Delete it with
  `catalyst_delete_resource` and apply it again, with the user's agreement first; there is
  no in-place path.
- **`actorStateStore` is rejected on a managed state store.** The managed workflow store
  already fills that role.
- **`agent-registry` is managed by Diagrid.** Do not create or edit it.
- **`agent-*` components require a matching Agent resource**, because the control plane
  needs one to scope the registry store to the sidecar. Components without their Agent
  are a hard failure, not a warning.

## 5. Verify readiness, do not infer it

An apply returning is the beginning of the check, not the end of it. Read the resource
back:

- `catalyst_get_app`, `catalyst_get_agent`, `catalyst_get_mcp_server` and
  `catalyst_get_component`. The first three include the backing identity under
  `status.appIds`, which is where its readiness lives.
- For the components and subscriptions attached to it, `catalyst_list_components`; read
  each one's `scopes`.

**Ready is not one field.** Catalyst's own readiness check requires the identity's status to
be `ready` **and** its API token to be present; a status of `ready` with no token yet is
not usable, and that is the state a caller most often reports as "it says ready but
nothing works". No read tool returns the API token; only `catalyst_get_connection`
does (see `catalyst-develop` section 3).

The status vocabulary is `ready`, `pending`, `processing`, `provisioning`, `updating`,
`deleting`, `deleted`, `error`, `unknown` — but the set is not closed and the API declares
the field as a bare string, so **report the value you were given verbatim** rather than
rounding it to one of the nine. Agents report from a narrower set — `ready`, `error`,
`pending`, or empty before their first reconcile.

Four readings that mislead if taken alone:

- **A component's real reason lives under `status.appIdStatus[]`.** A component that fails
  to load is only reported as such by the sidecar of each scoped identity, so the
  resource-level message is often empty while the per-identity one names the broker error.
  A pub/sub's `status.topicError` and a KV store's `status.itemsError` sit outside that
  structure entirely.
- **A disabled MCP server reports `ready`**, with a message saying it is disabled and
  loaded by no app. Disabled is a fully reconciled state, so `ready` is honest — it is
  just not the answer to "is it serving". Read the message.
- **`updating` right after a local connection attaches is normal.** Attaching one makes
  the sidecar reconfigure, so the identity goes `ready` → `updating` → `ready`.
- **A missing local connection is not an error.** It means nobody is running that app
  from a machine right now. `catalyst_list_app_tunnels` lists the ones that are.

Then prove the path rather than trusting the status. For a workflow app, start a run with
`catalyst_start_workflow` and read it back with `catalyst_get_workflow_run`; that
separates the platform from the application. `catalyst_get_metrics` shows whether the app
has served or sent anything. Invoking the app directly, publishing a test message and
reading state back are not available over MCP yet; say so rather than claiming you
checked them.

The API token of an app, agent or MCP server is the credential for that identity. No read tool returns it; only
`catalyst_get_connection` does (see `catalyst-develop` section 3). Do not ask the user
to paste one, and do not write one into a summary, a file or a commit.

## 6. Hand back a link so the user can see it

Once something exists, give the user a way to look at it. Naming a resource you cannot
link to is a weaker answer than naming it with a link.

The console for the production server is `https://catalyst.diagrid.io`. If you cannot build a link you trust, print
the identifiers as plain text.

Use only these routes, appended to that host:

| Resource | Route |
| --- | --- |
| App | `/apps/details/:id` |
| Agent | `/agents/:appId/:agentId` |
| MCP server | `/mcp-servers/:id` |
| Workflow run | `/workflows/:appId/:runId`, optionally `/:tab` |
| Metrics for one app, agent or MCP server | `/metrics/appids/:id`, by identity |
| Metrics for the project | `/metrics`, or `/metrics/appids` |
| Project list | `/admin/projects` |

An agent's `:agentId` is not its name. It is the `agent_id` on the agent's registry record,
from `catalyst_list_agents` or `catalyst_get_agent`, and looks like
`O5SWC5DIMVZC2YLTONUXG5DBNZ2A`. Copy it from that answer; a link built from the name
opens a page that cannot find the agent. An agent with no registry record yet takes its
app ID in both places: `/agents/:appId/:appId`.

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
recreated if someone deletes it. Confirm with `catalyst_list_projects`; if it is genuinely
gone, ask which project to use rather than inventing one. A hand-made project that behaves
differently is indistinguishable from a broken one to the person asking for help.

Be careful with a `Project` manifest in a `catalyst_apply` batch: it creates the project
it names, so check its `metadata.name`. A `project` argument that differs from it is
rejected. Send one only when the user has explicitly asked for a new project.

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **If the client blocks a `catalyst_*` call, stop.** Tell the user which call was
  blocked, with its arguments, and ask them to approve it or allow it in their client's
  permissions; then retry that same call. Do not route around it through the CLI, a
  script or another tool.
- **Name the organization before the first write.** Before the session's first
  `catalyst_apply`, `catalyst_delete_resource` or any other call that creates, changes
  or deletes something, call `catalyst_whoami` and tell the user which organization the
  change lands in. A user with more than one organization cannot otherwise tell where it
  went. If it fails, follow `catalyst-setup` and write nothing.
- **Check headroom before designing, not after building.** `catalyst_get_usage`.
  Identities, connections and subscriptions are capped per region across the whole
  organization, so a second project adds no headroom for them.
- **Never offer an upgrade as the fix for the single pub/sub or KV store.** It is 1 on
  every plan, so no plan change buys a second one. Read the live quota rather than
  asserting the 1. Describe the shape that works — one broker with many topics, one store
  with many key prefixes.
- **Do not offer a second project as the way to get a second broker or store.** Each project
  carries its own, but a second one spends a project slot (read `catalyst_get_usage`) and splits one app into two environments. The
  intended shape is one broker separated by topic; if you mention a second project at
  all, say that.
- **Never suggest an upgrade to clear a cap.** Read the limit, and if it is genuinely
  reached, the platform's own remedy is to contact Diagrid support.
- **Say `app` or `agent`, never just "agent".** They are different resources with
  different settings, creation paths and console routes.
- **Create the Agent or MCP server before anything else of that name.** It will not adopt
  an identity it does not own, and is then permanently in error.
- **Dry-run first, and verify by reading the resource back.** An apply that returned is
  not a resource that works, and `ready` without an API token is not ready.
- **Report a status verbatim.** The vocabulary is not closed, and paraphrasing a platform
  error loses the detail that mattered.
- **Do not create a project.** Use `default`, and check the `metadata.name` of any
  `Project` manifest in a batch.
- **Ask before any delete.** `catalyst_delete_resource` cannot be undone.
- **Do not print secrets.** Never paste a secret value, or an API token if you are ever
  given one, into anything that outlives the answer.
- **Link only what you can link correctly**, with a route from section 6 and a project
  parameter whose form you are sure of.
