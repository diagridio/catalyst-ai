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
recreated if someone deletes it. Confirm it with `diagrid project list` rather than
assuming; if it is gone, ask which project to use instead of creating one.

The managed components have fixed names — `pubsub` for the broker and `kvstore` for the
KV store. The managed workflow store is wired in implicitly and has no component name.

Two related facts, so you do not go looking for a flag that is gone:

- Agent infrastructure arrives with the managed KV store. `project create` has no
  `--enable-agent-infrastructure` flag — it was removed and is not coming back.
- `diagrid dev run` provisions the managed pub/sub, KV store and workflow store for any
  App ID it creates. You get them by running, not by configuring.

A project holds **exactly one managed pub/sub and exactly one managed KV store**. That
is a property of the platform on every plan, not a free-tier restriction — paying does
not raise it. Fan work out across topics on the one broker.

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

Scaffold the dev config, then run. Both commands default to the current project, so pass
`--project default` explicitly the first time to make the target visible in the log.

- `diagrid dev scaffold` writes a dev config for the project.
- `diagrid dev run --project default --id <app> -- <your run command>`
- Add `--app-port <port>` **only** if Catalyst must call *into* your application.

`--id` names the App ID, and on `dev run` the short `-p` means `--app-port`, not
`--project`.

**A pure workflow worker needs no app port.** It dials Catalyst outbound and polls for work
items, so there is no inbound endpoint to expose and nothing should be listening. The CLI
documents this shape itself: its own `dev run` example with no `--app-port` is the one
labelled *"without a local app connection"*. An App ID with no registered endpoint is the
correct shape for a worker.

Do not invent an HTTP server to satisfy a port you do not need. It is a common first-run
failure and it fails confusingly — the worker registers the workflow and every activity
successfully, then dies at bind because something else already holds the port, so the logs
show a healthy startup followed by an error that has nothing to do with workflows. Reach
for `--app-port` only when Catalyst calls in: service invocation, pub/sub delivery, or an
agent endpoint. Use `diagrid app`. The older `appid` command still exists but is hidden,
and it is **not** flag-compatible — `app create` takes `--endpoint` and
`--endpoint-token` where `appid create` takes `--app-endpoint` and `--app-token`. So
treat them as two commands, never as a noun you can swap while keeping the flags.

**Confirm every command against `--help` before relying on it**, including the ones
written here. This CLI renames nouns and moves flags between minor versions — `appid`
became `app`, and in the agent commands a single name changed which resource it creates.
Run `diagrid version` and the relevant `--help`, then match what you actually see rather
than what you remember.

**`dev run` has a much larger flag surface than the line above, and it is documented
elsewhere.** `-e, --env` passes environment variables through to your process,
`--app-id-env-server-enabled` serves the App ID's connection details to it, and
`--app-log-destination` redirects its logs. The full surface lives in `catalyst-develop` —
read it *before* working around a variable you cannot pass. Hand-building an environment
file to route around a flag that already exists one skill away is the expensive kind of
mistake here, and it is easy to make, because this section quotes only the flags it needs.

Budget the App IDs. A region allows **10 resources, where every app, agent and MCP
server counts as one**, and 3 projects. Scaffold one App ID for the workflow and add
more only when the user asks. Workflows themselves are not quotaed — instances are free,
App IDs are not.

## 6. Read the result back before claiming success

Start one instance and inspect it:

- `diagrid workflow start <workflow-name> --project default --id <app> --instance-id <run-id> -d '<json>'`
- `diagrid workflow list --project default`
- `diagrid workflow get <run-id> --project default --id <app>`

The workflow name and the run id are **positional**, not flags, and the two commands are
shaped differently in three ways worth checking rather than inferring:

- `start` **requires `--instance-id`** — you name the run, nothing generates it, and
  omitting it fails with `required flag(s) "instance-id" not set`.
- `get` takes the run id positionally and has no `--instance-id` at all.
- `get` also has no `--output` flag. It always prints YAML, so `-o json` on it is an
  unknown flag rather than a format choice — the one place `-o json` does not apply.

The App ID goes in `--id`. `--app-id` still parses as a hidden deprecated alias and
prints a notice, but it is absent from `--help`, so write `--id`.

Workflow exploration is only available for the managed workflow store — another reason
to stay in `default`.

**An absent field is not an empty one.** A withheld payload is withheld by deleting the
key, not by returning an empty value. But withholding is a property of *one* surface, not
of Catalyst, so which surface you are on decides whether it happens at all:

| Surface | `input` / `output` / `customStatus` | What it takes |
| --- | --- | --- |
| MCP tools | all three removed at the default `metadata` data-sharing level | Only an organization administrator can raise the org to `full`. You cannot do it from here. |
| CLI — `diagrid workflow get` | all three returned, **plus `input` and `output` for every activity in the history** | Nothing. There is no flag because none is needed. |
| Management API — single read | all three returned | Nothing. `getWorkflowExecution` takes no data parameter. |
| Management API — list endpoints | payloads withheld | `includeData=true`, which exists only on the two list operations |

The data-sharing level is read from the `x-diagrid-data-sharing` header by the MCP server
alone. The CLI and the management API never traverse that filter, so they cannot be
narrowed by it.

**So when an MCP response has withheld a payload, the CLI is the fallback that can still
show it.** Reach for `diagrid workflow get <workflow-id> --project <project> --id <app>`
before telling the user the data is unreachable. Its output is also richer than the tools':
the same activity name appears once per attempt, with its input each time, which is how you
see that an activity was retried and what it was retried with.

When a payload really is missing, report that it was withheld and by which surface. Never
say "the workflow produced no output" — that sends the user to debug working code, and on
the MCP path the remedy is an org-level setting they may not know exists.

A tool that refuses is likewise not a workflow that failed. Report the refusal, then fall
back to the CLI.

## 7. Hand back a link, not a claim

Once the App ID exists and a run has started, give the user a console link so they can
see it for themselves. Only these routes exist:

| To show | Route |
| --- | --- |
| The App ID | `/apps/details/<appId>` |
| A workflow run | `/workflows/<appId>/<runId>`, optionally `/<tab>` |
| Metrics for an App ID | `/metrics/appids/<appId>` |

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

Derive the host from the API URL the session is actually using. Prod, staging, dev and
local are different hosts, so a hardcoded one will be wrong for someone. If the host is
not determinable, print the App ID and run id as plain text and let `diagrid web` open the
console — **a link that 404s or lands on the wrong project is worse than no link.**

## Rules

- **Do not create a project.** Use `default`. If it is genuinely absent, say so and stop
  rather than inventing a substitute that behaves differently.
- **Do not name a package version you have not resolved.** Check the registry, or state
  the package without a version.
- **Do not scaffold per-language variants of this skill.** One skill detects the
  language; five near-identical skills would compete for the same request and lose.
- **Do not put a side effect in the workflow body.** Activities exist for that.
- **Check every CLI command against `--help` before running it.** Nouns and flags move
  between minor versions, so quote what you verified, not what you recall.
- **Never report a withheld field as an empty result.**
- **Never guess at a console URL.** Use the routes above, put the project in the right
  parameter, and print plain identifiers when you cannot build a link you trust.

<!-- These three coordinates are taught as traps, not as instructions. The lint
     gate rejects them by default because a skill that tells someone to use one
     is a real defect; naming them in order to warn against them is the opposite.
     lint-allow-banned: go-sdk/workflow — taught as an import path removed in go-sdk v1.14.0
     lint-allow-banned: Diagrid.Agents.Workflow — taught as a package id that 404s
     lint-allow-banned: --enable-agent-infrastructure — taught as a flag removed in v1.63.0
-->
