---
name: catalyst-agent-harness
description: Make a hand-written agent loop durable on Catalyst with Dapr Workflows — the loop becomes the workflow, each LLM call and each tool call its own activity. Use for a custom agent harness or a raw model-API tool loop no framework adapter covers.
---

# Make a hand-written agent loop durable

Goal: end this skill with the user's own agent loop — their prompt, their tools, their
model call — running as a Dapr Workflow on Catalyst, where every model call and every
tool call is its own activity. And with proof: a worker killed in the middle of a tool
call resumes at that tool, and the model is not asked again for a turn it already
answered. A loop that only survives when nothing crashes has gained nothing.

## 1. This skill, or an adapter?

This skill is for a loop the user wrote: code that calls a model API directly —
Anthropic, OpenAI, Bedrock, a local model — reads the tool calls out of the reply, runs
them, appends the results and calls again.

| What the user has | Go to |
| --- | --- |
| A framework with a Diagrid adapter — the 11 Python frameworks, Microsoft Agent Framework, Spring AI, langchaingo, Eino, Mastra | `catalyst-agent-scaffold`. The adapter already does this mapping for that framework; hand-rolling it again is duplicate work with new bugs |
| Their own loop, or a framework with no adapter whose loop they are willing to take over | This skill |
| Fixed steps with a model called inside some of them, and no step chosen by the model | `catalyst-workflow-scaffold` — that is a workflow, not an agent loop |

A loop you cannot split cannot be made durable from outside. A framework's `run()`, an
SDK's tool runner, or an agent SDK's query loop makes every model call and tool call
inside one call of yours, so the best you can do is wrap all of it in one activity — a
retry, not durability. Either use the framework's adapter, or take the loop over: call
the model client and the tools yourself, from the workflow. That is what the runners in
Diagrid's Python adapters do: each re-implements its framework's loop in a workflow body.

## 2. The mapping

| In the harness | Becomes | Why |
| --- | --- | --- |
| The `while` loop | The workflow body | Replayed from history after a crash, so its decisions must be reproducible |
| One model call — one assistant turn | One activity, `call_llm` | Recorded once. A replay returns the recorded reply instead of calling, and billing, the model again |
| One tool call | One activity per call, `run_tool` | A crash mid-batch resumes at the unfinished call, and each call retries on its own |
| Several tool calls in one turn | Scheduled together, awaited one by one | Parallel, and one failure stays local — section 6 |
| The messages list | A local variable, rebuilt on replay from the input and recorded results | Never a global, never read from a store in the body |
| System prompt, model id, tool schemas, turn limit | A `load_agent` activity, or the workflow input | Pinned per run: a redeploy changes new runs only |
| The model client, tool functions, database handles | A process-local registry that activities look up by name | Not serializable, so they never cross the workflow boundary |
| The max-iterations guard | The loop bound | An unbounded loop grows history without limit |
| Human approval before a tool | An external event raced against a timer | A durable wait that costs nothing while it waits — section 8 |
| A sub-agent | A child workflow | Its own history, retries and instance id |
| A conversation that lasts for days | A session workflow that continues-as-new every turn | Bounded history — section 9 |
| Token streaming, progress | Out of band from the activity; custom status | History records results, not streams |

## 3. One activity per model call, one per tool call

The granularity is the design. Every coarser boundary gives back a failure durability was
supposed to remove:

| Activity boundary | What a crash costs |
| --- | --- |
| The whole run | Everything re-runs: every model call billed again, every tool executed again |
| One turn, the model call plus its tools | The model is asked again and may choose different tools, so tools that already ran are duplicated or orphaned |
| All of one turn's tools | One failing tool re-runs its siblings |
| One model call, or one tool call | Only the interrupted call re-runs |

Measured on all five SDKs in the language files, against a local Dapr 1.18.1 sidecar:
killed with `kill -9` in the middle of a tool call, the restarted worker re-ran that one call — with the same idempotency key both
times — did not re-run the tool that had finished, and called the model exactly once per
turn in total.

Model calls and tool calls are the only activities the loop needs, plus one that loads
the agent's configuration. Parsing a reply, formatting a message and choosing the next
step are pure functions of recorded data and stay in the body. Making them activities
adds history and round trips for nothing.

## 4. The workflow body decides; it never acts

The general replay rules are in `catalyst-workflow-determinism`. These are the ones an
agent loop breaks, and none of them fails on the first run:

- **Pin the configuration per run.** Read the system prompt, model id, tool schemas and
  turn limit in a `load_agent` activity, or take them in the input. Reading them from a
  module global or a closure inside the body lets a redeploy change a run half way
  through — and at least one framework integration reads the agent's system prompt
  exactly that way.
- **Keep the transcript append-only and verbatim.** Store the assistant's content blocks
  exactly as the API returned them and send them back unchanged; never re-render history
  into your own message type and back. Current Claude models bind each thinking block to
  the conversation before it, so an edited, reordered or rebuilt earlier turn
  invalidates every later thinking block — and enforced accounts get a 400. A durable
  loop is append-only by construction: replay rebuilds the list from recorded replies.
- **Branch on the recorded stop reason.** `tool_use` runs the tools. `end_turn` finishes.
  `max_tokens` finishes without running tools, because the last tool call may be
  truncated. `refusal` is a result to report, not an error to retry. `pause_turn` — a
  server tool paused the turn — sends the turn back as it is.
- **Take ids from history, never from a generator.** The model's tool-call id is part of
  the recorded reply, so it is identical on every replay. Derive everything else from it
  and the instance id: idempotency keys, approval event names, child workflow instance
  ids. A `uuid4()` in the body is a new id on every replay, and at least one agent
  framework generates child workflow ids exactly that way.
- **Bound the loop.** A turn limit from the configuration, and optionally a token budget
  summed from each reply's recorded `usage` — recorded, so it replays identically.
- **Walk the model's list, not a map.** Tool calls arrive in order. Keep results in a map
  keyed by call id if that is convenient, but build the next message by iterating the
  calls, and in Go never range over the map at all.

## 5. Classify every failure before writing the activity

An activity fails in one of two ways, and they are not interchangeable. Raising hands the
failure to the retry policy at the call site. Returning hands it to the workflow — or,
for a tool, to the model.

| Failure | Do | Because |
| --- | --- | --- |
| Model call: connection error, timeout, 408, 409, 429, or 5xx including 529 | Raise | The retry policy retries with a durable backoff that survives a restart and shows in history |
| Model call: any other 4xx — invalid request, context too long, 401, 403, 404, 413 | Return it as data, and end the run as `rejected` | The same request fails the same way; retrying burns the budget and delays the answer |
| Model reply with `refusal` or `max_tokens` | Treat it as a reply | It arrived as HTTP 200. Branch on it |
| Tool: bad arguments, not found, a business rejection | Return a `tool_result` with `is_error` | The model reads it and corrects itself on the next turn |
| Tool: a name the model invented | Return an error `tool_result` | Same |
| Tool: a transient failure in an idempotent tool — a timeout, a 503 | Raise | Retried; when the retries run out, the workflow turns it into an error result |

The mirror-image mistake is common enough to have shipped in framework integrations:
catching every exception inside the model activity and returning it as an error value.
The retry policy at the call site then never fires, and the first rate limit ends the
run.

**Turn off the provider SDK's own retries** in the activity — the Anthropic and OpenAI
Python SDKs both retry twice by default. The workflow's policy owns retries; a retry loop
inside the activity is invisible to history, does not survive a crash, and multiplies
with the engine's attempts.

**Give the model call and the tools separate policies.** Model calls deserve more attempts
and a longer ceiling, because rate limits are the common failure. A tool retry only makes
sense for an idempotent tool, so the default for every other tool failure is to let the
model see it. Retry APIs differ enough by SDK to matter — JavaScript has no retry policy
at all, and Java's first retry waits longer than the others' — so read the language file.

## 6. Run a turn's tools in parallel without losing the batch

Schedule every tool call of the turn first, then await them one at a time, each in its
own try/catch. They still run in parallel, because scheduling is what starts them, and a
tool that exhausts its retries becomes an error result instead of aborting the turn.
Awaiting the batch with a when-all hands back one failure instead of the batch: when one
tool exhausts its retries the await throws, and the results of the calls that succeeded
are not returned.

Then send back exactly one `tool_result` per `tool_use`, in the model's order, all in
**one** user message. A missing result is rejected by the API, and splitting results
across messages teaches the model to stop calling tools in parallel.

## 7. Side effects: the key the model already gave you

`<instance-id>:<tool-call-id>` is a correct idempotency key for a tool with side effects.
It is stable across retries of the activity and across replays of the workflow, because
the tool-call id is part of the recorded model reply — the kill test showed the same key
on both attempts of the interrupted call. Pass it in the activity input and on to the
provider, rather than rebuilding it inside the tool where no reviewer will see it.

It is not a semantic dedupe. A model that asks for the same payment in two turns produces
two ids. Guard that with a natural key such as the order id and a conditional write — the
patterns are in `catalyst-activity-idempotency`.

## 8. Human approval is a durable wait

For a tool that needs a human, the workflow waits, not the tool:

1. Announce what is pending from an activity — a message on a topic, a row the approval
   UI reads — carrying the run id and the tool-call id. Never publish from the workflow
   body. Custom status can mirror it, but over MCP it is withheld at the default
   `metadata` data-sharing level, so it cannot be the only notice.
2. Wait for an event named after the call, `approval:<tool-call-id>`, so concurrent
   approvals never collide. Race it against a timer, or use the SDK's own timeout where
   it has one.
3. On approval, run the tool. On denial or timeout, return an error `tool_result` saying
   so, and let the model respond to it.

The decision comes back through `catalyst_raise_workflow_event` — the run, the event name
`approval:<tool-call-id>` and `{"approved": true}` — or through the SDK's workflow client
inside the approval service. `catalyst_raise_workflow_event` is a write tool, absent for a
role that cannot write.

Two measured facts, both against a local Dapr 1.18.1 sidecar rather than Catalyst. The
wait survives a worker kill: after a restart the run was still waiting with the same
custom status, and the model was not asked again. But **raising the event while no worker
is connected fails** with `FAILED_PRECONDITION` (`did not find address for actor`) — the
event is refused, not buffered — so the approver's side must retry until a worker is
back. Terminating a run failed the same way with no worker connected.

## 9. Long conversations: bound the history

Every model call's input carries the whole transcript, and every input is recorded, so
history grows with the square of the number of turns. Large payloads slow every replay
and can exceed state-store limits.

- **One workflow per task** is the simplest shape: the run ends when the model answers.
- **A conversation that lasts for days** is a session workflow. It waits for a
  `user_message` event, runs the turn as a child `agent_loop` whose input carries the
  transcript so far, then continues-as-new carrying the new transcript, so its own history
  never grows past one turn. Keep unprocessed events across the restart or a message that
  arrived during the turn is lost — the flag is named in each language file. Measured: two
  messages sent back to back ran as two turns, the second seeing the first's transcript
  verbatim.
- **Keep tool results small.** Inside the tool activity, write an oversized result to a
  store under a deterministic key, `<instance-id>:<tool-call-id>`, and return a pointer
  and a preview.
- **Compact without editing.** With Claude thinking blocks in the history, prefer the
  API's server-side compaction or context editing, which do not count as edits. Client
  side, replace the whole history with one summary message and replay nothing else.
  Summarizing old turns while keeping recent ones verbatim invalidates the recent turns'
  thinking blocks.

## 10. Sub-agents, streaming and secrets

- **A sub-agent is a child workflow**, with an instance id derived from the parent's and
  the tool-call id. Only the workflow body can start a child workflow, so a tool that
  delegates is dispatched in the body rather than through `run_tool`.
- **The workflow cannot stream.** Stream tokens from inside the model activity to wherever
  the UI listens, and return only the final reply. A retried attempt streams again, so tag
  every event with its turn and let the UI drop a restarted one. Coarse progress fits in
  custom status.
- **Never put a secret in a workflow or activity input.** Inputs and outputs are persisted
  in the run's history, readable in the console and over MCP at `full` data sharing. The
  model API key belongs in the activity's environment, handled like the connection token
  in `catalyst-develop` section 3. Prompts and tool outputs are persisted too, so consider
  what they contain before the first real run.

## 11. Names and shapes are a wire contract

The workflow name, every activity name and the JSON between them are what history records.
Rename one while runs are in flight and those runs cannot replay; change a field and old
results stop parsing.

- **Register and call by the same explicit string.** Default names are derived, and they
  silently differ from what you meant: a JavaScript function reference resolves to its
  `fn.name`, and Java defaults to the canonical class name.
- **Prefer one `run_tool` activity with the tool name in its input** over one activity per
  tool. Adding or removing a tool then never changes an activity name. Per-tool
  activities buy per-tool names in history, at the cost of a registration per tool.
- **Two workers for one app must agree on every shape.** Work is dispatched to whichever
  worker is connected. Measured by accident: a stale worker in another language, still
  connected, answered `load_agent` with a differently-cased field, and the new worker's
  runs all stopped at turn zero.

Changing the loop itself — a new activity before `call_llm`, a reordered step — changes
the action sequence for every run in flight. Use the SDK's patching API or a new workflow
name and let old runs drain; `catalyst-workflow-determinism` covers both. A redeploy also
swaps tool *implementations* under runs whose recorded configuration lists the old ones,
so keep tool signatures backward compatible or version the tool name.

## 12. Run it on Catalyst, then kill it

Everything here goes through the `catalyst_*` tools; if they are missing or refuse with
`NOT_AUTHENTICATED`, `catalyst-setup` covers it.

**Do not create a project.** Every organization has one named `default` with the managed
workflow store already attached, and that store is where run history lives. Confirm it
with `catalyst_list_projects` and pass the project on every call; if it is gone, ask which
project to use rather than creating one.

The loop needs the Dapr Workflow SDK for its language and no Diagrid package:
`dapr-ext-workflow`, `@dapr/dapr`, `github.com/dapr/durabletask-go`, `Dapr.Workflow` or
`io.dapr:dapr-sdk-workflows`. Section 2 of `catalyst-workflow-scaffold` has the versions
and the coordinate traps.

1. **Make sure the app exists** — `catalyst_get_app`, else `catalyst_apply` an `App`, as
   `catalyst-develop` section 2 describes. A worker needs no endpoint: it dials Catalyst
   and polls for work, so it has nothing to listen on.
2. **Start the worker** with the connection values from `catalyst_get_app_connection` in
   its environment, exactly as `catalyst-develop` section 3 says, including how to keep
   the token out of chat, files and history. If the tool is missing or refused, say it is
   not available to this role or server, and stop.
3. **Start a run** with `catalyst_start_workflow`: the project, the app's identity, the
   workflow name `agent_loop` and `{"task": "<prompt>"}`. It assigns the run id and
   returns it — keep it. It is a write tool, absent for a role that cannot write.
4. **Read it** with `catalyst_get_workflow_run`. The execution graph lists `load_agent`,
   then `call_llm`, one `run_tool` per call, then `call_llm` again — every step's name
   and status, even where its payload is withheld.

**The kill test is the acceptance test.** Give the agent a slow tool, start a run, kill
the worker while that tool runs, start it again with the same environment, and read the
run back. Pass means: the run completes; each turn's `call_llm` completed once; the tools
that finished before the kill did not run again; the interrupted one ran again with the
same idempotency key. The graph shows each step completing once; the worker's own output
shows which tool bodies actually ran, and with which key, because at the default
data-sharing level the run's payloads are withheld. If the model is called again for a
turn it already answered, the loop is not durable and the work is not finished — look for
a boundary coarser than section 3 allows.

## 13. Read it back honestly

**An absent field is not an empty one.** At the default `metadata` data-sharing level,
`catalyst_get_workflow_run` removes `input`, `output` and `customStatus` from the run and
from every step — removed, not returned empty. Every model reply, every tool result and a
pending approval's custom status are invisible there, while the graph of step names and
statuses is not. Say that a payload was not shared at this organization's data-sharing
level (`metadata`); never report a withheld reply as "the model returned nothing". Only an
organization administrator can raise the level to `full`, and you cannot do it from here.
Never forge a data-sharing header, and never ask an administrator to raise the level so
you can finish an answer.

Hand back a link rather than a claim: a run lives at
`https://catalyst.diagrid.io/workflows/<appId>/<runId>`, where `<appId>` is the app's
identity name from its `status.appIds`. Put a name-like project in `?project=` and a
numeric uid in `?projectId=` — a uid in `?project=` silently lands on the wrong project.
If you cannot build a link you trust, print the app and run id as plain text.

## Language files

Load the one for the language the repository is written in — detect it, do not ask:
`pyproject.toml` or `*.py`, `package.json`, `go.mod`, `*.csproj`, `pom.xml` or
`build.gradle`.

| Language | File | Verified with |
| --- | --- | --- |
| Python | [reference/python.md](reference/python.md) | `dapr-ext-workflow` 1.18.3, and the Anthropic SDK 1.9.0 for the model call |
| TypeScript | [reference/typescript.md](reference/typescript.md) | `@dapr/dapr` 3.18.0 |
| Go | [reference/go.md](reference/go.md) | `github.com/dapr/durabletask-go` v0.14.0, `github.com/dapr/go-sdk` v1.15.0 |
| .NET | [reference/dotnet.md](reference/dotnet.md) | `Dapr.Workflow` 1.18.5 |
| Java | [reference/java.md](reference/java.md) | `io.dapr:dapr-sdk-workflows` 1.18.1 |

Every file holds the same harness — `load_agent`, `call_llm`, `run_tool`, the loop, the
approval wait and the session workflow — and each was run against a Dapr 1.18.1 sidecar
with a scripted model through the same six cases: a kill in the middle of a tool, a 429
retried by the workflow, a 400 returned as a rejection, a tool that exhausts its retries,
an approval, and a two-message session. Python is the one with a real provider call; the
other four take the harness's existing model client behind a one-method interface.

## Rules

- **One activity per model call and one per tool call.** Never the whole run, a turn, or a
  turn's batch of tools in one activity.
- **The body decides, activities act.** No model call, tool call, clock, id generator or
  configuration read in the workflow body.
- **Replay the model's reply verbatim, append-only.** Never rebuild, reorder or edit an
  earlier turn.
- **Raise what a retry can fix; return what it cannot.** Rate limits and outages are
  raised; other 4xx become a `rejected` run; tool errors become `tool_result`s the model
  reads.
- **Every `tool_use` gets exactly one `tool_result`**, in order, in one message — including
  the denied, the unknown and the exhausted ones.
- **Key side effects on `<instance-id>:<tool-call-id>`**, passed in the input.
- **No secrets in inputs.** Every input and output is persisted and printable.
- **Do not create a project.** Use `default`.
- **Do not stop at a run that completes.** Kill one mid-tool and read the run back.
- **Use only the `catalyst_*` tools.** Where a capability has no tool, say it is not
  available over MCP yet, and stop.
- **Never report a withheld field as an empty result.**
- For determinism in general use `catalyst-workflow-determinism`; for the write side of a
  tool, `catalyst-activity-idempotency`; for a framework with an adapter,
  `catalyst-agent-scaffold`.
