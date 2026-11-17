# BPMN 2.0 XML to IR

The deterministic path. BPMN is structured and self-describing, so no vision is
involved: parse the XML and emit the records. Same BPMN in, same IR out, every time —
which makes this the path to prefer whenever the user has a choice, and worth saying
so if they have a modeller open.

Recognise it by extension (`.bpmn`, `.bpmn20.xml`) or by the namespace
`http://www.omg.org/spec/BPMN/20100524/MODEL` on an `.xml` file.

> Adapted from `prompts/bpmn-to-ir.md` in
> [diagrid-labs/dapr-skills](https://github.com/diagrid-labs/dapr-skills) (MIT). The element
> mapping is theirs. It has been re-expressed in the `__type` vocabulary of
> [ir-schema.md](ir-schema.md) — see [Where this differs from upstream](#where-this-differs-from-upstream),
> because the upstream table and the upstream schema disagreed, and a generator can
> only consume one of them.

## Elements

| BPMN element | Record | Notes |
| --- | --- | --- |
| `<bpmn:process>` | `metadata` | `name` is `PascalCase` from `@name`, else `@id`. |
| `<bpmn:participant>`, `<bpmn:lane>` | `participant` | One per pool or lane. |
| `<bpmn:startEvent>` with no event definition | `start_end_node`, `type: "start"` | |
| `<bpmn:startEvent>` with a message or timer definition | `activity`, `type: "wait_for_event"` | And **no** `start_end_node`. A triggered start is a wait. |
| `<bpmn:endEvent>` | `start_end_node`, `type: "end"` | `errorEventDefinition` and `terminateEventDefinition` go in `description`. |
| `<bpmn:task>` | `activity`, `task_type: "standard_task"` | |
| `<bpmn:serviceTask>` | `activity`, `task_type: "service_task"` | |
| `<bpmn:userTask>` | `activity`, `task_type: "user_task"` | |
| `<bpmn:manualTask>` | `activity`, `task_type: "manual_task"` | |
| `<bpmn:scriptTask>` | `activity`, `task_type: "script_task"` | |
| `<bpmn:sendTask>` | `activity`, `task_type: "send_task"` | |
| `<bpmn:businessRuleTask>` | `activity`, `task_type: "business_rule_task"` | |
| `<bpmn:receiveTask>` | `activity`, `type: "wait_for_event"` | One `message` event. See below. |
| `<bpmn:callActivity>` | `activity`, `task_type: "call_activity"` | Called process from `@calledElement`. |
| `<bpmn:subProcess>` | `activity`, `task_type: "call_activity"` | The nested body becomes a child workflow. |
| `<bpmn:exclusiveGateway>` | `gateway`, `type: "exclusive"` | |
| `<bpmn:parallelGateway>` | `gateway`, `type: "parallel"` | |
| `<bpmn:inclusiveGateway>` | `gateway`, `type: "inclusive"` | |
| `<bpmn:eventBasedGateway>` | `gateway`, `type: "event-based"` | Hyphen, not underscore. |
| `<bpmn:intermediateCatchEvent>` | `activity`, `type: "wait_for_event"` | Timer, message or signal, from the child definition. |
| `<bpmn:intermediateThrowEvent>` | `activity`, `task_type: "send_task"` | It emits; it does not wait. |
| `<bpmn:boundaryEvent>` | `failure_handling` | Never an `activity` and never an `edge` endpoint. |
| `<bpmn:sequenceFlow>` | `edge` | `@sourceRef` to `from`, `@targetRef` to `to`. |
| `<bpmn:dataObject>`, `<bpmn:dataObjectReference>` | `data_object` | |
| `<bpmn:messageFlow>` | *nothing* | It is the dashed line. See below. |

## Rules

**Ids.** BPMN `@id` values are unique in the document but are usually machine noise
(`Activity_1x8fh2k`), and the IR requires `snake_case`. Derive the id from `@name`,
lowercased and underscored; fall back to a normalised `@id` when there is no name;
append `_2`, `_3` on collision. The original `@id` has nowhere to live in the IR — do
not invent a field for it — so print the id mapping in the summary you show the user,
because that is the only way they can trace a generated activity back to the box they
drew.

**Labels.** Prefer `@name` for every `description`. Fall back to the id only when
there is no name, and say so, because a description that is really an id is a sign
the model was never labelled and the generated code will read accordingly.

**Gateway role** comes from counting sequence flows, exactly as on the image path: one
in and many out is `diverging`, many in and one out is `converging`. Anything else is
an `unrecognized_item` with `category: "ambiguous_gateway_role"`.

**Conditions live in the gateway, mirrored on the edge.** A
`<bpmn:conditionExpression>` on a flow out of an exclusive or inclusive gateway
becomes an entry in that gateway's `flows` — that is what the generator reads. Copy
the same text into the edge's `gw_flow_condition` for traceability. Preserve the
original expression text verbatim, including `${...}`; it is a hint for a human, not
something to evaluate. Invent a `condition_label` per entry and keep it globally
unique.

**`@default`** on an exclusive gateway marks that flow `is_default: true`. Exactly one
entry per gateway may carry it.

**Timers** keep their ISO 8601 text — `<bpmn:timeDuration>P3D</bpmn:timeDuration>`
becomes `"event_definition": "P3D"`. Do not normalise it into a value-and-unit pair;
the contract wants the string, and every SDK parses ISO 8601 durations already.

**Boundary events do not connect.** A `<bpmn:boundaryEvent>` has an `@attachedToRef`
and an outgoing `<bpmn:sequenceFlow>`. The `attachedToRef` becomes
`associated_activity` and the target of that outgoing flow becomes `handler_activity`.
Emit **no** `edge` for it. A boundary event is not an IR element, so an edge naming it
fails `EDGE_TARGET_VALIDITY` — and this is the single most common way a valid BPMN file
produces IR that will not validate.

**Message flows are not sequence flows.** A `<bpmn:messageFlow>` crosses pools and is
drawn dashed. Emit no edge. Reflect it in the sending activity's `task_type`
(`send_task`) and the receiving one's shape (`wait_for_event`, or `receive_task` where
it does not block). If it carries meaning the record shapes cannot hold, add an
`unrecognized_item` with `category: "annotation"`.

**Lanes assign participants.** Every element inside a `<bpmn:lane>` gets that lane's
id as its `participant`. An element in no lane gets the single default participant.

**Collaborations.** With more than one `<bpmn:process>`, generate one workflow per
process. Do not fuse them into a single orchestrator because the pools exchange
messages — the message exchange is the boundary between two workflows, and flattening
it produces one workflow that waits on itself.

## `receiveTask` is a wait, not a call

A `<bpmn:receiveTask>` blocks until a message arrives, so it maps to
`type: "wait_for_event"` with one `message` entry, not to a task with
`task_type: "receive_task"`. The distinction decides which code comes out: a wait
compiles to an external-event await that can sit idle for a week, while a task
compiles to an activity call that must return. Reserve `task_type: "receive_task"` for
the image path, where a task shape carries an incoming-message icon but the flow
plainly does not stop there.

## Unsupported

Emit an `unrecognized_item` for each, and do not silently drop:

- `<bpmn:adHocSubProcess>` — no ordering to extract.
- `<bpmn:transaction>` — the compensation semantics have no IR equivalent.
- `<bpmn:complexGateway>` — the activation condition is free text.
- Multi-instance markers — record them as `multi_instance_type` on the activity, then
  flag them: the IR carries the marker but nothing generates the fan-out yet, so
  treating one as handled would silently produce a single-instance workflow.
- Compensation events and handlers.
- Escalation events.

## Where this differs from upstream

The upstream repository holds two incompatible descriptions of the IR. The 912-line
`prompts/ir-schema.md` uses `__type`, `role: diverging|converging`, `data_object`, and
puts gateway conditions in `gateway.flows`. The BPMN mapping table, the companion
`REFERENCE.md` and the shipped `examples/order-process.ir.jsonl` use `type`,
`activity_type`, `gateway_type`, `role: split|merge`, `artifact`, `error_handler`,
`child_workflow`, `timeout` and `condition` on the edge.

Three of the four files disagree with the schema. Anything generated against the
minority vocabulary fails the schema's own validation checks, which is why this file
follows the schema and not the table:

| Upstream table | Here | Why |
| --- | --- | --- |
| `{"type": "workflow"}` | `{"__type": "metadata"}` | Schema record name. |
| `activity_type`, `gateway_type` | `type` plus `task_type` | Schema field names. |
| `role: split \| merge` | `role: diverging \| converging` | Schema enum. |
| `event_based` | `event-based` | Schema spelling. |
| `artifact` | `data_object` | Schema record name. |
| `error_handler` on the parent | `failure_handling` record | Schema record name. |
| `timeout` attribute on the parent | `failure_handling`, `timer_boundary_event` | The schema has no `timeout` field. |
| `child_workflow` activity type | `task_type: "call_activity"` | The schema has no `child_workflow`. |
| `condition` on the edge | `flows[].condition`, mirrored to `gw_flow_condition` | The schema has no `condition` on an edge. |
| `{value, unit}` duration struct | ISO 8601 string | The schema wants the string. |
| `messageFlow` as an edge with `cross_participant` | no edge | The schema forbids edges for dashed lines and has no such field. |
| `startEvent` always a start node | a triggered start is an activity | The schema's Step 2B rule, which the table contradicts. |
| `receiveTask` to `wait_for_event` | kept | The table got this one right. |

If you go back to the upstream repo for anything, take `prompts/ir-schema.md` as the
contract and treat the rest as commentary.
