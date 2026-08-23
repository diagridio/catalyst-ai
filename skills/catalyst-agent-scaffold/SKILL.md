---
name: catalyst-agent-scaffold
description: Build, host or stand up a Durable Agent on Diagrid Catalyst, Catalyst-hosted or your own app behind an App ID. Use for an AI agent, a coordinator-and-specialists topology, or to give an agent memory that survives restarts.
---

# Scaffold a Durable Agent on Catalyst

Goal: end this skill with one agent that answers a real prompt and survives being
killed mid-run. Durability is the whole point — an agent that only works when nothing
crashes is a chat loop, not a Durable Agent.

## 1. Know which resource you are looking at

Catalyst has two agent resources with confusingly similar names. You will rarely get to
choose between them, but you must never conflate them.

| | `diagrid agent` | `diagrid managed-agent` |
| --- | --- | --- |
| What it is | A connectivity and archiving resource in front of **your** app | A Durable Agent that Catalyst hosts and runs |
| Who runs the loop | Your process | Catalyst |
| You write code | Yes | No |
| Shape | `--endpoint`, `--archive-*` | `--llm-provider`, `--llm-model`, `--sandbox`, `--web-tools`, `--github-*` |
| Can the user create it | Yes | **No — hidden, gated to Diagrid accounts, and feature-gated per environment on top** |

**`managed-agent` is not an option any user can pick today, and it is gated three times
over.** Verified at v1.66.0:

1. The parent command sets `Hidden = true` unconditionally, so it is absent from
   `diagrid --help` for everyone.
2. Every subcommand — `list`, `get`, `create`, `update`, `delete`, `chat`, `runs` —
   carries a pre-run gate that refuses unless the logged-in account's email ends in
   `@diagrid.io`.
3. **Past both of those, the environment refuses anyway.** A Diagrid account on
   production gets `Durable agents are not available in this environment / Ensure you are
   using the latest Diagrid CLI and that the feature is enabled for your account`.

That third layer matters because it decides what you should predict. Do not tell a Diagrid
user they will hit a permission error — they will not; they will be told the feature is not
enabled for their account, which is a different problem with a different remedy. And do not
read that message as "your CLI is out of date", which is the first thing it suggests and
usually is not the cause.

It is an early-development surface, named `managed-agent` specifically to keep the `agent`
noun free for the generic Agent resource. Treat it as something to recognise, not something
to offer.

So in practice there is one path: **an app you write, fronted by `diagrid agent`.** That
starts at step 3.

**Never write "create an agent" unqualified**, in prose or in a command. `diagrid agent
create` and `diagrid managed-agent create` both parse and mean different things.

### Confirm the command before relying on it

The meaning of `diagrid agent` **changed between CLI versions.** On 1.51.0 it *is* the
Durable Agent — `diagrid agent create --llm-provider ... --sandbox` creates a hosted
agent, and `diagrid agent chat` talks to it. From 1.63.0 onward that moved to
`managed-agent`, and `diagrid agent` became the connectivity resource carrying
`--endpoint` and `--archive-*`; still true at 1.66.0. One command name, two different
resources, depending on a version you did not choose.

So do not emit an agent command from memory, and do not trust the ones written here on
sight. Run `diagrid version`, then the relevant `--help`, and match what you actually see.
A command that was right one minor version ago can now create the wrong kind of resource
without erroring.

## 2. The hosted path, for recognition rather than use

This section exists so you can identify a hosted agent someone else made and read its
flags, not so you can propose it. On any account that is not a Diagrid one the commands
below refuse before they do anything, so do not put them in front of the user as a step —
skip to section 3. What follows needs no repository and no adapter:

```
diagrid managed-agent create <name> --project default --role assistant \
  --goal "<goal>" -i "<instruction>" \
  --llm-provider openai --llm-model gpt-4o --llm-api-key <key>
```

Use `--llm-component <name>` instead of the three `--llm-*` flags to reuse a
conversation component that already exists. Add `--sandbox` for tool isolation,
`--web-tools` to opt into `web_search` and `web_fetch` (off by default), and the
`--github-*` flags for git access — those require `--sandbox`.

Never put an API key on a command line you also write into a file the user commits.
Read it from the environment and say that is what you did.

Then prove it answers, in one shot rather than an interactive REPL:

```
diagrid managed-agent chat --agent <name> --project default -m "<prompt>"
```

The agent name goes in the **required `--agent` flag**. The positional argument is a
conversation id, so `chat <name>` does not name the agent — it tries to resume a
conversation called that. Omitting `-m` drops into an interactive REPL, which will hang a
non-interactive session.

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
| Python | `diagrid[<framework>]` on PyPI, 0.4.3 | Widest coverage — 11 frameworks — and exercised against live Catalyst |
| .NET | `Diagrid.AI.Microsoft.AgentFramework` on NuGet, 1.0.10 | Published. Microsoft Agent Framework; targets net8.0, net9.0, net10.0 |
| Java | `io.diagrid:diagrid-spring-ai-starter` on Maven Central, 0.2.0 | Published, Spring AI. Its own README says the APIs are not yet stable |
| Go | `github.com/diagridio/go-ai` v0.1.1 | Root module resolves. The `adapters/*` submodules have no release tag, so they pin only as an untagged pseudo-version, and the repo has no CI |
| TypeScript | none | **Not installable.** Nothing is published to npm, the `@diagrid` scope does not exist, and the default branch is empty — the work sits on unmerged branches |

For **TypeScript**, say that plainly and offer the two things that do work: write the
agent in a language with a published adapter, or drive Dapr Workflows directly with
`@dapr/dapr`, which is published and does support workflows — you lose the framework
bridge, not durability. Do **not** offer the hosted `managed-agent` as the TypeScript
escape hatch; it is restricted per section 1, so it trades one dead end for another.

For **Go**, do not pretend the adapter is a normal dependency. `go get` the root module
by version, then pin each adapter to the pseudo-version `go get <path>@latest` resolves,
and tell the user it is untagged and untested by CI so they can decide.

Never emit a package coordinate you have not watched resolve. A confidently wrong
package id is worse than no skill at all: it sends the user to debug Catalyst for a
problem that is a typo.

## 5. Python specifics, since it is the widest path

Install the framework as an extra on the single `diagrid` distribution — there is no
per-framework distribution:

```
pip install "diagrid[langgraph]"
```

The 11 frameworks are `langgraph`, `crewai`, `adk`, `strands`, `pydantic_ai`,
`openai_agents`, `claude_agents`, `langchain`, `smolagents`, `deepagents` and
`holmesgpt`. Three traps: the extras use **underscores** where the framework's own name
uses a hyphen, `holmesgpt` conflicts with the others and needs its own environment, and
the console script is **`diagridpy`**, not `diagrid` — `diagrid` is the Catalyst CLI, a
different program. Python 3.11 or later, below 3.14.

Import the runner from the framework's module: `DaprWorkflowAgentRunner` for most,
`DaprWorkflowGraphRunner` for LangGraph, `DaprWorkflowDeepAgentRunner` for Deep Agents,
`DaprWorkflowHolmesRunner` for HolmesGPT. Then `runner.serve(...)` exposes the app.

Components are discovered **by name**, not by configuration. Ship the app's own
components as `agent-memory`, `agent-pubsub`, `agent-registry`, `agent-configuration` and
`agent-runtime`, or discovery silently finds nothing and the failure looks like a
connectivity problem. These are the app's components, distinct from the project's managed
`pubsub` and `kvstore`.

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
infrastructure comes with the managed KV store — `project create` has no
`--enable-agent-infrastructure` flag, which was removed. Do not document it.

`default` is bootstrapped once, when the organization is first reconciled, and it is not
recreated if someone deletes it. Check with `diagrid project list`; if it is gone, ask
which project to use rather than creating one. The managed components have fixed names,
`pubsub` and `kvstore`, and the managed workflow store has none.

## 7. Fit the topology to one pub/sub

A project holds **one managed pub/sub and one managed KV store** on every plan — free,
enterprise and internal alike. It is a platform default rather than a free-tier limit, and
no plan upgrade raises it, so never offer an upgrade as the fix. (A negotiated
per-organization override exists; a live quota read beats this document.)

A coordinator with specialists therefore **shares one broker and separates the agents by
topic**, one topic per specialist plus one for results. Design for that from the start;
it is not a workaround.

Budget the resource slots before scaffolding. Per region:

| | Allowance |
| --- | --- |
| Projects | 3 |
| Resources — every app, agent and MCP server counts as one | 10 |
| Durable Agents | 5 |
| Managed pub/sub, KV store and workflow store, per project | 1 each |

A hosted Durable Agent spends one resource slot **and** one Durable Agent slot; an app or
a connectivity `agent` spends one resource slot only. A coordinator plus four specialists
is five slots — it fits, but a second copy does not.

Throughput is capped per app and per project as well. Those figures move and are quoted
inconsistently, so read them off the current plans page instead of hardcoding one here.

## 8. Run it, then kill it

- `diagrid dev run --project default --id <app> --app-port <port> -- <run command>`
- Send a prompt, wait for it to be mid-run, kill the process, start it again.
- The run must resume rather than restart. If it restarts, the agent is not durable and
  the scaffold is not finished — usually the workflow store or a component name.

On `dev run` the short `-p` means `--app-port`, not `--project`, and `--id` names the App
ID. `--app-port` **is** wanted here, unlike for a pure workflow worker: an agent exposes an
endpoint Catalyst calls into, so there is a port to connect. `diagrid dev run` provisions
the managed pub/sub, KV store and workflow store for App IDs it creates, so you get the
infrastructure by running.

**An absent field is not an empty one.** An agent's turn runs as a workflow, and workflow
payloads are withheld by default — withheld by deleting the key, not by returning an
empty value. Over MCP tools, `input`, `output` and `customStatus` are all removed, and
only an organization administrator can raise the org's data-sharing level to `full`. Over
the management API, the list endpoints need `includeData=true`; the single-execution read
returns payloads without it. **The CLI needs no flag because it is not filtered at all** —
withholding is applied by the MCP server to MCP responses, so `diagrid workflow get
<workflow-id> --project <project> --id <app>` remains the fallback that can still show a
payload an MCP tool withheld. Two conditions: confirm the CLI is logged into the same
organization — the CLI session and the MCP connection are separate identities and can
sit in different ones — and say which surface the value came from. Never forge a
data-sharing header, and never ask an administrator to raise the organization's level so
you can finish an answer.

So never report a missing payload as "the agent produced no output". Say it was withheld
and by which surface. A tool that refuses is likewise not an agent that failed; report
the refusal and fall back to the CLI.

## 9. Hand back a link, not a claim

Once the agent exists, give the user a console link rather than asking them to trust the
transcript. Only these routes exist:

| To show | Route |
| --- | --- |
| Any agent, either kind | `/agents/<appId>/<id>` |
| Edit a Durable Agent | `/agents/durable/<name>/edit` |
| Chat with a Durable Agent | `/agents/durable/<name>/chat` |
| The backing App ID | `/apps/details/<appId>` |
| A run of the agent's workflow | `/workflows/<appId>/<runId>` |
| An MCP server | `/mcp-servers/<id>` |

Note where the two kinds diverge: both share the view route, but **only managed Durable
Agents have `edit` and `chat` routes.** Offering a chat link for a connectivity `agent`
produces a 404 — a second, independent reason to keep the two straight.

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

Do not hardcode or hand-derive the host; prod, staging, dev and local differ, so any
hardcoded host is wrong for someone. Prefer `diagrid web`, which opens the console for the
environment the session is logged in to, and see `catalyst-setup` section 3 for the mapping
when you need the URL itself. If you cannot establish it, print the identifiers as plain
text — **a link that 404s or lands on the wrong project is worse than no link.**

## Rules

- **Say `managed-agent` or `agent`, never just "agent".** They are different resources,
  with different flags and different console routes.
- **Do not offer `managed-agent` as a choice.** It is hidden and restricted to Diagrid
  accounts; for everyone else the only path is their own app fronted by `agent`.
- **Check every CLI command against `diagrid version` and `--help` before running it.**
  `diagrid agent` changed which resource it creates between 1.51 and 1.63, so a remembered
  command can quietly do the wrong thing.
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

<!-- Named in order to warn against it, not to instruct. The lint gate rejects
     this string by default because a skill that tells someone to pass the flag
     is a real defect.
     lint-allow-banned: --enable-agent-infrastructure — taught as a flag removed in v1.63.0
-->
