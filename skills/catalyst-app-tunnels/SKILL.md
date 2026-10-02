---
name: catalyst-app-tunnels
description: Open an app tunnel so Diagrid Catalyst can call into a process on this machine, with `diagrid dev run` or `diagrid listen`. Use for service invocation between laptop apps, pub/sub delivery, or an agent calling an MCP server on localhost.
---

# App tunnels: letting Catalyst call into this machine

Goal: end this skill with Catalyst able to reach a process on the user's machine, on a
port of their choosing, under a Catalyst identity, and with a request proven to have
arrived through it.

`catalyst_get_connection` (the `catalyst-develop` skill) gives a local process
**outbound** access only: it can call its sidecar, start workflows, publish. Nothing in
Catalyst can call **back** into it. That needs an app tunnel, and no `catalyst_*` tool
opens one. This is the one place these skills use the Diagrid CLI, and only for the
commands below. Everything else (creating resources, granting access, reading status)
still goes through the `catalyst_*` tools.

**Never reach for a public tunnel** (cloudflared, ngrok, a port-forward to a public
address) to give Catalyst a URL. An app tunnel keeps the traffic under the identity and
access policy of the App ID it serves. A public URL bypasses both, and anyone who learns
it can call the process.

## 1. Does this need a tunnel?

| The local process… | Needs a tunnel? | Use |
| --- | --- | --- |
| Is a workflow worker that registers workflows and polls for work | No | `catalyst-develop` |
| Only calls its sidecar (starts workflows, publishes, reads state, calls an MCP server through Catalyst) | No | `catalyst-develop` |
| Is the **target** of service invocation from another app | Yes | Section 4 |
| Receives pub/sub messages or input bindings | Yes | Section 3 |
| Is the endpoint behind an `Agent` resource that Catalyst calls into | Yes | Section 3 |
| Is the MCP server behind an `MCPServer` resource | Yes | Section 5 |
| Does not exist yet, and you want to see what Catalyst would send it | Yes, with `diagrid listen` | Section 6 |

A caller that is not itself called needs no tunnel. In "agent calls a tool on an MCP
server on this machine", only the MCP server is tunneled; the agent is a caller.

## 2. Install the CLI and sign in

1. Check whether it is installed: `diagrid version`.
2. If not, **ask the user before installing it**, as you would before any download that
   runs on their machine. The installer is
   `curl -o- https://downloads.diagrid.io/cli/install.sh | bash`. On Windows, point the
   user at the PowerShell installer at `https://downloads.diagrid.io/cli/install.ps1`.
3. `diagrid login` opens a browser to sign in. This is a **separate sign-in** from the
   Catalyst MCP server, and only the user can complete it. Ask them to run it; never ask
   for a token or key instead.
4. Confirm both sign-ins land in the same organization: compare `diagrid whoami` with
   `catalyst_whoami`. A tunnel opened in one organization serves nothing that the
   resources created through MCP in another organization can see.

## 3. `diagrid dev run`: one process behind one identity

```
diagrid dev run --project <project> --id <app-id> --app-port <port> --yes -- <command>
```

- **`--project` has no short form here.** In `dev run`, `-p` means `--app-port`. Always
  write `--project <name>` in full. It is the user's existing project, normally
  `default`; `dev run` creates a project it cannot find, and these skills never create
  projects.
- **`--app-port` is what opens the tunnel.** Without it the process gets outbound access
  only, exactly as with `catalyst_get_connection`.
- **Give `--app-port` only to a process that serves on that port.** Catalyst
  health-checks the app through the tunnel, and until a check answers it starts no
  workflows or actors and delivers nothing to the app. A workflow worker or a pure caller
  with an app port and no server behind it fails every workflow start with
  `failed to create workflow instance: context canceled`. Leave the flag off for those
  (section 1).
- **The command after `--` is started for you**, with `DAPR_APP_ID`,
  `DAPR_HTTP_ENDPOINT`, `DAPR_GRPC_ENDPOINT` and `DAPR_API_TOKEN` already in its
  environment, so `catalyst_get_connection` is not needed. Leave the command off to
  tunnel a process the user already started on that port. **When that command exits,
  `dev run` exits too**, so an app that crashes on startup takes the tunnel down with
  it; read the app's output first.
- The app's own settings go in two ways. **Secrets** (an LLM key, say) go in a
  gitignored `.env` that the command itself loads:
  `-- sh -c 'set -a; . ./.env; set +a; exec <command>'`. Never let a `.env` override the
  four values `dev run` injects. `-e NAME=value`, repeatable, is for **non-secret**
  values only: it puts the value in the command line, the process list and the
  transcript.
- **`--yes`** skips the confirmation prompt, which a background shell cannot answer.
- It runs in the foreground until stopped. Start it in the background with your shell
  tool and keep its output; that output is where tunnel and app errors appear. Note its
  process ID, which is how you stop it (below). `-a` is the short form of `--id` in
  `dev run`, `dev stop` and `listen`; `dev scaffold` takes no `--id`.
- `--rm-appids` deletes the App IDs that this run created when it stops. It suits a
  throwaway app; never use it on an App ID that existed before.

**Stopping a tunnel.** Ending the process does not always close the tunnel:

- Stop `dev run` with SIGINT: `kill -INT <pid>` on the `dev run` process you started in
  the background (not on the app it started), or Ctrl-C if the user runs it in their own
  terminal. That stops the app it started and closes the tunnel.
- If it was killed instead (SIGKILL, a background-task time limit, a crash of the app),
  the tunnel record stays `ready` with nothing behind it. Run
  `diagrid dev stop --id <app-id> -p <project>` to close it (in `dev stop`, `-p` is the
  project).
- On older CLIs, `dev stop` can leave the app that `dev run` started still running on
  its port. Check the port with `lsof -i :<port>` afterwards and stop the leftover.
- After a stop, the tunnel takes up to a minute to finish closing. Until
  `catalyst_list_app_tunnels` no longer lists the App ID, an apply or a grant on it is
  still refused, and a new `listen` on it can fail with `local app connection not found`.
  Wait for it to go, then retry.

What it does to the platform:

- **It creates the App ID if it is missing, and does not provision one that exists.**
  While the tunnel is open, though, Catalyst points that App ID's endpoint at the tunnel,
  so `catalyst_get_app` shows a different `appEndpoint` and a higher resource version.
  Closing the tunnel restores the original endpoint. That is the tunnel working, not a
  change to undo.
- **For an `Agent` or an `MCPServer`, create that resource first** with `catalyst_apply`.
  Run `dev run` before it exists, and `dev run` creates a plain App ID of that name. The
  Agent or MCP server then refuses to adopt it and stays in error (`catalyst-deploy`).
  For a resource that already exists, `dev run` prints that the App ID is managed by it
  and skips provisioning. That is correct.
- **The tunnel needs the App ID to be `ready`, and `dev run` gives up after about 100
  seconds** with an error containing `not ready` (`app <id> not ready`, which newer CLIs
  follow with the status and its messages), without starting the command. Right after
  creation, readiness can take a minute or two. So when an Agent or MCP server is new,
  read its App ID with `catalyst_get_app` until it is `ready`, then start `dev run`. If
  `dev run` already gave up, run it again once the App ID is `ready`. Once the tunnel
  attaches, the App ID goes `ready` → `updating` → `ready`, which is normal.
- **The port must be free.** With `-- <command>`, an old copy of the server still
  holding the port makes the new one fail to bind, or leaves the stale copy answering
  every tunneled request. Check the port before starting (`lsof -i :<port>`), and stop
  what holds it only if it is the user's own leftover process.
- **While a tunnel is open, that App ID cannot be updated.** A `catalyst_apply` to it, or
  an access grant that has to attach a policy to it, is refused with a message telling
  you to stop the tunnel. Stop the tunnel and wait for it to close (above), make the
  change, start it again.
- `catalyst_list_app_tunnels` lists the tunnel records on a project. A record can stay
  `ready` after its `dev run` has exited, so it shows that a tunnel was opened, not that
  one is live. Proof of a live tunnel is a request arriving in the local process's own
  log.

**Several processes at once:** `diagrid dev scaffold -p <project>` writes a multi-app
run file (`apps:` with `appID`, `appPort`, `command`, `env`). Then run
`diagrid dev run -f <file>`. `--id` and `-f` cannot be combined.

## 4. App to app: service invocation between two local apps

1. Run the **target** with a tunnel:
   `diagrid dev run --project default --id orders --app-port 5002 --yes -- <command>`.
2. Run the **caller** under its own identity. It needs `--app-port` only if something
   also calls into it:
   `diagrid dev run --project default --id checkout --yes -- <command>`.
3. The caller invokes the target through Catalyst, never at `localhost:5002`:
   - Over HTTP: `POST $DAPR_HTTP_ENDPOINT/v1.0/invoke/orders/method/<method>` with the
     header `dapr-api-token: $DAPR_API_TOKEN`.
   - With a Dapr SDK, its service-invocation call with app ID `orders`. The SDK reads
     the endpoint and the token from the environment.
4. Calls between apps in a project are allowed unless an access policy restricts them.
   To restrict them, use `catalyst_grant_access` with `target_kind: app` (or `agent`).
   **Grant before you open the target's tunnel**, because attaching the policy updates
   the target's App ID (section 3). The first grant on an app creates a Configuration
   named after it. With `action: deny` its default becomes deny, and a denied call is
   refused with 403 before it reaches the target. Delete that Configuration along with
   the app when you clean up.
5. Prove it: the target's own log shows the request, and `catalyst_get_metrics` for the
   target shows it served something. A call that goes straight to `localhost` proves
   nothing about Catalyst.

## 5. An app or agent calling an MCP server on this machine

The `MCPServer` resource owns an identity with **the same name** as the server, and
that identity is the one to tunnel. Do not create an App ID for the MCP server, and do
not tunnel the caller.

1. **Start the MCP server process** over streamable HTTP, for example on
   `127.0.0.1:8000` at path `/mcp`. Requests arrive with the tunnel's host, not
   `localhost`. A server that checks the `Host` header (FastMCP's DNS-rebinding
   protection, for one) rejects them until that check is relaxed for local development.
2. **Create the `MCPServer`** with `catalyst_apply`, after reading
   `catalyst_get_resource_schema` for the kind and showing the user a `dry_run`. Set
   `spec.endpoint.streamableHTTP.url` to the local URL, for example
   `http://127.0.0.1:8000/mcp`. When its identity is tunneled, Catalyst keeps only the
   **path** of that URL and replaces the host with the tunnel's. So the path must be the
   one the server serves, and the host does not matter.
3. **Wait for its identity to be `ready`** (`catalyst_get_mcp_server`, under
   `status.appIds`). The server itself may report that it cannot reach its upstream until
   the tunnel opens. That is expected at this step.
4. **Open the tunnel on the MCP server's identity**:
   `diagrid dev run --project default --id <mcpserver-name> --app-port 8000 --yes`.
   Add `-- <command>` to have `dev run` start the server instead of step 1.
5. **Grant the caller access.** MCP server access is **deny-all by default**, and the
   server's `scopes` do not grant anything. Use `catalyst_grant_access` with
   `target_kind: mcp_server`, the server as `target`, the caller's identity in `callers`,
   and the tool names in `tools` (`*` for all). Grant only the tools the user asked for,
   and leave destructive ones out unless they asked for them by name. This writes the
   server's access policy, not its App ID, so it works while the tunnel is open.
6. **Run the caller under its own identity**: an `Agent`'s App ID, or an app's. Use
   `dev run` without `--app-port` if it is only a caller, or `catalyst_get_connection`
   (`catalyst-develop`).
7. **The caller reaches the server through its own sidecar**, never at the local URL:
   - Discovery: `GET $DAPR_HTTP_ENDPOINT/v1.0/diagrid/mcp` with
     `dapr-api-token: $DAPR_API_TOKEN` lists the servers this caller is granted, each
     with a `connect.path`.
   - MCP: `POST` JSON-RPC to `$DAPR_HTTP_ENDPOINT` + that `connect.path` (for example
     `/v1.0/diagrid/mcp/<mcpserver-name>`), with `Accept: application/json,
     text/event-stream`. Speak streamable HTTP MCP as to any server: `initialize` first,
     then send the `Mcp-Session-Id` it returns on every later request. A client that
     skips `initialize` gets 400s. Any MCP client library does this for you.
   - Anything after the server name is appended to the spec URL's path. With a spec URL
     ending in `/mcp`, post to the bare name, or the upstream sees `/mcp/mcp`.
8. **Prove it.** `catalyst_get_mcp_server` lists the server's tools. The caller's
   discovery lists the server only after the grant, and its `tools/list` shows only the
   granted tools. A granted tool call shows up in the MCP server's own log. A tool left
   out of the grant is refused with 403, and never reaches the server.

**Use the HTTP endpoint above for an MCP server behind a tunnel.** Some SDKs and
frameworks call MCP tools as workflows instead (`dapr.internal.mcp.<name>.*` child
workflows, which is what the Dapr Python SDK's `DaprMCPClient` does). That is not
the path to build an agent on anywhere, and it does not go through the tunnel. Its calls
never reach the server on this machine, and the parent workflow waits forever rather than
failing. So if the agent's
code schedules those workflows, tell the user it cannot use an MCP server on this
machine yet, and point it at the HTTP endpoint instead. The HTTP proxy working proves
nothing about the workflow path.

**Tear down in this order:** stop the tunnel, then delete the `MCPServer`. An open
tunnel blocks the delete of its identity.

## 6. `diagrid listen`: see what Catalyst sends, with no app yet

```
diagrid listen --id <app-id> -p <project>
```

It tunnels an **existing** App ID to a built-in server and prints every request that
arrives: invocations, pub/sub deliveries, binding events. It never creates the App ID,
so create it first. `--subscription <name>`, `--binding <name>` and `--invoke <method>`
answer those requests; `--invoke <method>!` answers with a 500. Use it to check that a
subscription routes or an invocation arrives before writing the handler. For real code,
use `dev run`.

The request body is printed **base64-encoded**, so it is not garbled. The shape differs
by mode: with no handler flag each request shows `method`, `url` and `body`; under
`--invoke` it shows `data` and `contentType`.

**`listen` leaves the tunnel open when you stop it**, and says so. Before running
`dev run` on the same App ID, run `diagrid dev stop --id <app-id> -p <project>` and wait
for the tunnel to close (section 3).

## 7. When it does not work

| Symptom | Cause | Do |
| --- | --- | --- |
| `dev run` exits with an error containing `not ready` | It gave up waiting for the App ID (section 3) | Read the App ID with `catalyst_get_app`. Once it is `ready`, run `dev run` again. If it has sat in `processing` for over 10 minutes, report it as a platform problem; do not delete and re-create it |
| `App ID "<other>" must be in ready status in order to scaffold dev session configuration`, naming an App ID this run does not use | Older CLI versions require **every** App ID in the project to be `ready`, and stop the app they just started | `catalyst_list_apps` to find the one that is not `ready`. Wait for it, or ask the user before deleting it if it is theirs and unused |
| The `Agent` or `MCPServer` is in error after a `dev run` | `dev run` created a plain App ID of that name first | With the user's agreement, stop the tunnel, delete the App ID (`catalyst_delete_resource`) and apply the resource again |
| An apply or a grant is refused, naming `dev stop` | A tunnel is open on that App ID, or is still closing | Stop it, wait until `catalyst_list_app_tunnels` no longer lists it, make the change, start it again |
| The MCP server answers 4xx to every tunneled request | It rejects the tunnel's `Host` header | Relax its host check for local development (section 5, step 1) |
| The upstream sees `/mcp/mcp` | The proxy path repeated the spec URL's path | Post to the bare `/v1.0/diagrid/mcp/<name>` |
| Every workflow start fails with `failed to create workflow instance: context canceled` | `dev run` has `--app-port`, and nothing listens on that port, so the app's health check never passes | Run it again without `--app-port` if nothing calls into the process (section 1); otherwise start the server on that port |
| `catalyst_list_app_tunnels` shows a tunnel `ready`, yet nothing arrives | The record outlived its `dev run` | Check that `dev run` is still running; start it again |
| A workflow that calls `dapr.internal.mcp.<name>.*` stays running with nothing after `ExecutionStarted` | The workflow path does not reach an MCP server behind a tunnel | Call the server through `/v1.0/diagrid/mcp/<name>` instead (section 5) |
| The caller's discovery is empty, or the call returns 404 | No grant for that caller | `catalyst_get_access_policy`, then `catalyst_grant_access` |
| CLI commands land in a different organization | The CLI and the MCP server are signed in to different organizations | Compare `diagrid whoami` with `catalyst_whoami` (section 2) |

## Rules

- **The CLI is for tunnels only:** `diagrid version`, `login`, `whoami`, `dev` and
  `listen`. Create, grant, read and delete through the `catalyst_*` tools, as every other
  skill does.
- **Never use a public tunnel or a public URL** to let Catalyst reach a process on this
  machine.
- **Create the `Agent` or `MCPServer` before running `dev run` on its name.**
- **Tunnel the identity being called**: the MCP server's own identity, the target app's.
  Never the caller's, and never a workflow worker's.
- **Name the organization before the first write** (`catalyst_whoami`), and use the
  existing project: `default` unless the user named another.
- **Never ask the user for a token.** `diagrid login` and `dev run` handle credentials,
  and `DAPR_API_TOKEN` never goes into chat, a pull request, an issue or a commit.
- **Prove the request arrived through Catalyst**, in the receiving process's own log, and
  say so. A call made straight to `localhost` proves nothing.
