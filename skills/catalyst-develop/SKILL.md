---
name: catalyst-develop
description: Iterate on code locally while it runs against live Diagrid Catalyst infrastructure — the edit, rerun, observe loop. Covers `diagrid dev run`, the scaffolded dev file, the local app connection, output streams, and a tunnel or sidecar that never comes up.
---

# The local development loop

Goal: end this skill with the user's own process running on their machine, talking to a
real Catalyst sidecar, and able to see three things — their app's output, the API traffic,
and the platform's own logs. A loop that requires a redeploy per edit is not this loop;
if you find yourself recreating resources to test a code change, something above is wrong.

## 1. The shape of the loop

Two commands, run at different frequencies. Confusing them is the most common way this
gets slow.

| Frequency | Command | What it does |
| --- | --- | --- |
| Once per project, then on change | `diagrid dev scaffold` | Writes a dev config file describing every App ID in the project, and exports the project's own resources next to it |
| Every iteration | `diagrid dev run` | Reconciles the resources, attaches a local app connection, and launches your process |

What survives an iteration: the App ID, its API token, the components, the subscriptions,
the managed pub/sub and KV store. What you redo: your process. Nothing in a code change
requires touching the platform, and the section on what *does* force a change is below —
read it before you delete anything.

**Never create a project to develop in.** Every organization gets one named `default`
with managed pub/sub, KV, workflow store and agent infrastructure already attached, and
`dev run` needs all of them. Confirm with `diagrid project list`.

This matters more here than elsewhere, because `dev run` **creates the project when the
name does not exist.** A typo in `--project` does not error; it provisions a fresh empty
project, spends one of the three per-region slots, and then reports that nothing is in it.
Read the `Using existing project: ...` line it prints before you trust the run.

## 2. Scaffold the dev file, then own it

`diagrid dev scaffold` writes `<project>.yaml` into the current directory unless `-f`
says otherwise, and it writes more than that one file. Every non-managed component,
subscription and resiliency policy in the project is exported alongside it as
`<project>-component-<name>.yaml`, `<project>-subscription-<name>.yaml` and
`<project>-resiliency-<name>.yaml`, and listed under `common.resourcesPaths`. Managed
components are skipped with a `skipping managed component` line — that is correct, not a
failure, because a managed component is not yours to declare.

Scaffold refuses to run against a project that is not settled. It polls the project for
readiness, then polls the App IDs, and gives up with `App ID "x" must be in ready status
in order to scaffold dev session configuration`. That is a wait, not an error to work
around — see the readiness row in section 7.

If the project has no App IDs it writes an empty file and says so, pointing you at
creating one first. An empty dev file is not runnable.

### What it fills in, and what it leaves for you

Per app it writes `appID`, `appDirPath`, `appChannelAddress` (`127.0.0.1`), `appProtocol`
(`http`), the health-check block, and four environment variables:

| Variable | Why your code needs it |
| --- | --- |
| `DAPR_APP_ID` | The identity the sidecar answers as |
| `DAPR_HTTP_ENDPOINT` | Where the Dapr HTTP API lives, on the project's host, not localhost |
| `DAPR_GRPC_ENDPOINT` | The same for gRPC |
| `DAPR_API_TOKEN` | The App ID's credential |

It leaves `appPort` at `0` and `command` empty. Those two are yours to fill in — a
scaffolded file with neither will refuse to start with `port and command cannot both be
empty`.

**That file contains a live API token per app.** It is a credential, in your working
directory, in a file named after your project. Add it to `.gitignore` before you run
anything, and never paste its contents into an answer, an issue or a commit.

Re-running scaffold on an existing file **updates rather than replaces**: an app entry
that is already there is carried over untouched, so the port and command you filled in
survive. That is what makes re-scaffolding the right response to a stale file rather than
a lossy one.

## 3. Run it

Two mutually exclusive forms. Passing both a file and an `--id` is rejected.

```
diagrid dev run --project default --file default.yaml
diagrid dev run --project default --id <app> --app-port <port> -- <your run command>
```

Everything after `--` is your process. Omit the command and `dev run` only attaches the
connection, which is how you launch from a debugger.

Flags worth knowing, all present on v1.63.0:

| Flag | Note |
| --- | --- |
| `--id`, `-a` | The App ID. `--app-id` still works but is a hidden, deprecated alias |
| `--app-port`, `-p` | **`-p` is the port here, not the project** |
| `--project` | No shorthand on `run`. On `scaffold`, `stop`, `status` and `cleanup`, `-p` *is* `--project` |
| `--file`, `-f` | The dev config file |
| `--dry-run` | Shows what would be created. **Only valid with `--file`** |
| `--env`, `-e` | Extra environment variables for your process |
| `--app-dir-path` | Working directory for the command, default `.` |
| `--enable-api-logging` | Streams the API log, see section 5 |
| `--app-log-destination` | `file`, `console` or `all` |
| `--app-id-env-server-enabled` | Serves each App ID's environment over HTTP, see section 6 |
| `--rm-appids` | Deletes App IDs this run created, on exit |
| `--skip-managed-pubsub`, `--skip-managed-kv`, `--skip-managed-workflow`, `--skip-default-resiliency` | Opt out of the automatic provisioning below |

The `-p` collision is worth spelling out, because only one half of it announces itself.
`dev run -p default` is rejected at parse time, since `--app-port` takes an integer — that
one is loud. `dev run -p 8080` when you meant the project is silent: it sets a port, falls
back to whatever project the CLI context holds, and runs against it.

## 4. What happens before your code starts

`dev run` reconciles in a fixed order, and the order is load-bearing rather than
cosmetic. Knowing it tells you which line a failure belongs to.

1. **Project.** Used if it exists, created if not, waited for if it is mid-deletion.
2. **The managed workflow store, before any App ID exists.** The sidecar reads workflow
   configuration at boot, so an App ID created before the store is enabled comes up
   without workflow support and the Workflow API answers `FAILED_PRECONDITION` until it is
   redeployed. This is why enabling the store afterwards does not fix a broken run.
3. **Configuration resources**, so an App ID can reference one by `appConfig`.
4. **Components and subscriptions**, so they exist when the sidecars boot.
5. **App IDs**, in parallel. Names are lowercased for you.
6. **Readiness** — the project, then every component, then every App ID.
7. **The local app connections.** Attaching one makes the App ID reconfigure, so its
   status goes `ready` → `updating` → `ready`.
8. **Readiness again**, because of step 7, so the sidecar's gRPC endpoint is actually
   there before your process gets a chance to call it.
9. **Your process.**

Three side effects of step 4 that surprise people:

- **A component pointing at a local address is rewritten to a managed one.** A
  `state.*` component whose host resolves to loopback or an RFC 1918 address becomes
  `state.diagrid` against the managed `kvstore`; a `pubsub.*` becomes `pubsub.diagrid`
  against the managed `pubsub`. Only a small allow-list of metadata survives the
  translation — `keyPrefix` and the outbox settings for state, `consumerID` for pub/sub.
  Everything else is dropped silently, so do not tune a local component and expect the
  settings to arrive. Any other local component type cannot be translated at all and
  fails with `Cannot transform local component ... to a Catalyst managed type`.
- **A default resiliency policy is created** — `managed-service-invocation-policy`, a 30
  second app timeout and five constant 3 second retries on HTTP 500-504. Declaring your
  own Resiliency in the run file suppresses it, as does `--skip-default-resiliency`.
- **Declaring your own pub/sub or state component suppresses the managed one.** The
  automatic `pubsub` and `kvstore` are only created when the run file asks for neither.

## 5. Read the output while you develop

Three different streams, and picking the wrong one is why bugs look invisible.

| Stream | How | What it carries |
| --- | --- | --- |
| Your process | Inline in `dev run`, or written to file with `--app-log-destination` | Whatever your code prints |
| The API log | `--enable-api-logging`, or `enableApiLogging` per app in the file | One JSON line per Dapr API call, prefixed `== API - <appid> ==`, with method, status, protocol, execution time, component name and the trace and span ids |
| The platform | `diagrid appid logs <id> -f -t 50` | The sidecar and the app as Catalyst saw them |

Reach for the API log the moment a call "does nothing": it shows whether the call left
your process at all, which is the fork between an application bug and a wiring bug. The
trace id in it is what joins a request across App IDs.

For the platform logs, the type is the whole point:

- `diagrid project logs --ids <a>,<b> --type dapr` — the sidecar. Component
  initialisation and connection errors land here.
- `diagrid project logs --ids <a>,<b> --type app` — your application's output as
  Catalyst captured it.

<!-- lint-allow-banned: --appids — named here only to steer away from it, which is the guidance the ban exists to produce -->

Note the flag is `--ids`, not `--appids`, and the project name is a positional argument
rather than a flag. `project logs` does not follow — it paginates with `--limit` and
`--page`, and defaults to JSON output. `appid logs` is the one that takes `--follow`.

**Confirm a command against `diagrid <noun> --help` before you rely on it.** This CLI
moves nouns and flags between minor versions, `appid` is now hidden in favour of `app`,
and `--app-id` has already become a deprecated alias for `--id`. Run `diagrid version`
first and match what you see, including against the commands written here.

### Trigger a run, so there is output to read

Nothing above produces anything until a workflow actually runs. Starting one is a write,
so it is the one part of this loop that is absent from a read-only tool surface — if
`catalyst_start_workflow` is not in the tool list, that is why, and the CLI still works.

| | |
| --- | --- |
| MCP | `catalyst_start_workflow` — needs `projectId`, `appId` and `name` |
| CLI | `diagrid workflow start <workflow-name> --id <app-id> -p <project> --data '<json>'` |

**Capture the instance id.** The MCP tool returns it, and it is how every later call
refers to that run — reading its status, its history, or stopping it. Losing it means
listing runs and guessing which one was yours, which is ambiguous the moment two runs
start in the same second.

The two interfaces differ here in a way worth knowing: the CLI lets you *choose* the
instance id with `--instance-id`, which is useful when you want a predictable handle
across a rebuild. The MCP tool assigns one and hands it back.

Stopping a run is a separate matter and is deliberately not in this skill — it is
irreversible and belongs with diagnosis rather than iteration.

## 6. Iterating without touching the platform

A code change needs nothing but your process restarted. Stop `dev run`, start it again,
and the App ID, components and subscriptions are found rather than made — the run prints
`Using existing dapr app id ...` for each, which is your confirmation that the loop is
tight.

What genuinely does require a platform change:

| Change | Why |
| --- | --- |
| A new component or subscription | It has to exist before the sidecar that loads it boots |
| A component's **type** | Immutable. It must be deleted and recreated, and that includes converting to or from a Diagrid managed type |
| A new App ID | Nothing can reference an app that has no App ID |
| Health-check or protocol settings | An App ID's spec is not updatable in place; the health check is re-applied when the connection attaches, and `appConfig` is the one field `dev run` will patch |

### The connection outlives your process

This is the trap that produces "it worked yesterday". Killing `dev run` stops your
process but leaves the local app connection registered, and the CLI says so on exit:
`Your dev session will remain active until you stop it by running: diagrid dev stop --id <id>`.

- `diagrid dev status` lists every connection in the project, with its status and whether
  its credentials have **expired**.
- `diagrid dev stop --id <app> --project default` removes one.
- An expired or orphaned connection is a normal thing to find and a normal thing to stop.
  A missing connection is also normal — it means nobody is running locally.

### Running your app from a debugger

Attach the connection without launching anything, then start the process yourself:

```
diagrid dev run --project default --id <app> --app-port <port> --app-id-env-server-enabled
```

The environment server then serves each App ID's `DAPR_HTTP_ENDPOINT`,
`DAPR_GRPC_ENDPOINT` and `DAPR_API_TOKEN` as JSON at `http://localhost:8001/<app-id>`
(`--app-id-env-server-port` moves it). Your debug configuration reads them from there
instead of you copying a token into a launch profile where it will rot.

## 7. When the sidecar or the connection does not come up

Route by the message you actually saw. Guessing here wastes a whole iteration.

| Message | Cause | Do |
| --- | --- | --- |
| `project <name> not found` | The dev file names a project that is gone, or `--project` is a typo | Check `diagrid project list`. Do not let `dev run` create the typo |
| `App ID <name> not found` | The dev file is ahead of the project | Re-scaffold rather than hand-editing |
| `App ID x does not match provided env var DAPR_APP_ID y` | A hand-edited or copied dev file | Re-scaffold. This check exists because the mismatch otherwise surfaces as a silent auth failure |
| `API token org ID / project ID / App ID does not match` | A token pasted from another project or organization | Re-scaffold. Never hand-write a token into the file |
| `App ID "x" must be in ready status in order to scaffold` | The App ID is still provisioning | Wait. Scaffold already retries at 4 second intervals; a tighter loop of your own does not help |
| `error connecting to tunnel for app "x"` | The connection could not be established | `diagrid dev status`, then `dev stop` a stale one. Then check whether the project was created with app tunnels disabled — that is a project setting, and no local connection will ever attach while it is set |
| `tunnel for app "x" did not start` | It connected but never came up | Same as above |
| `App IDs did not become ready after tunnel connection` | The reconfigure at step 7 of section 4 did not settle | Expected transient, then a real failure. `updating` immediately after attach is normal; give it the poll window before calling it broken, then read `--type dapr` logs |
| `component <name> not ready` | A component, not your app | `diagrid project logs --ids <id> --type dapr` carries the broker or store error |
| `Directory "x" for app "y" does not exist` | `appDirPath` is resolved from where you ran the command | Fix the path or run from the directory the file assumes |
| `this run references agent components but no Agent resource exists for ...` | The run declares `agent-*` components but no matching Agent | Create the Agent for that name first. Every app in an agent run needs one |
| `component must be deleted to be updated ...` | You changed a component's type | Delete and recreate it. Nothing else works |
| `The selected region does not support the Workflows API` | Informational | Not a failure of this run, but workflow calls in that region will not work |
| `port and command cannot both be empty` | A scaffolded app entry never got filled in | Set `appPort`, a `command`, or both |

Two quieter failure modes with no error to grep for:

- **A run-file field that does nothing.** The dev file is a Dapr multi-app run file
  dialect, and Catalyst ignores a long list of the standard fields — container images,
  `daprHTTPPort` and the other port overrides, `placementHostAddress`,
  `schedulerHostAddress`, `appSSL`, `unixDomainSocket`, profiling, `runtimePath`, and the
  health-check fields at `common` level rather than per app. Each one prints an
  `Ignoring unsupported ...` warning at startup. If a setting appears to have no effect,
  read the startup warnings before debugging your code.
- **`agent-registry` is managed by Diagrid.** It is skipped if your resources declare it.
  Do not try to create or edit it.

If you get past all of that and requests still are not arriving, stop guessing at the app
and check the path: `diagrid listen --app-id <id> --invoke <method>` streams inbound
requests straight to your terminal with no application code involved. Nothing arriving
means the problem is upstream of your process.

## Rules

- **Do not create a project.** Use `default`, and remember `dev run` will create a typo
  rather than reject it. Check the project name before every first run of a session.
- **Treat the dev file as a secret.** It holds a live API token per App ID. Gitignore it,
  and never print its contents.
- **Do not hand-edit the generated app entries.** Re-scaffold; it preserves the port and
  command you added and fixes the identity fields that go stale.
- **Say which stream a line came from.** Your process, the API log and the platform logs
  fail differently, and a conclusion drawn from the wrong one sends the user to the wrong
  file.
- **Confirm every command against `diagrid version` and `--help`.** `-p` means different
  things on different `dev` subcommands, `appid` is hidden in favour of `app`, and
  `--app-id` is deprecated in favour of `--id`. Quote what you verified.
- **Wait for readiness rather than retrying past it.** The CLI already polls the project,
  the components and the App IDs. Restarting the run resets those timers and makes a slow
  provision look like a hang.
- **Stop what you started.** A dev session left running holds a local app connection on
  the App ID. `diagrid dev status` shows it, `diagrid dev stop --id <app>` releases it.
- **Do not delete resources to test a code change.** Nothing in an edit-run-observe cycle
  needs a component or App ID recreated, and `--rm-appids` on a shared project deletes
  what this run created out from under whoever else is using it.
