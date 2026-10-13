---
name: catalyst-workflow-determinism
description: Replay-safety rails for the body of a Dapr Workflow orchestrator. Use when writing or reviewing code inside a workflow function, or when a run diverges on replay — clocks, randomness, ids, iteration order, direct I/O, threads and mutable global state.
---

# Workflow Determinism

Goal: for every line inside a workflow function, be able to say why it produces the same
value on the tenth execution as on the first. Where you cannot, either move it to an
activity or take the value from the workflow context.

## The mechanism

A workflow function is not run once. It is re-executed **from the first line** every time
the engine needs to advance it — after a crash, a worker restart, a scale event, or a
timer firing days later. On each re-execution the function emits a sequence of actions
(schedule this activity, create this timer, start this child workflow). The engine
compares that sequence against the events already recorded in history:

- **Same sequence** — the engine returns the recorded results without re-running anything
  and the workflow continues from where it left off.
- **Different sequence** — history and code disagree. The instance cannot advance.

Two properties make this the hardest class of bug in the system:

1. **The first run always succeeds.** Non-determinism is invisible until a replay
   happens, which may be days later and only on some instances.
2. **There is no sandbox and no static check.** The SDKs do not intercept the system
   clock, block I/O, or reject a workflow that reads a random number. Nothing warns you.
   The correctness burden is entirely on the code, which is why this rail exists.

## The rule

**Everything in the workflow body must be a pure function of the workflow input and the
values already returned by awaited context calls.** If a value could differ between two
executions of the same function, it must arrive through the context or through an
activity result. Nothing else may enter the body.

## Hazard table

| In the workflow body | Why replay breaks it | Correct alternative |
| --- | --- | --- |
| Read the system clock | Wall clock has advanced, so any comparison or arithmetic on it yields a different result | The context's current-UTC-time accessor — it returns the timestamp recorded in history |
| Sleep or block | Not replay-aware, and it holds the workflow thread | A durable timer created through the context |
| Generate a random number | New value per execution | Generate it in an activity and return it |
| Generate a UUID | New value per execution | The context's deterministic GUID where the SDK has one, otherwise an activity |
| Read an environment variable or config | Config can change between the original run and the replay, e.g. after a redeploy | Pass it in the workflow input, or read it inside an activity |
| HTTP, gRPC, socket call | Non-deterministic result, and the call is re-issued on every execution | Wrap in an activity |
| Database or state store access | Same as above, plus the data has moved on since the original run | Wrap in an activity |
| File or blob I/O | Filesystem is external state | Wrap in an activity |
| Read or write mutable global or static state | Outlives the replay and is shared across instances on the same worker | Workflow input/output, or activity state |
| Spawn a thread, goroutine, or unawaited task | Escapes the workflow scheduler; ordering is not reproducible and the work is invisible to history | Express parallelism with the context's when-all |
| Iterate an unordered collection to schedule work | Enumeration order is not guaranteed, so activities are scheduled in a different order | Sort into a list first, or pass an ordered list in |
| Log or print unguarded | Emitted again on every replay, multiplying volume and misleading whoever reads it | A replay-safe logger, or log from the activity |
| Unbounded loop with no continue-as-new | History grows without bound; replay gets slower until the instance exceeds state store limits | Continue-as-new each iteration, keeping history small |
| Measure elapsed time with a stopwatch or monotonic clock | Measures replay duration, not real duration | Take two context timestamps at the boundaries |

## The two escape hatches, and which to use

**The workflow context** for time, durable waits, and deterministic ids. The context
records the value in history the first time and returns the same value on every replay.
Use it whenever it covers what you need — it costs no extra history entry and no round
trip.

**An activity** for everything else. An activity runs outside the replay: its result is
written to history once and returned from history thereafter. This is the general
mechanism, and every hazard above that is not covered by a context accessor resolves to
"move it into an activity".

Do not reach for an activity when the context already has the value — an activity call
for the current time adds a history entry and a network hop to get something the context
returns for free.

## The failure is the branch, not the read

Reading the clock is not what corrupts the run. Emitting a different action sequence is.
The contrast worth internalizing:

```
# WRONG
if now().hour < 12:                    # true at 11:59, false at 12:01
    call_activity(morning_task)        # first run schedules morning_task
else:
    call_activity(afternoon_task)      # replay schedules afternoon_task

# History says TaskScheduled(morning_task). Code now says afternoon_task.
# The instance cannot advance.
```

```
# CORRECT
now = ctx.current_time()               # replayed from history, stable forever
if now.hour < 12:
    call_activity(morning_task)        # same branch on every execution
else:
    call_activity(afternoon_task)
```

The same shape applies to every hazard: a random number that only appears in a log line
is harmless; the same random number in an `if` that chooses which activity to schedule
corrupts the instance. When reviewing, follow each non-deterministic value to see whether
it can reach a branch, a loop bound, or an activity input. Report severity accordingly.

## Iteration order

Scheduling activities while iterating a hash-based collection makes the action sequence
depend on enumeration order. Sort explicitly:

```
# WRONG
for item_id in pending_set:            # enumeration order not guaranteed
    tasks.append(call_activity(process, item_id))

# CORRECT
for item_id in sorted(pending_set):    # total order, reproducible
    tasks.append(call_activity(process, item_id))
```

Sorting is only needed where order affects the emitted sequence. Iterating a list that
arrived in the workflow input is already deterministic.

## Parallelism

Fan out by scheduling several context calls without awaiting, then awaiting them
together with the context's when-all. The engine handles the concurrency; the *scheduling*
order is what must be deterministic, and the completion order does not matter because
when-all returns results positionally.

Never create a thread, goroutine, or unawaited runtime task in the workflow body. It
escapes the scheduler, its ordering is not reproducible, and it is invisible to history —
so it re-runs on every replay while the engine has no record it ever ran.

If a design fans out over pub/sub rather than over activities, note the shape of a
Catalyst project: **`number_of_pubsubs_per_project` is 1 on every plan**, and no plan upgrade raises it. It is a platform default
rather than a free-tier restriction. These are plan values overlaid per organization,
not constants in the code, so read the live quota rather than asserting the 1 — and do
not promise a user it can be raised for them, which is a commercial question rather than
one you can answer. Fan out across *topics* on the one
pub/sub component. A design
that needs several pub/sub components does not fit and needs reshaping, not an upgrade.
Publishing from the workflow body is also direct I/O — it belongs in an activity either
way.

## Do not branch on the is-replaying flag

Where an SDK exposes an is-replaying flag, it is for suppressing duplicate log lines and
nothing else. The flag is `true` while the engine is working through recorded events and
flips to `false` when it reaches new ones — so gating a context call on it emits a
different action sequence on the first execution than on a replay. Using the flag to
schedule work is a way of writing the exact bug it exists to help you debug.

## Per-language notes

Names below are verified against the SDKs. Where a name is not verified, the entry says
so — read it from the SDK rather than guessing.

| | Deterministic time | Deterministic id | Trap that differs here |
| --- | --- | --- | --- |
| .NET | `context.CurrentUtcDateTime` (property) | `context.NewGuid()` | `foreach` over `Dictionary`, `HashSet` or `ConcurrentDictionary` driving activity order. LINQ inherits the source's enumeration order, so a query over a hash-based collection carries the same hazard; `OrderBy` is the fix, not the problem. Also `async void` on a workflow class — it cannot be awaited and bypasses the scheduler. |
| Python | `ctx.current_utc_datetime` (property) | none — use an activity, or derive from `ctx.instance_id` | `dict` and `set` iteration when the collection was built non-deterministically. `asyncio.gather`, `create_task` and `asyncio.sleep` escape the workflow scheduler — inside an activity they are fine, inside the workflow body they are not. |
| Go | `ctx.CurrentTimeUTC()` (method) | none on the context — use an activity | `for k := range myMap` — Go deliberately randomizes map iteration order per run, so this is the one language where the hazard fires reliably rather than occasionally. `go func(){}()` in the workflow body. |
| Java | `ctx.getCurrentInstant()` (method, returns `Instant`) | `ctx.newUuid()` | `HashMap` and `HashSet` have no guaranteed order; `Stream` over an unordered source inherits it. |
| JavaScript / TypeScript | `context.getCurrentUtcDateTime()` (method, returns `Date`) | none on the context — use an activity | Workflows must be **async generator functions** (`async function*` with `yield`). A plain `function*` is not run at all: its generator object becomes the output and the run completes without scheduling anything. `context.createTimer()` takes a `Date`, or a number of seconds. |

Two names that appear in generated Go code and do not exist on today's workflow context:
`ctx.WorkflowExecutionID()` and `ctx.InstanceID()`. The accessor is `ctx.ID()`;
`InstanceID()` belonged to an older Go workflow package that has since been removed. Do
not emit either.

## What is not a determinism problem

Do not report these. Flagging them trains the reader to ignore the real findings.

- **Non-determinism inside an activity.** That is the entire purpose of an activity.
- **Branching on an activity result, a timer outcome, or an external event payload.** All
  three are recorded in history and replay identically.
- **Branching on a failure from an awaited context call.** Recorded in history, therefore
  deterministic. Catching it and choosing a compensating activity is correct design.
- **Pure computation** over the workflow input and awaited results, however complex.
- **Iterating a list, tuple or array**, or a sorted view of anything.
- **Reading an immutable module constant.**
- **A non-deterministic value that only reaches a log line** and cannot influence the
  action sequence. Note it as informational at most.

## Reading run history when you suspect non-determinism

At the default `metadata` data-sharing level, workflow and activity **`input`, `output`
and `customStatus` are removed from the response — absent, not empty.** The payload
exists; AI tools are not allowed to read it.

This matters more here than anywhere else, because diagnosing a divergence is exactly
when someone wants to see payloads. Reporting "the activity returned nothing" or "the
workflow was started with no input" when the value was elided is a false statement the
user has no way to detect. Say instead, in plain words: *I can't see the payload,
because your organization's setting doesn't let AI tools read it.* Then reason from what
is available:

- event types and order, `event_id`, `timestamp`
- activity, timer and external-event `name`
- `task_scheduled_id`, `task_execution_id`, `instance_id`, parent and rerun lineage
- `origin__activity_retry_task_execution_id`, which ties a retry timer to the activity
  execution it is retrying
- `workflow_status`, `fire_at`, `version`
- `failure_details_error_message`, `failure_details_stack_trace`,
  `failure_details_is_non_retriable`

When the diagnosis turns on a payload you cannot see, tell the user three things: what
you can't see, why (the organization's setting for what AI tools may read), and what they
can do. Example: "I can't see what this activity took in, because your organization
doesn't let AI tools read that data. The console shows it in full, and an admin of your
organization can ask Diagrid to change the setting." **Hand the user a link to the
run** so they can read it themselves: `https://catalyst.diagrid.io/workflows/<appId>/<runId>` (the console for the production server).
Mention the admin route once, as an option: never forge a data-sharing header, and never
ask for the setting to change so you can finish an answer. The project
is a query parameter with two spellings and **no cross-fallback between them** —
`?project=` is matched against the name-like project id (`default`), `?projectId=` against
the numeric uid (the `prj-` prefix is optional). A numeric uid passed as `?project=`
matches no project name, so the console does not switch project at all: it stays on
whatever project is already selected, where the run id does not resolve. Name goes in
`?project=`, number in `?projectId=`, and if you cannot tell which you are holding, omit
the parameter. A link that 404s or lands on the wrong project is worse than no link: if
you cannot build one confidently, give the run id and app id as plain text.

That is enough to locate a divergence: compare the recorded sequence of scheduled names
against the sequence the current code would emit. The workflow archive export is refused
outright at this level, so do not offer it as a fallback.

## Fixing it without breaking the instances that survived

Editing a workflow function changes the action sequence for **every in-flight instance**,
not just new ones. The naive fix re-breaks the runs you were trying to rescue.

- **The change was accidental** — revert the body to what was running when the history
  was recorded, restart the worker, and the instances resume.
- **The change is intended** — use the versioning/patching API so old and new code paths
  coexist, and in-flight instances continue down the path their history recorded.
- **The instance is already unrecoverable** — terminate and, if the side effects allow,
  rerun it. Say plainly that this discards the run rather than repairing it.

The durable protection against all of this is a replay test: record a real history, then
re-run the current code against it and assert the emitted actions still match. It is the
only mechanism that catches a determinism regression before deployment does.

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **Judge the action sequence, not the vocabulary.** A hazardous call that cannot reach a
  branch, a loop bound or an activity input is not the same finding as one that can.
- **Never invent an SDK name.** If a context accessor is not verified above, read it from
  the SDK. A plausible wrong name costs more than an admission.
- **Do not report a hidden payload as an empty one.** Say the organization's setting hides it.
- **Do not use the is-replaying flag for anything but logging.**
- **Do not edit a deployed workflow body to fix determinism** without deciding what
  happens to in-flight instances first.
- **This is static work.** Reading the source, and at most reading run history, is enough.
  It never requires starting an instance, deploying, or modifying state to make a point.
  Do not create a project — the organization's `default` project already has a managed
  workflow store.
- For hazards in the *activity* body — duplicate side effects under retry — use the
  `catalyst-activity-idempotency` skill.
