---
name: catalyst-agent-scaffold
description: Build or stand up a Durable Agent on Diagrid Catalyst — your own agent app, fronted by a Catalyst agent resource. Use for an AI agent, a coordinator-and-specialists topology, or to give an agent memory that survives restarts.
---

# Scaffold a Durable Agent on Catalyst

Goal: end this skill with one agent that answers a real prompt and survives being
killed mid-run. Durability is the whole point — an agent that only works when nothing
crashes is a chat loop, not a Durable Agent.

## 1. Know which resource you are looking at

The Catalyst resource for an agent is the **`Agent`** kind: a connectivity and archiving
resource in front of an agent that **your** app runs. Your process runs the loop, you
write the code, and the resource takes an endpoint and archive settings. You create it
with `catalyst_apply` (read `catalyst_get_resource_schema` for the `Agent` kind first, run
with `dry_run`, show the user, then apply), which needs a write role.

If the user asks for Catalyst to host or run the agent for them, say it is not something
you can set up, and continue with their own app fronted by an `Agent`. That starts at
section 3.

**Never write "create an agent" unqualified.** Say which resource you mean: an `Agent`
fronting their app, or their own agent code.

## 2. Read the schema before writing the manifest

Do not write an `Agent` manifest from memory. `catalyst_get_resource_schema` returns the
fields the kind takes and the platform rejects unknown ones; a guessed field name that
happens to be accepted can mean something else. An `App` is a different resource with
different fields, so check which one you are writing.

## 3. Your-own-app path: detect the language first

Language and framework are parameters of this skill, not variants of it. Read the
repository before choosing anything.

| Found at the top level | Language |
| --- | --- |
| `pyproject.toml`, `requirements.txt`, `*.py` | Python |
| `*.csproj`, `*.sln`, `global.json` | .NET |
| `pom.xml`, `build.gradle` | Java |
| `go.mod` | Go |
| `package.json`, `tsconfig.json` | TypeScript |

## 4. Check the adapter is installable before promising it

The adapter is what makes an agent framework run as a durable workflow. It is at a
different stage in each language, and that difference decides what you can scaffold.

| Language | Coordinate | State |
| --- | --- | --- |
| Python | `diagrid[<framework>]` on PyPI, 0.5.0 | Widest coverage — 11 frameworks — and exercised against live Catalyst |
| .NET | `Diagrid.AI.Microsoft.AgentFramework` on NuGet, 1.2.0 | Published. Microsoft Agent Framework; targets net8.0, net9.0, net10.0 |
| Java | `io.diagrid:diagrid-spring-ai-starter` on Maven Central, 0.4.0 | Published, Spring AI. Its own README says the APIs are not yet stable |
| Go | `github.com/diagridio/go-ai` v0.2.0; adapters `github.com/diagridio/go-ai/adapters/langchaingo` v0.1.1 and `github.com/diagridio/go-ai/adapters/eino` v0.1.1 | Published. Each adapter is its own module with its own release tag, built in CI |
| TypeScript (Mastra) | `@diagrid/agent-mastra` on npm, 0.2.0 | Published and public, with provenance, Mastra only — not a general TypeScript adapter. Needs Node >= 22.13.0. First published 2026-08-23, so treat it as early |
| TypeScript (anything else) | none | No adapter. The options below are unchanged |

For **TypeScript**, the answer depends on the framework, and getting that wrong sends
someone to install a package that cannot bridge what they are using.

On **Mastra**, scaffold against the adapter. It depends on `@diagrid/agent-core`, which
therefore arrives transitively — do not ask anyone to install it. `@mastra/core` and
`zod` are peer dependencies, so npm will not install them for you and they have to be
listed explicitly:

```bash
npm install @diagrid/agent-mastra @mastra/core zod
```

The peer ranges are `@mastra/core >=1.50.0 <2` and `zod ^4.0.0`, and it ships its own
types. Its licence is BUSL-1.1, which is not what a user may assume from the other
adapters — worth one sentence if they are evaluating rather than already committed.

Include `zod` even though the adapter's own README omits it. The manifest declares it
as a required peer, so following the README leaves an unmet peer dependency.

On **any other TypeScript framework** there is still no adapter, and the honest options
are unchanged: write the agent in a language whose framework has a published adapter,
or drive Dapr Workflows directly with `@dapr/dapr`, which is published and does support
workflows — that loses the framework bridge, not durability. There is no other
route (section 1).

For **Go**, the adapters are separate modules from the root, so each is fetched and pinned
by its own tag: `go get` the root module at its version, then the adapter the framework
needs at the adapter's version. Do not assume the two share a version number — they do
not.

Never emit a package coordinate you have not watched resolve. A confidently wrong
package id is worse than no skill at all: it sends the user to debug Catalyst for a
problem that is a typo. The `@diagrid/agent-mastra` line above was checked that way —
installed, not read off a registry page.

## 5. Python specifics, since it is the widest path

Install the framework as an extra on the single PyPI package named `diagrid`. There is no
per-framework distribution:

```
pip install "diagrid[langgraph]"
```

The 11 frameworks are `langgraph`, `crewai`, `adk`, `strands`, `pydantic_ai`,
`openai_agents`, `claude_agents`, `langchain`, `smolagents`, `deepagents` and
`holmesgpt`. Two traps: the extras use **underscores** where the framework's own name
uses a hyphen, and `holmesgpt` conflicts with the others and needs its own environment.
Python 3.11 or later, below 3.14.

Import the runner from the framework's module: `DaprWorkflowAgentRunner` for most,
`DaprWorkflowGraphRunner` for LangGraph, `DaprWorkflowDeepAgentRunner` for Deep Agents,
`DaprWorkflowHolmesRunner` for HolmesGPT. Then `runner.serve(...)` exposes the app.

Components are discovered **by name**, not by configuration. Outside Catalyst, ship the
app's own components as `agent-memory`, `agent-pubsub`, `agent-registry`, `agent-configuration` and
`agent-runtime`, or discovery silently finds nothing and the failure looks like a
connectivity problem. These are the app's components, distinct from the project's managed
`pubsub` and `kvstore`. On Catalyst, apply the `Agent` resource and let the platform
provide its state, pub/sub and registry. The platform creates `agent-registry` and refuses
one created by hand. A sample's local `resources/` files are for running without Catalyst.

To start from a working tree rather than a blank file, `diagridpy init <name> --framework
<framework>` clones a template. It covers fewer frameworks than the extras list, so check
what it offers before promising a specific one.

For .NET, register with `AddDaprAgents(...)`, then `.WithAgent(...)` and
`.WithCatalyst()`. There is no `DurableAgent` type in .NET — durability comes from the
agent running as a workflow. For Java, putting the starter on the classpath is the whole
integration; note that only `ChatClient.call()` is durable today, not `.stream()`.

## 6. Use the project named `default`

**Do not create a project.** Every organization gets `default`, with managed pub/sub, a
managed KV store, the workflow store and agent infrastructure already attached. Agent
infrastructure comes with the managed KV store.

`default` is bootstrapped once, when the organization is first reconciled, and it is not
recreated if someone deletes it. Check with `catalyst_list_projects`; if it is gone, ask
which project to use rather than creating one. The managed components have fixed names,
`pubsub` and `kvstore`, and the managed workflow store has none.

## 7. Fit the topology to one pub/sub

A project holds **one managed pub/sub and one managed KV store** on every plan. It is a platform default rather than a free-tier limit, and
no plan upgrade raises it, so never offer an upgrade as the fix. (A negotiated
per-organization override exists; a live quota read beats this document.)

A coordinator with specialists therefore **shares one broker and separates the agents by
topic**, one topic per specialist plus one for results. Design for that from the start;
it is not a workaround.

Budget the resource slots before scaffolding: every app, agent and MCP server counts as
one identity against a per-region allowance, and a coordinator plus four specialists is
five of them. Read the allowance with `catalyst_get_usage` rather than quoting a figure,
and do the same for throughput limits.

## 8. Run it, then kill it

- Make sure the `App` and the `Agent` exist (`catalyst_get_app`, `catalyst_get_agent`).
- Start the agent process with the connection values in its environment:
  `catalyst-develop` section 3 is the one place that says how, using
  `catalyst_get_connection`.
- Send a prompt, wait for it to be mid-run, kill the process, start it again.
- The run must resume rather than restart. If it restarts, the agent is not durable and
  the scaffold is not finished — usually the workflow store or a component name.

Apps, agents and MCP servers are each backed by an identity (an "App ID" in some APIs).
Where a tool asks for or returns `appId`, it means that identity's name. Read it from the
resource's `status.appIds` (the get tools include it). For an agent registered from your
own code, it's the `appId` on its registry record.

An agent exposes an endpoint Catalyst calls into, so unlike a pure workflow worker it
needs an inbound port and a registered endpoint. Run on a laptop, that endpoint is
reached through an app tunnel on the agent's App ID (`catalyst-app-tunnels`). The same
goes for an MCP server on this machine that the agent calls tools on: it is tunneled
behind its own `MCPServer`, and the agent is granted access to its tools.

**An absent field is not an empty one.** An agent's turn runs as a workflow, and workflow
payloads are withheld by default — withheld by deleting the key, not by returning an
empty value. Over MCP tools, `input`, `output` and `customStatus` are all removed at the
default `metadata` data-sharing level, and only an organization administrator can raise
the level to `full`. Never forge a data-sharing header, and never ask an administrator to
raise the level so you can finish an answer.

So never report a missing payload as "the agent produced no output". Say it was not
shared at this organization's data-sharing level, name the level, and link the console
run (section 10). A tool that refuses is likewise not an agent that failed; report the
refusal.

## 9. Give it MCP tools through its own sidecar

An agent calls the tools of a Catalyst `MCPServer` through **its own sidecar's MCP
proxy**. That is the path Catalyst supports, and the one where the server's access policy
is enforced:

- **Discovery:** `GET $DAPR_HTTP_ENDPOINT/v1.0/diagrid/mcp` with
  `dapr-api-token: $DAPR_API_TOKEN` lists the servers this identity is granted, each with
  a `connect.path`.
- **Calls:** point any streamable HTTP MCP client at `$DAPR_HTTP_ENDPOINT` + that
  `connect.path` (`/v1.0/diagrid/mcp/<mcpserver-name>`), with the same header. There is
  no Catalyst-specific MCP SDK. The framework's own MCP client or the `mcp` package works
  unchanged.
- **Access is deny-all until granted.** Use `catalyst_grant_access` with
  `target_kind: mcp_server`, and grant only the tools the user asked for. A
  caller's `tools/list` then shows only the granted tools, and a call to any other tool
  is refused with 403. To verify a grant, make exactly those two calls as the
  agent's identity.

Where the adapter has no MCP wiring of its own, wrap each MCP call in one of the agent's
tools, so the runner records it like any other tool call and a replayed run does not call
it twice.

**Do not call MCP tools as workflows, even though the Dapr SDK ships that path.** The
Dapr Python SDK's `DaprMCPClient` (`dapr.ext.workflow`) calls MCP tools as
`dapr.internal.mcp.<server>.ListTools` and `CallTool.<tool>` child workflows. That is not
the path to build an agent on: it does not go through app tunnels, and a call that cannot
reach its server leaves the parent workflow running forever instead of failing. If the
user's code already uses it, say so and move it to the proxy.

## 10. Hand back a link, not a claim

Once the agent exists, give the user a console link rather than asking them to trust the
transcript. The console for the production server is `https://catalyst.diagrid.io`. Only these routes exist:

| To show | Route |
| --- | --- |
| An agent | `/agents/<appId>/<agentId>` |
| The app it runs in | `/apps/details/<appId>` |
| A run of the agent's workflow | `/workflows/<appId>/<runId>` |
| An MCP server | `/mcp-servers/<id>` |

An agent's `<agentId>` is not its name. It is the `agent_id` on the agent's registry record,
from `catalyst_list_agents` or `catalyst_get_agent`, and looks like
`O5SWC5DIMVZC2YLTONUXG5DBNZ2A`. Copy it from that answer; a link built from the name
opens a page that cannot find the agent. An agent with no registry record yet takes its
app ID in both places: `/agents/<appId>/<appId>`.

There is **no project detail page** and **no quota page**. Do not link to either.

The project rides along as a query parameter, and the two spellings do not fall back to
one another:

- `?project=<name>` for a name-like id, such as `default`
- `?projectId=<uid>` for a numeric uid, `prj-` prefix optional
- If both appear, `projectId` wins

Put a numeric uid into `?project=` and the console looks for a project literally named
after that number, finds none, and **silently falls back to the user's default project**
— no error, just the wrong data. Name goes in `project`, number in `projectId`, and if
you cannot tell which you hold, omit the parameter.

If you cannot establish a link you trust, print the identifiers as plain text — **a link
that 404s or lands on the wrong project is worse than no link.**

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **Do not offer to host the agent on Catalyst.** The path is their own app fronted by
  an `Agent` resource.
- **Read `catalyst_get_resource_schema` before applying a manifest.** A remembered field
  name can quietly mean something else.
- **Do not create a project.** Use `default`.
- **Do not name a package coordinate you have not resolved**, and say plainly when a
  language has no installable adapter instead of guessing one.
- **Do not scaffold per-language or per-framework variants of this skill.** One skill
  detects both; a shelf of near-identical skills competes for the same request and loses.
- **Do not offer an upgrade as the fix for the single pub/sub or KV store.** It is 1 on
  every plan, so no plan change buys a second one. Read the live quota rather than
  asserting the 1 — see section 7.
- **Never report a withheld field as an empty result.**
- **Never guess at a console URL.** Use the routes above, put the project in the right
  parameter, and print plain identifiers when you cannot build a link you trust.

