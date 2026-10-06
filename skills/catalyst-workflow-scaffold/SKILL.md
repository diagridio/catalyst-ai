---
name: catalyst-workflow-scaffold
description: Add, create or generate a Dapr Workflow that runs on Diagrid Catalyst — the orchestrator, its activities, and the project wiring. Use for a workflow, orchestration, saga, pipeline or long-running multi-step process. Infers the repo's language.
---

# Scaffold a Dapr Workflow on Catalyst

Goal: end this skill with a workflow registered, started once against Catalyst, and its
status read back. Code that compiles but was never started is not a scaffold — most of
what goes wrong here goes wrong on the first real run.

## 1. Detect the language, do not ask for it

Language is a parameter of this skill, not a variant of it. Read the repository first.

| Found at the top level | Language | Workflow SDK |
| --- | --- | --- |
| `pyproject.toml`, `requirements.txt`, `*.py` | Python | `dapr` + `dapr-ext-workflow` |
| `*.csproj`, `*.sln`, `global.json` | .NET | `Dapr.Workflow` |
| `pom.xml`, `build.gradle` | Java | `io.dapr:dapr-sdk-workflows` |
| `go.mod` | Go | `github.com/dapr/durabletask-go` |
| `package.json`, `tsconfig.json` | TypeScript / JavaScript | `@dapr/dapr` |

Ask only when the directory is empty, or when two of these sit side by side and the
workflow could plausibly live in either. Guessing produces a project that will not build.

## 2. Add the Dapr SDK, not a Diagrid adapter

A Dapr Workflow needs the Dapr SDK for the detected language. All five are published.
The Diagrid `*-ai` packages are agent-framework bridges and are not needed here — they
belong to the agent-scaffolding path.

| Language | Coordinate | Newest verified stable |
| --- | --- | --- |
| Python | `dapr`, `dapr-ext-workflow` | 1.18.3 |
| .NET | `Dapr.Workflow` | 1.18.5 |
| Java | `io.dapr:dapr-sdk-workflows` | 1.18.1 |
| Go | `github.com/dapr/durabletask-go` | v0.14.0 |
| TypeScript | `@dapr/dapr` | 3.18.0 |

Three coordinate traps, each of which has already bitten someone:

- **Go workflow authoring is not in `github.com/dapr/go-sdk/workflow`.** That package
  existed in go-sdk v1.10.0 through v1.13.0 and was **removed in v1.14.0**, which is why
  stale tutorials still tell you to import it and why `go get` on it fails today. Import
  `github.com/dapr/durabletask-go/workflow` for authoring and
  `github.com/dapr/go-sdk/client` for the Dapr APIs.
- **`Dapr.Workflow` 1.19.0 is preview-only.** Pin the newest stable rather than the
  newest version.
- **Do not invent a Diagrid package for workflows.** There is no
  `Diagrid.Agents.Workflow`, and no Diagrid workflow package on any registry.

Never write a coordinate you have not watched resolve. A package id that 404s sends the
user hunting for a Catalyst problem that does not exist, which is worse than no skill.

## 3. Use the project named `default`

**Do not create a project.** Every organization gets one named `default` with managed
pub/sub, a managed KV store, the workflow store and agent infrastructure already
attached. Workflow history lives in that managed store, so a hand-rolled project is the
most common reason a freshly scaffolded workflow starts but never appears.

`default` is bootstrapped once, when the organization is first reconciled, and it is not
recreated if someone deletes it. Confirm it with `catalyst_list_projects` rather than
assuming; if it is gone, ask which project to use instead of creating one. There is no
current project, so pass the project on every call.

The managed components have fixed names — `pubsub` for the broker and `kvstore` for the
KV store. The managed workflow store is wired in implicitly and has no component name.
Agent infrastructure arrives with the managed KV store.

A project holds **one managed pub/sub and one managed KV store** on every plan, and no plan upgrade raises it, so never offer one as the
fix. Fan work out across topics on the one broker. These are plan values overlaid per
organization, not constants in the code, so read the live quota with `catalyst_get_usage`
rather than asserting the 1 — and do not promise a user it can be raised for them, which
is a commercial question rather than one you can answer.

## 4. Write the workflow so replay cannot change its mind

A workflow body is re-executed from the top on every replay. Anything that answers
differently the second time corrupts the run. Keep the body a pure function of its
history, and push every side effect into an activity.

| Hazard in the workflow body | What replay does to it | Write this instead |
| --- | --- | --- |
| Wall-clock reads (`now`, `UtcNow`, `time.Now`) | Yields a new value each replay | The context's current-time and durable-timer APIs |
| `random`, new UUIDs | Diverges from recorded history | Pass in as input, or generate inside an activity |
| HTTP, database and Dapr calls | Re-fires on every replay | Move into an activity |
| Iterating a map or dict | Order is not stable across replays | Sort keys, then iterate |
| Env vars, files, globals, statics | Host state drifts between replays | Pass in as input |
| `sleep`, threads, goroutines, `Task.Delay` | Not recorded in history | The context's durable timer |

Activities are **at-least-once**: an activity can run twice for one logical step. Make
each one idempotent, keyed on the instance id plus a stable step name, and never let two
activities in the same workflow both own the same write.

Renaming, reordering or removing activities in a workflow that has instances in flight
replays old history against new code, which fails the run. Add a new workflow name
instead and let the old instances drain. Workflow versioning is not solved for you.

## 5. Run it against Catalyst

1. **Make sure the app exists.** `catalyst_get_app` for the project and the app name; if
   it is absent, `catalyst_apply` an `App` (read `catalyst_get_resource_schema` first, run
   with `dry_run`, show the user, then apply). A write role is needed: if
   `catalyst_apply` is not in the tool list, say so and stop.
2. **Run the worker.** `catalyst-develop` section 3 is the one place that says how to
   start the process with the connection values from `catalyst_get_connection` in its
   environment. Follow it
   rather than improvising.

**A pure workflow worker needs no app port.** It dials Catalyst outbound and polls for work
items, so there is no inbound endpoint to expose and nothing should be listening. An app
with no registered endpoint is the correct shape for a worker. Give it one anyway (an app
endpoint with its health check enabled, or `--app-port` on a tunnel) and Catalyst
health-checks the app there, finds nothing, and starts no workflows: every start fails with
`failed to create workflow instance: context canceled`.

Do not invent an HTTP server to satisfy a port you do not need. It is a common first-run
failure and it fails confusingly — the worker registers the workflow and every activity
successfully, then dies at bind because something else already holds the port, so the logs
show a healthy startup followed by an error that has nothing to do with workflows. Give
the app an endpoint only when Catalyst calls in: service invocation, pub/sub delivery, or
an agent endpoint.

Apps, agents and MCP servers are each backed by an identity (an "App ID" in some APIs).
Where a tool asks for or returns `appId`, it means that identity's name. Read it from the
resource's `status.appIds` (the get tools include it). For an agent registered from your
own code, it's the `appId` on its registry record.

Budget the identities. Every app, agent and MCP server counts as one identity against a
per-region allowance; read it with `catalyst_get_usage`. Scaffold one app for the workflow and add more only when the
user asks. Workflows themselves are not quotaed — instances are free, apps are not.

## 6. Read the result back before claiming success

Start one instance and inspect it:

- `catalyst_start_workflow` with the project, the app identity and the workflow name, and
  the input if it takes one. It assigns the run id and returns it; keep it.
- `catalyst_list_workflow_runs` for the project, if you lost the id.
- `catalyst_get_workflow_run` for the run: the execution graph, and which step it is on
  or failed at.

`catalyst_start_workflow` is a write tool and is absent for a role that cannot write.

Workflow exploration is only available for the managed workflow store — another reason
to stay in `default`.

**An absent field is not an empty one.** A withheld payload is withheld by deleting the
key, not by returning an empty value. At the default `metadata` data-sharing level
`input`, `output` and `customStatus` are all removed from the run. Only an organization
administrator can raise the level to `full`, and you cannot do it from here. Never forge
a data-sharing header, and never ask an administrator to raise the level so you can
finish an answer.

When a payload really is missing, say so and name the level: "`output` was not shared at
this organization's data-sharing level (`metadata`)". Never say "the workflow produced no
output" — that sends the user to debug working code. Hand over the console link from
section 7 so the user can read it themselves.

A tool that refuses is likewise not a workflow that failed. Report the refusal.

## 7. Hand back a link, not a claim

Once the app exists and a run has started, give the user a console link so they can
see it for themselves. The console for the production server is `https://catalyst.diagrid.io`. Only these routes
exist:

| To show | Route |
| --- | --- |
| The app | `/apps/details/<appId>` |
| A workflow run | `/workflows/<appId>/<runId>`, optionally `/<tab>` |
| Metrics for the app | `/metrics/appids/<appId>` |

There is **no project detail page** and **no quota page**. Do not link to either; the only
project routes are the admin ones.

The project rides along as a query parameter, and the two spellings are not
interchangeable:

- `?project=<name>` for a name-like id, such as `default`
- `?projectId=<uid>` for a numeric uid, with or without the `prj-` prefix
- If both appear, `projectId` wins

Put a numeric uid into `?project=` and the console searches for a project literally named
after that number, finds nothing, and **silently falls back to the user's default
project** — no error, just the wrong data. Name goes in `project`, number goes in
`projectId`, and if you cannot tell which you are holding, leave the parameter off.

If you cannot build a link you trust, print the app and run id as plain text — **a link
that 404s or lands on the wrong project is worse than no link.**

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **If the client blocks a `catalyst_*` call, stop.** Tell the user which call was
  blocked, with its arguments, and ask them to approve it or allow it in their client's
  permissions; then retry that same call once. If they decline, stop and say so. Do not
  route around a block through the CLI, a script or an equivalent tool.
- **Do not create a project.** Use `default`. If it is gone, ask which existing project
  to use, and send someone with no project to the console to create one.
- **Do not name a package version you have not resolved.** Check the registry, or state
  the package without a version.
- **Do not scaffold per-language variants of this skill.** One skill detects the
  language; five near-identical skills would compete for the same request and lose.
- **Do not put a side effect in the workflow body.** Activities exist for that.
- **Use only the `catalyst_*` tools.** Where a capability has no tool, say it is not
  available over MCP yet and stop.
- **Never report a withheld field as an empty result.**
- **Never guess at a console URL.** Use the routes above, put the project in the right
  parameter, and print plain identifiers when you cannot build a link you trust.

<!-- These three coordinates are taught as traps, not as instructions. The lint
     gate rejects them by default because a skill that tells someone to use one
     is a real defect; naming them in order to warn against them is the opposite.
     lint-allow-banned: go-sdk/workflow — taught as an import path removed in go-sdk v1.14.0
     lint-allow-banned: Diagrid.Agents.Workflow — taught as a package id that 404s
-->
