---
name: catalyst-workflow-from-diagram
description: Turn a diagram into a durable workflow on Diagrid Catalyst — a Mermaid flowchart, a sequence diagram, a BPMN export, a whiteboard photo or a hand sketch. Use when the design arrives as boxes, arrows and swimlanes rather than as a written request.
---

# From a diagram to a running workflow

Goal: end this skill with a workflow whose structure a reader can check line by line
against the picture that produced it, registered and started once against Catalyst.

The picture is the specification. Everything here exists to keep it that way, because
the failure that matters is not code that will not compile — you find that in seconds —
it is code that compiles, runs, and quietly does something the diagram does not say.

## 1. Never go from the picture straight to code

Four phases, in this order, and the third does not begin until the second passes.

| Phase | In | Out |
| --- | --- | --- |
| 1. Detect | The file or the pasted image | Which input path, and what it is |
| 2. Extract | The input | IR — JSON Lines, one record per element |
| 3. Validate | The IR | A `result` record, and a stop if it fails |
| 4. Generate | The valid IR | Workflow, activities, project wiring |

The intermediate representation is what makes this reviewable. A picture and a source
file cannot be compared by eye at any useful speed, so a direct translation gets
accepted on the strength of looking plausible. The IR is small enough to read in full,
it names every element the diagram contains, and it can be *checked* — a dead end, a
gateway with no conditions, a duplicate label, an edge pointing at nothing are all
mechanical findings against the IR and all invisible in generated code.

It is also what makes the input format replaceable. A Mermaid flowchart, a BPMN export
and a photograph of a whiteboard have nothing in common until they are IR, and after
that the generator does not care which one it was.

Write the IR to `.workflow.ir.jsonl` next to the generated code. It is the artefact
that answers "why did it generate that", months later, when the diagram is gone.

The record types, in one list, so this phase is legible without opening anything:
`metadata`, `participant`, `activity`, `gateway`, `data_object`, `failure_handling`,
`start_end_node`, `edge`, `unrecognized_item`, plus `content_warning`, `system`,
`error`, `result` and `end_of_ir_stream` for the machinery.
[reference/ir-schema.md](reference/ir-schema.md) is the contract: every field, every
`check_id`, and the extraction steps in order. Load it before emitting a record.

## 2. Name the input before you read it

| What arrived | Path |
| --- | --- |
| A fenced `mermaid` block, an `.mmd` file, or text opening with `flowchart`, `graph`, `sequenceDiagram` or `stateDiagram-v2` | [reference/mermaid-to-ir.md](reference/mermaid-to-ir.md) |
| `.bpmn`, `.bpmn20.xml`, or XML in the BPMN 2.0 namespace | [reference/bpmn-to-ir.md](reference/bpmn-to-ir.md) |
| PNG, JPG, GIF, WebP, a pasted screenshot, a photo of a whiteboard | Vision. Section 3. |
| A PDF or a Visio, Lucid or draw.io export | Ask for the underlying diagram, or a screenshot of it |
| A prose description of a process | Not this skill. It starts from a picture. |

Say which path you took. The user knows whether the thing they handed over was a
photograph or a text file, and hearing it back is how they catch you having read the
wrong attachment.

Prefer text over pixels whenever both exist. Mermaid and BPMN are parsed; an image is
inferred, and inference has a confidence field for a reason. If someone screenshots a
Mermaid diagram, ask for the source.

## 3. Reading a picture

Vision only, and only after the two text paths are ruled out. The shape cues:

| Drawn | Record |
| --- | --- |
| Rectangle, rounded rectangle | `activity`, `type: "task"` |
| Diamond | `gateway`. The marker inside gives the type — `+` parallel, `X` exclusive, `O` inclusive, an event icon event-based |
| Thin-bordered circle | `start_end_node`, `type: "start"` |
| Thick-bordered or doubled circle | `start_end_node`, `type: "end"` |
| Circle with an icon — envelope, clock | An `activity` that waits, **not** a start node |
| Circle on an activity's border | `failure_handling`, not an activity |
| Solid arrow | `edge` |
| **Dashed or dotted arrow** | **No edge.** A message or a data association |
| Swimlane, pool | `participant` |
| Cylinder, document, note | `data_object` |
| Anything else | `unrecognized_item` |

Three of those rows are where a plausible extraction goes wrong, and all three are
subtractions rather than additions — the dashed arrow that becomes control flow, the
triggered start circle that becomes both a start node and a wait, the boundary event
that becomes an ordinary step in the happy path. Each produces a workflow that runs.

A photograph brings its own problems: a glare band across an arrowhead, a label in
handwriting that could be `50` or `5o`, an arrow that leaves the frame. Read what is
there, mark the rest `low` confidence, and put every one in `unrecognized_item`.
Guessing at a cropped arrow is how a diagram of five steps becomes a workflow of four.

**Count the diamonds before you finish.** `GATEWAY_COUNT` is the only check that
compares the IR back against the picture rather than against itself, so it is the only
one that can catch a branch you never saw.

## 4. Ask before you generate, not after

Any `unrecognized_item` with `ask_user: true` sets `feedback_required: true`, and that
is a stop. Put the questions in one message, numbered, each naming the element it is
about and what you will assume if they say nothing.

Two answers are worth more than the rest:

- **An unlabelled split.** Which branch runs when? A wrong guess here does not fail; it
  runs both the refund and the shipment.
- **A loop with no visible exit.** What ends it? A poll drawn as a cycle becomes a
  workflow whose history grows until the run cannot be replayed.

Then stop asking. Three questions is a conversation; ten is a form, and the diagram
was supposed to save them from filling one in. Assume, label the assumption in the
generated code, and list the assumptions at the end.

## 5. Detect the language, never ask which one

Language is a parameter of this skill, not a variant of it — one skill that reads the
repository, not five that compete for the same request.

| Found at the top level | Language |
| --- | --- |
| `pyproject.toml`, `requirements.txt`, `*.py` | Python |
| `*.csproj`, `*.sln`, `global.json` | .NET |
| `pom.xml`, `build.gradle` | Java |
| `go.mod` | Go |
| `package.json`, `tsconfig.json` | TypeScript / JavaScript |

Ask only when the directory is empty, or when two of these sit side by side and the
workflow could plausibly live in either.

All five can host a Dapr Workflow, because a workflow needs the **Dapr SDK** and
nothing else. There is no Diagrid adapter in this path and no language is second
class here — the adapter gap people remember is an agent-framework question, not a
workflow one. Coordinates and per-language shapes are in
[reference/codegen.md](reference/codegen.md).

## 6. Generate from the IR, one record at a time

Walk the IR and emit code. The mapping from record to construct, the five languages'
signatures, the file layout and the serialization traps are in
[reference/codegen.md](reference/codegen.md);
[reference/worked-example.md](reference/worked-example.md) runs a small flowchart all
the way through so the shape of the output is not left to imagination.

Four rules that hold whatever the language:

**Every activity gets a body, even an empty one.** A stub that returns a typed value is
finishable. A `TODO` in the middle of an orchestrator is a workflow that fails on the
step nobody noticed was missing.

**Keep the diagram's names.** An activity called `validate_order` in the IR is
`validate_order` in the code, and the box said "Validate Order". Rename it to
something tidier and you have severed the only link between the picture and the
program.

**One activity per box, no helpful merging.** Two boxes that look like one step are
still two steps, because they are two entries in the run history and two places a
retry can resume from. Collapsing them changes the recovery behaviour of the workflow,
which is the property the user came for.

**The IR is the argument.** Anything not in the IR is not in the code. If the
generated workflow has a step the IR does not, either the extraction missed something
and you go back to phase 2, or you invented a step — and an invented step in a durable
workflow is a side effect nobody asked for.

### The two rails, at generation time

A diagram is drawn by someone thinking about the business, not about replay, so the
picture will happily ask for the two things a durable workflow cannot do. Catch them
here, while the code is being written:

- **A box that reads a clock, a random number, a new id, or the network belongs in an
  activity, not in the orchestrator.** The orchestrator body re-executes from the top
  on every replay, so anything that answers differently the second time corrupts the
  run. A "wait 3 days" box is a durable timer, never a sleep.
- **A box with a side effect must survive running twice.** Activities are
  at-least-once; "Charge card" and "Send email" will occasionally run twice for one
  logical step. Key the idempotency on the instance id plus the activity name, both of
  which the IR already gives you.

Both hazards have their own skills in this collection — `catalyst-workflow-determinism`
for the orchestrator body and `catalyst-activity-idempotency` for the activities. Reach
for those when reviewing a workflow. Here they are a checklist you run per box as you
write it.

## 7. Wire it into Catalyst

**Do not create a project.** Every organization gets one named `default` at signup,
with the managed pub/sub, the managed KV store, the workflow store and agent
infrastructure already attached. Workflow history lives in that managed store, so a
hand-rolled project is the most common reason a freshly generated workflow starts and
then cannot be found. Confirm `default` exists with `catalyst_list_projects` rather than
assuming it; if it is absent, ask which project to use rather than making one.

The generated project needs **no local state-store component and no Docker**. The
managed workflow store is already there, which is most of what makes this shorter than
running Dapr yourself — do not emit a `statestore.yaml` for it, and do not tell the
user to run a broker.

**A project holds one managed pub/sub and one managed KV store.** One is the limit on
every plan, free and paid alike, and no plan upgrade buys a second broker, so never offer
one as the fix. These are plan values overlaid per organization, not constants in the
code, so read the live quota rather than asserting the 1 — and do not promise a user it
can be raised for them, which is a commercial question rather than one you can answer.
It matters here more
than anywhere else, because fan-out is what diagrams are *for*: a parallel gateway with
four branches drawn as four queues is four **topics on the one broker**. Say that as
the fact it is.

The consequence for generated setup steps is concrete. In `default` the managed
`pubsub` and `kvstore` already exist and already consume the one slot, so
applying a second `Pubsub` or `KVStore` is **rejected on quota** —
`current 1, max 1` — and re-applying does not rescue it. Reference the existing components by
name. Emit a create only for a project made without the managed ones, which is not the
project you should be in.

Then run it against Catalyst:

- Make sure the app exists: `catalyst_get_app`, else `catalyst_apply` an `App` (read
  `catalyst_get_resource_schema` first and run with `dry_run`). A write role is needed.
- Start the worker with the connection values in its environment. `catalyst-develop`
  section 3 is the one place that says how, using `catalyst_get_connection`.

**Give the app no endpoint and no port.** What a diagram translates into is a workflow
worker: it dials Catalyst outbound and polls for work items, so there is no inbound
endpoint to expose. Give it an endpoint only if Catalyst must call *into* the
application — service invocation, pub/sub delivery, an agent endpoint. Building an HTTP
server just to answer a port you do not need is a common first-run failure, and it fails
confusingly: the worker registers every workflow and activity, then dies at bind because
something else holds the port.

## 8. Start one run, then read it back

A generated workflow that has never run is not a result.

- `catalyst_start_workflow` with the project, the app identity and the workflow name, and
  the input. It assigns the run id and returns it; keep it.
- `catalyst_list_workflow_runs` for the project, if you lost the id.
- `catalyst_get_workflow_run` for the run.

`catalyst_start_workflow` is a write tool, absent for a role that cannot write. Name the
input after the diagram's happy path so the first run is recognisable later.

Pick the input for that first run off the diagram's own happy path, and check the
result against the boxes it should have visited. `catalyst_get_workflow_run` returns the graph;
comparing that list to the picture is the only end-to-end proof the translation was
faithful, and it is cheaper than reading the generated code again.

Payloads are withheld by default, and by deleting the key rather than returning an empty
value. Never report an absent `output` as a workflow that produced nothing, or you will
send someone to debug working code. Tell the user you can't see it because of the
organization's setting for what AI tools may read, and that they can open the run in the
console. Mention once that an admin of their organization can ask Diagrid to change the
setting. Never forge a data-sharing header, and never ask an administrator to change the
setting so you can finish an answer. The console shows the run under the user's own access:
`https://catalyst.diagrid.io/workflows/<appId>/<runId>` (the console for the production server).

## 9. Hand back the diagram you implemented

Finish with a Mermaid flowchart rendered **from the IR**, not from the input. Round-
tripping it is the check: the user compares your diagram to theirs, and every
difference is either something you got wrong or something their picture did not say.
It is a review a non-programmer can do, which no amount of generated code allows.

Alongside it, state plainly:

- Every assumption you made, and which element it was about.
- Every `unrecognized_item` still open.
- Anything in the code with no box behind it — a decision activity generated for a
  gateway is the usual case, and the one a reader will otherwise assume you invented.
- Which boxes became activities with empty bodies for them to fill in.
- Where `.workflow.ir.jsonl` is.

## Rules

- **Use the Catalyst MCP tools for everything in Catalyst.**
- **Never generate code from a diagram without emitting the IR first.** The IR is what
  makes the translation reviewable, and it is the only artefact that survives.
- **Never generate code from IR that failed validation.** Report the failed `check_id`s
  and stop.
- **Never invent a step the diagram does not contain.** Ambiguity becomes an
  `unrecognized_item` and a question, not a best guess.
- **Never turn a dashed line into control flow.** It is a message or a data
  association, on every input path.
- **Do not create a project.** Use `default`. If it is genuinely absent, say so and
  stop rather than substituting something that behaves differently.
- **Do not stop at code that compiles.** Start one run and read its history back.
- **Do not silently redraw the process.** No merged boxes, no renamed activities, no
  tidied-up branches.
- **Do not present a low-confidence reading as a fact.** Confidence is a field in the
  IR; carry it into what you tell the user.

## Provenance

The pipeline, the IR contract and the BPMN element mapping are adapted from the
`create-workflow-from-diagram` skill in
[diagrid-labs/dapr-skills](https://github.com/diagrid-labs/dapr-skills), which is MIT
licensed. The record shapes, field names and `check_id` values are kept as they are
upstream, because they are a contract and a renamed field is a broken generator.

Everything around them was rewritten: that skill targets Dapr run locally with Docker
and a hand-written state store, where this one targets a Catalyst project that already
has the workflow store. The Mermaid and sequence-diagram paths are new — upstream
rejects Mermaid outright. The upstream repository also carries two incompatible
descriptions of the IR, and
[reference/bpmn-to-ir.md](reference/bpmn-to-ir.md) records which one to believe.
