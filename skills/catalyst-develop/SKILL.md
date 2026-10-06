---
name: catalyst-develop
description: Run an app or agent locally against Diagrid Catalyst — get its connection with catalyst_get_connection, start it, trigger runs, and crash and restart it to watch a workflow resume. Use for local runs, a crash-and-recover demo, or a worker that never connects.
---

# The local development loop

Goal: end this skill with the user's own process running on their machine, talking to a
real Catalyst sidecar, and able to see what it did. A loop that requires a redeploy per
edit is not this loop; if you find yourself recreating resources to test a code change,
something above is wrong.

Everything here goes through the Catalyst MCP server, the `catalyst_*` tools. If they are
missing or refuse with `NOT_AUTHENTICATED`, the `catalyst-setup` skill covers it.

## 1. The shape of the loop

| Frequency | Step | How |
| --- | --- | --- |
| Once per app | Make sure the App ID exists, with its components | `catalyst_get_app`, else `catalyst_apply` (section 2) |
| Every run of the process | Get the connection values and start the process with them | `catalyst_get_connection` (section 3) |
| Every iteration | Trigger a run and read what happened | `catalyst_start_workflow`, `catalyst_get_workflow_run` (section 4) |

What survives an iteration: the app and its identity, its API token, the components, the
subscriptions, the managed pub/sub and KV store. What you redo: your process. Nothing in a
code change requires touching the platform, and section 6 lists what *does* force a
change. Read it before you delete anything.

**Use `default`; only if it is absent, offer to create a project and wait for the user's
agreement. Never reuse a misconfigured project.** Every organization gets one named
`default` with managed pub/sub, KV, workflow store and agent infrastructure already attached.
Confirm with `catalyst_list_projects`, and pass the project on every call; there is no
current project. A `Project` manifest creates the project it names, so if one is in a
batch, check its `metadata.name`; a differing `project` argument is rejected. Send a
`Project` manifest only when the user explicitly asked for a new project.

## 2. Make sure the App ID exists

Apps, agents and MCP servers are each backed by an identity (an "App ID" in some APIs).
Where a tool asks for or returns `appId`, it means that identity's name. Read it from the
resource's `status.appIds` (the get tools include it). For an agent registered from your
own code, it's the `appId` on its registry record.

1. `catalyst_get_app` for the project and the app name. If it exists and is `ready`, go
   on.
2. If it does not exist, create it with `catalyst_apply`: read
   `catalyst_get_resource_schema` for the `App` kind first, run with `dry_run` and show
   the user, then apply. The project's managed `pubsub` and `kvstore` are already
   there. Apply a component only if the app needs one beyond them,
   and apply it before the app, then any subscriptions scoped to the app in a second
   call (see `catalyst-deploy` for the full ordering), so they exist when its sidecar
   boots. An agent needs none: apply its `Agent` resource and Catalyst provides its
   state, pub/sub and registry (`catalyst-agent-scaffold`). A sample's local
   `resources/` files are for running without Catalyst, so leave them out. An app with
   no endpoint is the correct shape for a pure workflow worker, which dials Catalyst
   outbound.
3. Read it back and wait for `ready`. `updating` right after a local connection attaches
   is normal; give it time before calling it broken.

`catalyst_apply` is a write tool. If it is absent, the user's role cannot write: say so
and stop.

## 3. Running the app locally

The app runs as the user's own process with three values in its environment. Catalyst
hands them out through one tool.

1. Make sure the App ID exists (section 2).
2. Call `catalyst_get_connection` for that project and App ID. For an agent or an MCP
   server, pass the App ID behind it: one tool serves all three. It returns
   `DAPR_API_TOKEN`, `DAPR_GRPC_ENDPOINT` and `DAPR_HTTP_ENDPOINT`. It is a
   write-consent tool and its calls are audited, so the client may ask the user to
   approve it.
3. Start the process (the app, agent or MCP server) with those three values in its
   environment, in whichever of these ways your shell tool allows. Run it yourself, in
   the background:
   - **Inline on the command:**

     ```
     DAPR_API_TOKEN=<token> DAPR_GRPC_ENDPOINT=<grpc> DAPR_HTTP_ENDPOINT=<http> APP_ID=<app-id> uv run main.py
     ```

   - **A `.env` file in the app's folder.** The quickstart samples don't read `.env`
     themselves, so load it into the process's environment when you start it: with
     `uv run --env-file .env main.py`, or with `set -a; . ./.env; set +a` in the same shell
     before the run command. Make sure `.env` is listed in `.gitignore`, and add it if it
     isn't.
   - **Your tool's own environment option**, if it has one.

   Use the user's own run command in place of `uv run main.py`, and the app's own port
   or server flags if it has any (a web app started with `uv run uvicorn main:app
   --port 5001` for example). A pure workflow worker dials Catalyst outbound and needs
   no inbound port.
4. **These are local-dev values, not production secrets.** A deployed app gets its own
   injected by the platform. Never paste `DAPR_API_TOKEN` into the chat, a pull request,
   an issue or a commit. Beyond that it needs no special handling.
5. On a crash or a restart, reuse the same environment. If the token is no longer in hand,
   call the tool again.
6. If `catalyst_get_connection` is missing or refused, say that it is unavailable to
   this role or server, and stop. There is no other route to these values.

Two things about the worker process itself:

- **A worker needs only those values.** A process that registers workflows and activities
  and polls for work items dials Catalyst outbound. It needs no tunnel and no inbound
  port. Do not add an HTTP server just so that a port has something to answer: the worker
  then registers the workflow and every activity successfully and dies at bind because
  something else holds the port, and the startup log reads as healthy right up to the
  error. Do not give it an app port either: `--app-port` on a tunnel, or a
  health-checked app endpoint on its App ID, with nothing listening blocks every workflow
  start (section 7).
- **An app that Catalyst must call into** (service invocation, pub/sub delivery, an agent
  endpoint, the MCP server behind an `MCPServer`) needs an app tunnel as well, and these
  three values do not open one. The `catalyst-app-tunnels` skill covers it. Never use a
  public tunnel instead. `catalyst_list_app_tunnels` lists the tunnels open on the
  project, so you can see whether Catalyst currently reaches a local process.
- **An app or agent that calls an MCP server** calls it through its own sidecar, at
  `$DAPR_HTTP_ENDPOINT/v1.0/diagrid/mcp/<mcpserver-name>` with its `DAPR_API_TOKEN`. It
  never calls the server's own URL, and never calls `dapr.internal.mcp.*` workflows
  (`DaprMCPClient` in the Dapr SDK). `catalyst-agent-scaffold` section 9 has the details.

If the process cannot connect, read the app back (`catalyst_get_app`) before changing
code. Status and the per-identity messages under `status.appIds` say whether the platform
side is ready. Sidecar log reading is at `full` data sharing only (section 5).

## 4. Trigger a run, so there is something to read

Nothing above produces anything until a workflow actually runs. Starting one is a write,
so `catalyst_start_workflow` is absent from the tool list for a role that cannot write —
if it is not there, that is why.

`catalyst_start_workflow` takes the project, the app identity and the workflow name, plus
the input if the workflow wants one. It assigns the instance id and hands it back.

**Capture the instance id.** It is how every later call refers to that run — reading its
status, its history, or stopping it. Losing it means listing runs and guessing which one
was yours, which is ambiguous the moment two runs start in the same second.

**Show the run's console link at every step.** That means when the run starts, whenever
you wait for the user (a crash, an approval, "type continue"), and when it ends. Use the
link the tool response gives. If it gives none, build it from the run:
`https://catalyst.diagrid.io/workflows/<app-id>/<instance-id>?project=<project>`. This
works for an agent's runs too, with the agent's App ID.

Read the result with `catalyst_get_workflow_run`: it returns the execution graph, so you
see which step the run is on or failed at. `catalyst_list_workflow_runs` finds runs when
you lost the id.

Stopping a run is a separate matter and is deliberately not in this skill — it is
irreversible and belongs with diagnosis rather than iteration (`catalyst-debug`).

### Watch a run survive a crash

This is the quickest way to see what durability buys:

1. Start a run, then kill the process mid-run. Use the sample's crash endpoint if it has
   one, otherwise stop the process.
2. `catalyst_get_workflow_run` now shows the run **RUNNING and waiting for a worker**, not
   failed. The steps that finished are already in its history.
3. Restart the process with the same connection values (section 3, step 5).
4. When the run completes, its history shows that every step that finished before the
   crash ran once, and only the step the crash cut off ran again.

That re-run is expected, because activities run at least once. Never say "nothing ran
twice". An activity with a side effect must be safe to repeat (`catalyst-activity-idempotency`).

## 5. Read the output while you develop

Three different sources, and picking the wrong one is why bugs look invisible.

| Source | How | What it carries |
| --- | --- | --- |
| Your process | Its own terminal or log file, where you started it | Whatever your code prints. Catalyst never sees it |
| The run | `catalyst_get_workflow_run` | Status, the execution graph, step errors. `input`, `output` and `customStatus` are withheld at the default data-sharing level |
| The sidecar's API log | `catalyst_get_logs`, at `full` data sharing only | One entry per Dapr API call the app made, with status, method and error |

`catalyst_get_logs` returns `DATA_SHARING_RESTRICTED` at the default `metadata` level.
That is policy, not a fault: do not retry it, say the logs were not shared at this
organization's data-sharing level, and use the other two sources. `catalyst_get_metrics`
shows request and error rates for the app when the question is "is anything arriving at
all".

**An absent field is not an empty one.** Never report a missing `output` as "the workflow
produced no output". Say it was not shared at this level.

## 6. Iterating without touching the platform

A code change needs nothing but your process restarted: stop it, start it again with the
same environment, and the app, components and subscriptions are found rather than made.

What genuinely does require a platform change:

| Change | Why |
| --- | --- |
| A new component or subscription | It has to exist before the sidecar that loads it boots |
| A component's **type** | Immutable. It must be deleted (`catalyst_delete_resource`, with the user's agreement) and applied again, and that includes converting to or from a Diagrid managed type |
| A new app | Nothing can reference an app that does not exist yet |
| The app's health-check or protocol settings | An app's identity spec is not updated in place; read it, change it and apply it whole |

A component pointing at a local address is not translated for you: Catalyst components
are applied as written, so point state and pub/sub at the project's managed `kvstore`
and `pubsub` rather than at a local broker.

## 7. When the worker does not come up

Route by what you actually saw. Guessing here wastes a whole iteration.

| Symptom | Cause | Do |
| --- | --- | --- |
| `catalyst_get_connection` missing or refused | Not available to this role or server | Say so and stop |
| `catalyst_get_app` says the app does not exist | Wrong name or project | Check the name with `catalyst_list_apps` |
| The app is not `ready` | Still provisioning, or a component failed | Read `status.appIds` messages; `catalyst_list_components` and then `catalyst-debug` |
| The worker starts but no run ever appears | The project has no managed workflow store, or the store was enabled after the app | Read the project with `catalyst_get_project`; the sidecar reads workflow configuration at boot, so the app may need re-creating after the store is enabled |
| The worker is connected but a run fails | An application error | `catalyst_get_workflow_run` for the failing step |
| Every workflow start fails with `failed to create workflow instance: context canceled` | The worker runs behind an app tunnel opened with `--app-port`, or its App ID has an app endpoint with the health check enabled, and nothing answers there. Catalyst starts no workflows or actors until the app's health check passes | Remove the app port: clear the endpoint on the App ID (read it, drop the endpoint, apply it whole), or run it without `--app-port` (`catalyst-app-tunnels`). Keep one only for a process that serves Catalyst's calls |
| Bind error on startup in a worker that never needed a port | An HTTP server was added unnecessarily | Remove it; see section 3 |
| A component is not ready | A component, not your app | `catalyst_get_component`, then `status.appIdStatus[]` |
| `component must be deleted to be updated ...` | You changed a component's type | Delete it and apply it again |
| `agent-*` components rejected | No matching Agent resource exists | Apply the `Agent` first; `agent-registry` is managed by Diagrid, do not create it |

Two quieter failure modes with no error to search for:

- **A setting that does nothing.** Catalyst applies components as written and ignores
  Dapr settings that belong to a self-hosted sidecar. If a setting appears to have no
  effect, read the resource back before debugging your code.
- **The app is ready and requests still do not arrive.** Check
  `catalyst_list_app_tunnels`: with no tunnel open on that App ID, nothing in Catalyst can
  reach the local process (`catalyst-app-tunnels`, which can also print requests as they
  arrive). Then check `catalyst_get_metrics` for the app.

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **Name the organization before the first write.** Before the session's first
  `catalyst_apply`, `catalyst_delete_resource` or any other call that creates, changes
  or deletes something, call `catalyst_whoami` and tell the user which organization the
  change lands in. A user with more than one organization cannot otherwise tell where it
  went. If it fails, follow `catalyst-setup` and write nothing.
- **Use `default`; only if it is absent, offer to create a project and wait for the user's
  agreement.** Never reuse a misconfigured project. Check the project name before the first
  call of a session.
- **Set the connection values inline, in a gitignored `.env`, or through your tool's
  environment option**, and never paste `DAPR_API_TOKEN` into chat, a pull request, an
  issue or a commit.
- **Do not fall back to anything else when a tool is missing or refused.** Say it is
  unavailable to this role or server, and stop.
- **Say which source a line came from.** Your process, the run and the sidecar log fail
  differently, and a conclusion drawn from the wrong one sends the user to the wrong place.
- **Wait for readiness rather than retrying past it.** Re-creating a resource resets its
  timers and makes a slow provision look like a hang.
- **Do not delete resources to test a code change.** Nothing in an edit-run-observe cycle
  needs a component or app recreated.
