# Mermaid to IR

Mermaid is text, so this path is deterministic like the BPMN one — no vision, no
confidence guessing about what a shape was. It is also the input most people actually
have, because it is what lives in the README and the design doc.

Two dialects matter: `flowchart` (and its older alias `graph`) and `sequenceDiagram`.
They need different rules and the difference is not cosmetic.

> New in this skill. The upstream `create-workflow-from-diagram` skill in
> [diagrid-labs/dapr-skills](https://github.com/diagrid-labs/dapr-skills) explicitly rejects
> Mermaid — "stop, tell the user the input type is not supported in v1, suggest they
> export to BPMN or a standard image". Nothing here is lifted; it targets the IR
> contract in [ir-schema.md](ir-schema.md), which is.

## Both dialects

**Direction is layout, never order.** `flowchart TD` and `flowchart LR` describe where
Mermaid puts the boxes. Order comes from arrows only. A node drawn above another is
not its predecessor, and reading top-to-bottom is how you produce a plausible workflow
that does the steps in the wrong sequence.

**Cosmetics are cosmetic.** Ignore `classDef`, `class`, `style`, `linkStyle`,
`click`, `accTitle`, `accDescr` and `%%` comments. One exception: a class or comment
that plainly carries meaning — `class chargeCard external`, `%% needs human approval`
— is worth an `unrecognized_item` with `category: "annotation"` rather than a silent
drop.

**`~~~` is an invisible link.** It exists to push layout around and is not flow. Emit
nothing.

## `flowchart` node shapes

| Mermaid | Record |
| --- | --- |
| `id[Text]` rectangle | `activity`, `task_type: "standard_task"` |
| `id(Text)` rounded | `activity`, `task_type: "standard_task"` |
| `id([Text])` stadium | `activity` — but see below |
| `id[[Text]]` subroutine | `activity`, `task_type: "call_activity"` |
| `id[(Text)]` cylinder | `data_object` |
| `id((Text))` circle | `start_end_node` |
| `id(((Text)))` double circle | `start_end_node`, `type: "end"` |
| `id{Text}` rhombus | `gateway` |
| `id{{Text}}` hexagon | `activity` — unless it splits, see below |
| `id[/Text/]` or `id[\Text\]` parallelogram | `activity` plus a `data_object` |
| `id[/Text\]` or `id[\Text/]` trapezoid | `activity`, `task_type: "manual_task"` |
| `id>Text]` asymmetric | `activity`, `task_type: "standard_task"` |

Recent Mermaid also allows a node to name its own shape, as
`id@{ shape: diamond, label: "Approved?" }`. When a diagram uses that form, take the
declared shape literally and skip the bracket inference entirely — it is the only
Mermaid input that states its intent rather than implying it.

**The stadium problem.** `([Text])` is Mermaid's most overloaded shape. In a
hand-written flowchart it is nearly always the start or the end — `A([Start])`,
`Z([Done])` — but it is also a perfectly ordinary node shape. Decide on edges, not on
text: no incoming edges makes it the start, no outgoing edges makes it an end, and
anything with both is an activity. Then check the label, and if a node you called an
activity is labelled "Start", "Begin", "Done", "End" or "Finish", trust the label and
raise an `unrecognized_item`.

**The hexagon.** `{{Text}}` is a preparation step, so it is an activity by default.
If it has more than one outgoing edge and those edges are labelled, it is being used
as a decision — treat it as an `exclusive` diverging gateway.

## `flowchart` edges

| Mermaid | Meaning |
| --- | --- |
| `-->`, `---`, `==>`, `--o`, `--x` | Control flow. Emit an `edge`. |
| `-.->`, `-.-` | Dotted. **Not** control flow. Emit no edge. |
| `~~~` | Invisible. Emit nothing. |
| `<-->`, `o--o`, `x--x` | Bidirectional. Ambiguous — flag it. |

Arrow length (`-->` versus `---->`) is a layout hint in Mermaid and carries no
meaning. Thick `==>` usually marks a happy path; record that as `visual_label` if the
author bothered, but never as a condition.

Labels come in two spellings — `A -- Yes --> B` and `A -->|Yes| B` — and mean the same
thing. Route them the way [ir-schema.md](ir-schema.md) requires: decision logic into
`gw_flow_condition` and into the owning gateway's `flows`, description into
`visual_label`. "Yes", "No", "Amount > 100", "rejected" are conditions. "async",
"retry path", "then" are descriptions.

A bidirectional arrow almost always means two people drew a request and a response as
one line. Do not turn it into two edges and do not pick a direction: emit an
`unrecognized_item` with `category: "uncategorized"`, `ask_user: true`. A reversed
edge produces a workflow with a loop nobody intended.

## `flowchart` gateway inference, which inverts the image rule

A drawn diagram distinguishes a fork from a choice with a marker inside the diamond —
`+` for parallel, `X` or nothing for exclusive. **Mermaid has no such marker.** The
rhombus is the only decision shape it offers, so the inference has to run the other
way round:

| Shape | Outgoing edges | Verdict |
| --- | --- | --- |
| `{...}` rhombus | 2+, all labelled | `exclusive`, `diverging`. Conditions from the labels. |
| `{...}` rhombus | 2+, unlabelled | **Ambiguous.** Ask. |
| `{...}` rhombus | 2+ incoming, 1 outgoing | `exclusive`, `converging`. |
| Any other shape | 2+, unlabelled | `parallel`, `diverging` — an implied fork. |
| Any other shape | 2+, labelled | `exclusive`, `diverging` — an implied choice. |

An unlabelled rhombus split does not mean parallel. It means somebody drew a decision
and did not write the conditions on it. Guessing `parallel` there turns a choice into
a fan-out that runs every branch — including, in the usual order-processing example,
both the refund and the shipment. Emit `unrecognized_item` with
`category: "gateway_condition"` and `ask_user: true`.

The forks and joins implied by bare `A --> B` / `A --> C` fan-out are **not** drawn, so
they are not `gateway` records. Leave them to the generator's connectivity pass, the
same as on the image path.

**Mixed labelling on one node's outgoing edges** — one arrow labelled `declined`, the
other bare — is an exclusive split whose unlabelled arrow is the default. Set
`is_default: true` on it. This is the commonest hand-written shape and reading it as a
parallel fork runs the failure path alongside the happy one.

## Waits, in a notation that has no timer

Mermaid gives you no clock icon and no boundary event, so a wait arrives as an ordinary
rectangle with a telling label — `Wait for restock`, `Wait 7 days`, `Await approval`,
`Poll until ready`. Read the label. A node whose label opens with *wait*, *await*,
*poll*, *pause* or *sleep* is `type: "wait_for_event"`, not a task.

Then look at what leaves it. **Outgoing edges labelled with things that happen** —
`restocked`, `7 days`, `approved`, `timeout` — are events, not conditions. Each becomes
an entry in the activity's `events` array with that entry's `next` pointing at the
arrow's target, and the timer entry gets the ISO 8601 form of whatever duration the
label names. Outgoing edges labelled with things that are *true* — `Yes`, `> 100` — are
conditions, and the node is a gateway after all.

Generating a wait as a task is the mistake that costs the most: an activity has to
return, so a seven-day wait becomes either an activity that blocks a worker for a week
or one that returns immediately and skips the wait entirely.

Boundary events have no Mermaid spelling at all. A failure path drawn as a labelled
arrow out of an activity is an exclusive split in the IR, not a `failure_handling`
record — say so in the summary, and if the user wants real boundary semantics, ask for
BPMN.

`subgraph name [Title] ... end` is a swimlane. Emit a `participant` per subgraph and
assign it to every element inside. Nested subgraphs take the innermost.

## `sequenceDiagram`

A sequence diagram describes *messages between participants*, which is a different
thing from a flowchart's *steps in an order*, and the mapping has to bridge that.

**Pick the orchestrator first.** It is the participant that sends the most messages,
which in practice is the service or system column rather than a person or an external
API. Everything the orchestrator calls becomes an activity; everything the
orchestrator waits to be told becomes an event. Get this wrong and the whole workflow
comes out inside out, so state your choice to the user before generating.

| Mermaid | Record |
| --- | --- |
| `participant x as Name`, `actor x as Name` | `participant` |
| `orch->>svc: Charge card` | `activity`, `task_type: "service_task"` |
| `svc-->>orch: result` | **nothing** — see below |
| `orch->>orch: Recalculate` | `activity`, `task_type: "script_task"` |
| `orch-)svc: Publish event` | `activity`, `task_type: "send_task"` |
| `orch--xsvc: Fire and forget` | `activity`, `task_type: "send_task"` |
| `user->>orch: Approve` (unsolicited) | `activity`, `type: "wait_for_event"` |
| `alt cond` / `else cond` / `end` | `gateway`, `exclusive`, one flow per branch |
| `opt cond` / `end` | `gateway`, `exclusive`, the branch plus a default that skips |
| `par` / `and` / `end` | `gateway`, `parallel`, diverging, plus a converging join |
| `critical` / `option` / `end` | as `alt` |
| `break cond` / `end` | `gateway`, `exclusive`, one branch to an end node |
| `loop text` / `end` | a loop in the orchestrator |
| `Note over a,b`, `Note left of a` | `unrecognized_item`, `category: "annotation"` |
| `activate`, `deactivate`, `->>+`, `->>-` | nothing |
| `autonumber`, `box`, `rect` | nothing, except `box` as participant grouping |

**A dashed reply is not a step.** `svc-->>orch: charged` is the return value of the
`orch->>svc: Charge card` activity that preceded it. Emitting an activity for the
reply doubles every call in the diagram, which is the single most common way a
sequence diagram produces a workflow with twice the steps it should have. The dashed
reply contributes the activity's *output*, nothing more.

The distinction that matters is unsolicited versus reply. An inbound message that
answers a call the orchestrator just made is a return. An inbound message that answers
nothing — an approval arriving from a human, a webhook from a payment provider — is an
external event, and becomes `type: "wait_for_event"` with an `event_label`.

**Durations hide in prose.** Sequence diagrams have no timer shape, so a wait shows up
as `Note over orch: wait 2 days` or a self-message `orch->>orch: sleep 30s`. Read it
as a timer, put the ISO 8601 form in `event_definition`, and raise an
`unrecognized_item` with `category: "ambiguous_timer_definition"` when the text is
loose. Never let a sleep become an activity — the whole point of a durable timer is
that nothing is running while it waits.

**No start, no end.** Sequence diagrams do not draw them. Emit a `start` before the
first activity and an `end` after each terminal path, and log an
`unrecognized_item` with `category: "missing_start_symbol"`, `ask_user: false`.

**`loop` needs a bound.** `loop until approved` with no exit condition becomes a
workflow whose history grows forever. Ask what ends it, and if the answer is "it
polls", say plainly that the shape wanted is a timer plus a bounded retry count, not
an unbounded loop.

## Other text dialects

`stateDiagram-v2` maps cleanly enough to be worth trying: states become activities,
`[*]` becomes start and end, transitions become edges, and a transition guard
`s1 --> s2: approved` becomes a condition. Choices (`<<choice>>`) and forks
(`<<fork>>` / `<<join>>`) map to exclusive and parallel gateways. Say you are doing
this rather than assuming it, since a state machine and a workflow are not the same
thing and the user may have meant a state machine.

`classDiagram`, `erDiagram`, `mindmap`, `gantt`, `journey`, `pie`, `gitGraph` and
`C4Context` are not processes. Fail them at Step 1 with the
`DIAGRAM_TYPE_VALIDATION` error, name the diagram type you found, and ask for a
flowchart.
