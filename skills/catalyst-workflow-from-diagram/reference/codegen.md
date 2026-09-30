# IR to workflow code

Phase 4. The IR has passed validation, so every id resolves, every label is unique and
nothing is orphaned. What is left is a graph, and the job is to turn it into an
orchestrator that a reader can hold against the diagram.

> The per-language sections are adapted from `prompts/languages/*.md` in
> [diagrid-labs/dapr-skills](https://github.com/diagrid-labs/dapr-skills) (MIT). Their
> serialization findings are the load-bearing part and are kept. The record-to-construct
> mapping and the connectivity pass are new — upstream had no language-neutral layer,
> which is how the same rule came to be stated five times and differently.

## Order of work

1. **Connectivity pass.** Turn the edge list into a structure. This is where the joins
   and splits the diagram implied but never drew get inferred.
2. **Models.** One type per `data_object` and one for the workflow input and output.
3. **Activities.** One per `activity` record, each with a typed signature and a body.
4. **Orchestrator.** Walk the structure from the start node.
5. **Registration and entry point.**
6. **A README** naming the diagram it came from and how to run it.

Models first is not stylistic. Every activity signature and every branch condition
refers to a field, so writing the orchestrator first means inventing field names twice
and reconciling them.

## The connectivity pass

The extractor deliberately emits only gateways that are *drawn*. Implied structure is
inferred here instead, because a deterministic pass over an edge list gives the same
answer every time and a model looking at a picture does not.

| Pattern in the edge list | Emit |
| --- | --- |
| Node with 2+ outgoing edges, no `gateway` record, edges carry `gw_flow_condition` | An exclusive branch |
| Node with 2+ outgoing edges, no `gateway` record, no conditions | A parallel fan-out |
| Node with 2+ incoming edges, reachable from one parallel split | A wait-for-all join |
| Node with 2+ incoming edges, reachable from one exclusive split | Nothing. Control simply arrives |
| An edge back to an already-visited node | A loop |

**Match joins to their splits before generating either.** Walk back from each
multiple-incoming node to the nearest common ancestor. If that ancestor is a parallel
split, the join waits for all its branches; if it is exclusive, exactly one branch
arrives and waiting for all deadlocks the run. The same shape in the picture means two
opposite things, and the difference is only visible from the split.

**A loop needs a bound before it needs code.** A back edge with no exit condition is a
run whose history grows without limit until replay stops being viable. Find the exit
condition, or generate a bounded loop with an explicit maximum and say in the summary
that you chose the bound.

## Record to construct

| IR | Construct |
| --- | --- |
| `activity`, `type: "task"` | Call an activity, await it |
| `activity`, `task_type: "call_activity"` | Call a child workflow |
| `activity`, `wait_for_event`, one message event | Wait for an external event |
| `activity`, `wait_for_event`, message and timer events | Race the event against a durable timer, take the first, cancel the loser |
| `activity`, `wait_for_event`, timer only | A durable timer |
| `activity`, `multi_instance_type` set | Not generated. Emit a single instance and say so |
| `gateway`, `exclusive`, diverging | `if` / `else if` / `else`, one branch per `flows` entry, `is_default` last |
| `gateway`, `inclusive`, diverging | Independent `if`s that each start a task, then wait for the ones that started |
| `gateway`, `parallel`, diverging | Start every branch, wait at the join |
| `gateway`, `event-based`, diverging | Wait for the first of the events, branch on which arrived |
| `gateway`, `parallel`, converging | The wait-for-all point |
| `gateway`, `exclusive` or `inclusive`, converging | Nothing executable. The paths meet |
| `failure_handling`, `error_boundary_event` | Catch around the activity, then the handler path |
| `failure_handling`, `timer_boundary_event` | Race the activity against a timer, handler path on timeout |
| `data_object` | A field on a model |
| `start_end_node`, `type: "start"` | The orchestrator entry point |
| `start_end_node`, `type: "end"` | A return |
| `participant` | Nothing executable. A namespace, a module, or separate apps |
| `edge` | Sequencing only. Never a construct of its own |
| `unrecognized_item` | A comment at the site, and a line in the summary |

`condition_label` and `event_label` are the branch names. Use them verbatim, converted
to the language's casing — they were made globally unique for exactly this, so a
branch named `level1_approved` in the code can be found in the IR and traced to the
arrow that produced it.

An **inclusive** gateway is the one worth care. It is not a chain of `else if`: every
condition is evaluated and every branch that passes runs, concurrently. Generating it
as exclusive silently drops work whenever two conditions hold, which is the case the
author drew an `O` to describe.

## Conditions are text, not code

A `condition` in the IR is what somebody wrote on an arrow: `Amount > 1000`,
`Approved`, `Balance <= 0`, `${inStock == true}`. It is documentation of intent. Never
`eval` it, never pass it to an expression engine, and never emit it into a string that
something later parses.

Three ways to turn one into code, in order of preference:

1. **It names a field on a model you already have.** Emit the comparison directly, with
   the original text as a comment above it.
2. **It is a business rule over workflow state.** Emit a small pure function on the
   model — `order.isHighValue()` — and put the original text in its doc comment.
3. **It needs information the workflow does not hold.** Emit a **decision activity**
   that returns the branch label, and branch on that.

The third case is the one that gets mishandled. "Is the customer a VIP?" is not a
condition the orchestrator can evaluate — answering it means a lookup, and a lookup in
an orchestrator body is I/O on the replay path. The activity returns the label; the
orchestrator branches on it. Whenever a condition needs to *find something out*, that
is an activity, not an `if`.

A decision activity is **the one function in the generated code that does not
correspond to a box**. Name it after the gateway — `gw_in_stock` becomes
`evaluate_in_stock` — and list it in the summary as generated from the gateway, not from
a step. Otherwise the next reader compares the code to the diagram, finds an activity
with no box, and has to work out from scratch whether it was invented.

A condition you cannot classify is an `unrecognized_item`, not a guess.

## Two rails, per box

Run these as you write each construct, not as a review afterwards.

**The orchestrator body re-executes from the top on every replay.** So, inside it: no
wall clock, no random, no new ids, no HTTP, no database, no file, no environment, no
globals, no sleeping, no threads. Iterate maps and dictionaries in sorted key order.
Every one of those belongs in an activity, and a "wait 3 days" box is a durable timer.

**Activities run at least once.** A retry after a partial failure re-runs the whole
activity, so "Charge card", "Send email" and "Create shipment" will occasionally
execute twice for one logical step. Key each one on the instance id plus the activity
name — both already in the IR — and never let two activities own the same write.

Both are covered at length by the `catalyst-workflow-determinism` and
`catalyst-activity-idempotency` skills in this collection. Here they are a per-box
checklist.

One more, specific to generated code: **renaming or reordering activities breaks runs
already in flight**, because old history replays against new code. If you are
regenerating a workflow that has live instances, generate under a new workflow name and
let the old instances drain.

## Files

Follow whatever the repository already does. Absent a convention:

```
<project>/
  <workflow-name>/
    workflow.<ext>       the orchestrator
    activities.<ext>     one function or class per activity
    models.<ext>         input, output, and one type per data object
  README.md
  .workflow.ir.jsonl     the IR this was generated from
```

No `statestore.yaml` and no local broker: on Catalyst the managed workflow store is
already attached to the project.

**Keep `.workflow.ir.jsonl`.** It is the only record of why the code has the shape it
has once the diagram has gone back to being a photo in someone's phone.

## Per language

| Language | Package | Signatures |
| --- | --- | --- |
| Python | `dapr`, `dapr-ext-workflow` | [languages/python.md](languages/python.md) |
| .NET | `Dapr.Workflow` | [languages/dotnet.md](languages/dotnet.md) |
| Java | `io.dapr:dapr-sdk-workflows` | [languages/java.md](languages/java.md) |
| Go | `github.com/dapr/durabletask-go` | [languages/go.md](languages/go.md) |
| TypeScript / JavaScript | `@dapr/dapr` | [languages/javascript.md](languages/javascript.md) |

Resolve the version against the registry before writing it into a manifest, and if you
cannot, name the package without one. A coordinate that 404s sends the user hunting for
a Catalyst problem that does not exist, and `Dapr.Workflow` has shipped a preview ahead
of stable before, so newest is not the same as newest stable. There is no Diagrid
workflow package on any registry, in any language — a workflow needs the Dapr SDK.

### The differences that cross-contaminate

Five SDKs built on the same engine, with five different spellings for the same idea.
These are the ones that get copied from the wrong language and compile — or worse,
compile and misbehave.

| | Python | .NET | Java | Go | JS |
| --- | --- | --- | --- | --- | --- |
| Wait for all | `when_all(...)`, module-level | `Task.WhenAll` | `ctx.allOf(...)` | **nothing** | `ctx.whenAll(...)` |
| Wait for first | `when_any(...)`, module-level | `Task.WhenAny` | `ctx.anyOf(...)` | **nothing** | `ctx.whenAny(...)` |
| Instance id | `ctx.instance_id` | `ctx.InstanceId` | `ctx.getInstanceId()` | `ctx.ID()` | `ctx.getWorkflowInstanceId()` |
| Replay-safe now | `ctx.current_utc_datetime` | `ctx.CurrentUtcDateTime` | `ctx.getCurrentInstant()` | `ctx.CurrentTimeUTC()` | `ctx.getCurrentUtcDateTime()` |
| Reading input | 2nd parameter | 2nd parameter | `ctx.getInput(T.class)` | `ctx.GetInput(&v)` | 2nd parameter |
| Retry policy type | `RetryPolicy` | `WorkflowRetryPolicy` | `WorkflowTaskRetryPolicy` | `workflow.RetryPolicy` | **none exists** |
| Returning output | `return` | `return` | `ctx.complete(x)` | `return` | `return` |

Two of those cells change what you can generate at all:

**Go has no when-any and no when-all.** Not a different name — the module exports
neither. A parallel gateway becomes "create every task, then await each in turn", and
an event-raced-against-a-timer becomes the timeout argument on
`WaitForExternalEvent`. A diagram that races two *events* against each other has no Go
expression; say so rather than approximating it.

**JavaScript has no retry policy.** `callActivity` takes an activity and an input, and
that is the whole signature. A retry from a diagram becomes an explicit bounded loop
with a timer between attempts, in the orchestrator, which is deterministic and fine —
but it is code you have to write rather than a parameter you can pass.
