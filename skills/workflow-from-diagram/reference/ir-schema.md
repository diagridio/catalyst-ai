# The IR contract

The intermediate representation every input path produces and the code generator
consumes. Read this before emitting a single record.

> Adapted from the `create-workflow-from-diagram` skill in
> [diagrid-labs/dapr-skills](https://github.com/diagrid-labs/dapr-skills) (MIT). The record
> shapes, field names, `check_id` values and validation rules are kept as they are
> upstream — they are a contract, and a renamed field is a broken generator. The prose
> around them was rewritten for Catalyst.

## Output format

JSON Lines. One complete, valid JSON object per line.

- Every line starts with `{` and ends with `}`.
- No wrapping array, no wrapping object.
- No markdown fences, no prose, no comments, no blank lines between records.
- The only line that is not a record is nothing — even the terminator is a record.

The format is line-oriented so a long extraction can be streamed and each record
validated on its own. A single large JSON object cannot be checked until it is
finished, and a truncated one is unrecoverable; a truncated JSON Lines stream is
still valid up to its last newline.

## Record types

Every record carries `__type`. The double underscore is part of the name.

| `__type` | What it is |
| --- | --- |
| `metadata` | The diagram and the extraction. First record of the stream. |
| `content_warning` | The input depicts something out of scope. Terminates the stream. |
| `system` | Progress marker, for watching a long extraction. Code generation ignores these. |
| `participant` | A role, system or department that performs work. |
| `activity` | A unit of work, or a wait state. |
| `gateway` | A branch or a join that is *drawn* in the diagram. |
| `data_object` | A document, message or record the work reads or writes. |
| `failure_handling` | An interruption or exception path attached to an activity. |
| `unrecognized_item` | Something that could not be classified, or an ambiguity worth a question. |
| `start_end_node` | A start or end event. |
| `edge` | One control-flow connection between two elements. |
| `result` | The verdict of validation. |
| `error` | A fatal problem. Carries a `check_id`. |
| `end_of_ir_stream` | The last line, and only on full success. |

**Explicit only.** Emit what is drawn. A join that the picture implies but does not
draw is *not* a `gateway` record — the code generator infers those from `edge`
connectivity, deterministically, where a guess by the extractor would not be
reproducible. Extraction is the lossy step; keep the loss on the side of omission.

## Progress and termination

```json
{"__type": "system", "__step": "2.B", "__description": "Extract Activities"}
{"__type": "end_of_ir_stream", "__description": "End of JSON Lines IR output."}
```

`end_of_ir_stream` appears **only** when validation produced `"success": true`. Its
absence is how a consumer knows the stream is not trustworthy, so never emit it
optimistically. Ignore anything after it.

### Running out of room

A large diagram can exhaust the output budget. If that happens:

1. Keep the records already emitted — they are individually valid.
2. Set `truncated: true` in `metadata`.
3. Emit, as the very last line:

```json
{"__type": "error", "error": "Output truncated due to token limit. The generated IR is incomplete and should not be considered fully valid.", "truncated": true}
```

4. Do **not** emit `end_of_ir_stream`.

Shed in this order: `system` markers, then `data_object`, then `unrecognized_item`
with `impact: low` or `ask_user: false`. Never shed `metadata`, `participant`,
`activity`, `gateway`, `start_end_node`, `edge` or `failure_handling` — dropping any
of those produces IR that validates as connected while describing a different
process, which is worse than a stream that admits it was cut off.

## Step 0 — Is the input in scope

If the diagram depicts something outside ordinary business process logic, emit one
line and stop. Nothing else, and do not describe what you saw.

```json
{"__type": "content_warning", "status": "offensive", "reason": "Input diagram contains content violating safety guidelines.", "action_recommended": "do_not_store_image"}
```

## Step 1 — Classify and size it

Is this a step-by-step process — a flowchart, a BPMN model, a sequence diagram, a
whiteboard sketch of a flow? Or is it a static picture: an architecture diagram, a
class diagram, an org chart, an ER diagram, a mind map?

Then count the activities. **More than 10 and you stop.** Not because the model
cannot read it, but because past that size the extraction is confident and wrong in
places nobody checks, and an unreviewed 30-step workflow is a liability. Ask for the
diagram to be split into a parent and children instead — that is a better decomposition
anyway, and the IR supports it.

```json
{"__type": "error", "check_id": "DIAGRAM_TYPE_VALIDATION", "diagram_type": "entity_relationship_diagram", "error": "Diagram could not be interpreted as a processable workflow.", "user_feedback": "Cannot process as a step-by-step workflow because it appears to show entity relationships rather than a sequence of actions.\nSuggestion: To process, redraw using shapes like rectangles for steps, connected by arrows showing the flow over time from a start to an end."}
{"__type": "error", "check_id": "DIAGRAM_COMPLEXITY_ABOVE_THRESHOLD", "diagram_type": "workflow", "complexity": "high", "activity_count": 17, "error": "Workflow exceeds maximum allowed complexity threshold of 10 activities.", "user_feedback": "This diagram has 17 activities. Split it into one top-level flow that calls child workflows, and I will generate each."}
```

`user_feedback` is read by a person, so it earns its own rules: state the conclusion
first, give one or two reasons **specific to this diagram**, offer one or two concrete
visual fixes, and use no internal vocabulary — no "IR", no "schema", no "record".
Escape newlines; never emit a literal newline inside a JSON string.

Databases and external services drawn for context are **not** participants. They are
`data_object` interactions, unless the diagram gives them a lane and work happens in it.

## Step 1.5 — `metadata`, and it goes first

```json
{"__type": "metadata", "schema_version": "1.0", "diagram_type": "workflow", "complexity": "medium", "truncated": false, "name": "OrderProcessing", "description": "Handles the end-to-end process for customer orders.", "feedback_required": false}
```

`name` is `PascalCase` and will become a type or class name. `complexity` is `low`,
`medium` or `high`. `feedback_required` starts `false` and becomes `true` if any
`unrecognized_item` has `ask_user: true`.

## Step 2A — `participant`

Swimlanes and pools are the strongest signal, one participant per lane. Failing that:
colour and grouping, role labels near boxes, who initiates what. With no signal at
all, emit a single `System` participant at low confidence rather than inventing a cast.

```json
{"__type": "participant", "id": "customer", "role": "Customer", "confidence": "high"}
{"__type": "participant", "id": "system", "role": "System", "confidence": "low"}
```

## Step 2B — `activity`

Fields:

| Field | Rule |
| --- | --- |
| `id` | `snake_case`, unique across **every** record in the stream. |
| `type` | `"task"` or `"wait_for_event"`. |
| `task_type` | Mandatory if and only if `type` is `"task"`. |
| `participant` | Id from Step 2A. Mandatory. |
| `description` | Action-oriented, and only what is visible. |
| `data_objects_flow` | `[{"id": "...", "data_flow": "input\|output\|read\|update"}]` |
| `events` | Mandatory if and only if `type` is `"wait_for_event"`. Non-empty. |
| `asynchronous` | Always `true` for `wait_for_event`. |
| `multi_instance_type` | `"parallel"`, `"sequential"` or `null`. Only from a visible marker. |
| `confidence` | `"high"`, `"medium"` or `"low"`. |

`task_type` is one of `user_task`, `service_task`, `send_task`, `receive_task`,
`script_task`, `business_rule_task`, `manual_task`, `call_activity`, or
`standard_task` when no icon distinguishes it.

Each entry in `events` needs `event_type` (`message`, `timer`, `signal`,
`conditional`, `participant_interaction`), a human `name`, a `next`, and an
`event_label`. `event_definition` is **mandatory for timers**: an ISO 8601 duration
(`P3D`, `PT1H`), an ISO 8601 instant, or a cron expression. If the diagram says
"Friday 6 pm" and you cannot resolve it, keep the literal string, drop confidence to
`low`, and raise an `unrecognized_item` with
`category: "ambiguous_timer_definition"` — a wrong timer is a workflow that fires at
the wrong time and looks correct in review.

`event_label` and `condition_label` share one namespace and **every one of them must
be globally unique across the whole stream.** They become variable, enum and branch
names in generated code, so a collision is a compile error at best and two branches
silently merged at worst. Name the *outcome*, not the step: `manager_approval_received`,
`approval_timeout_expired`, `risk_score_high`. Never `event_1`, never `true`, never
`message`, and never the id of the element that owns it.

Four traps, each of which loses a step or invents one:

- **A start circle with an icon is an activity, not a start node.** An envelope or a
  clock inside the leading circle means the process waits to be triggered. Emit it as
  `type: "wait_for_event"` with its trigger in `events`, and emit **no**
  `start_end_node` for it.
- **A catch event immediately after an event-based gateway is not an activity.** It is
  already described by that gateway's `flows`. Emitting both double-counts the wait.
  A catch event standing alone in the flow *is* an activity, `type: "wait_for_event"`.
- **A boundary event on an activity's border does not change that activity.** Leave
  the `activity` record alone and describe the interruption in `failure_handling`.
- **Dashed and dotted lines are not control flow.** They mean a message or a data
  association. Reflect them in the activity's `task_type` — `send_task`,
  `receive_task`, `service_task` — and emit **no** `edge`.

An activity waits forever if its `events` array has no `timer` entry. That is a
legitimate shape and how you express it: absence, not a sentinel.

```json
{"__type": "activity", "id": "review_application", "type": "task", "task_type": "user_task", "participant": "p3_manager", "description": "Manager reviews the submitted application.", "data_objects_flow": [{"id": "application_doc", "data_flow": "read"}], "asynchronous": false, "multi_instance_type": null, "confidence": "high"}
{"__type": "activity", "id": "wait_for_approval_or_timeout", "type": "wait_for_event", "participant": "p2_order_system", "description": "Waits for manager approval or times out after two days.", "data_objects_flow": [], "events": [{"event_type": "message", "name": "Approval Received", "event_label": "manager_approval_received", "trigger_identifier": "ManagerApprovalMsg", "next": "process_approved_order"}, {"event_type": "timer", "name": "Timeout Expired", "event_label": "approval_timeout_expired", "trigger_identifier": null, "next": "escalate_lack_of_approval", "event_definition": "P2D"}], "asynchronous": true, "multi_instance_type": null, "confidence": "high"}
```

## Step 2C — `gateway`

Only diamonds that are drawn. `type` comes from the symbol inside; `role` comes from
counting edges, and **role is decided first**.

| Inside the diamond | `type` | Semantics |
| --- | --- | --- |
| `X` | `exclusive` | Exactly one outgoing path is taken. `if / else if / else`. |
| `+` | `parallel` | All outgoing paths start at once. No conditions. |
| `O` | `inclusive` | Every path whose condition holds starts. Zero, one or many. |
| Event marker | `event-based` | The first event to arrive selects its path. |

The `O` is decisive. A diamond with an `O` is `inclusive` however plausibly its
labels read as a single choice, because that is the one distinction a reader cannot
recover from the labels alone.

An unmarked diamond needs the two-step rule:

1. `role` first. One in, many out is `diverging`. Many in, one out is `converging`.
2. If `converging`, `type: "exclusive"` — a plain merge.
3. If `diverging`, look at the outgoing arrows. **Labelled** with conditions ("Yes",
   "No", "> 100", "Approved") means `exclusive`. **Unlabelled** means `parallel`. The
   absence of conditions on a split is itself the evidence.

`dual` exists for a diamond that does both, and is nearly always a drawing mistake:
raise an `unrecognized_item` with `category: "ambiguous_gateway_role"` rather than
guessing.

**One edge in this contract, so it does not surprise you.** `diverging` requires
*exactly one* incoming edge, which means the very common "wait, then re-check" shape —
an arrow looping from a later step back into the decision diamond — fails
`DIVERGING_GATEWAY_STRUCTURE` with two incoming edges. That is the contract working, not
a bug in your extraction: a diamond that is both the loop head and the branch point is
genuinely two things drawn as one. Emit the gateway as `diverging`, keep the extra
incoming edge, and raise an `unrecognized_item` with
`category: "ambiguous_gateway_role"` naming the loop. Do not relax the check to make it
pass, and do not delete the back edge to make it pass — the first hides the shape from
the generator and the second deletes the loop.

`flows` depends on both fields:

- `exclusive` or `inclusive`, `diverging`: one entry per path, every field mandatory —
  `{"condition": "<text|null>", "condition_label": "<snake_case>", "is_default": <bool>, "next": "<id>"}`.
  A `null` condition also needs an `unrecognized_item` with
  `category: "gateway_condition"`.
- `event-based`, `diverging`: one entry per event —
  `{"name": "...", "event_type": "...", "trigger_identifier": "<name|null>", "event_definition": "<details|null>", "next": "<id>"}`.
  `event_type` and `next` are mandatory; `event_definition` is mandatory for `timer`
  and `conditional`.
- `parallel` diverging, and **every** converging gateway: `[]`. Empty. The join's
  semantics live in the graph, not in the record.

Every `next` must name a record that exists in the stream.

```json
{"__type": "gateway", "id": "gw_leave_balance", "type": "exclusive", "role": "diverging", "description": "Checks if the employee has sufficient leave balance.", "participant": "system", "flows": [{"condition": "Balance > 0", "condition_label": "leave_balance_sufficient", "is_default": false, "next": "select_leave_type"}, {"condition": "Balance <= 0", "condition_label": "leave_balance_insufficient", "is_default": true, "next": "end_node_rejected"}], "data_objects_flow": [], "confidence": "high"}
{"__type": "gateway", "id": "gw_sync_checks", "type": "parallel", "role": "converging", "description": "Waits for the fraud check and the inventory check.", "participant": "p2_order_system", "flows": [], "data_objects_flow": [], "confidence": "high"}
{"__type": "gateway", "id": "gw_wait_customer_action", "type": "event-based", "role": "diverging", "description": "Waits for a customer response or a timeout.", "participant": "p1_system", "flows": [{"name": "OrderConfirmed", "event_type": "message", "trigger_identifier": "CustConfirmOrder", "event_definition": null, "next": "process_confirmed_order"}, {"name": "ResponseTimeout", "event_type": "timer", "trigger_identifier": null, "event_definition": "PT1H", "next": "send_reminder"}], "data_objects_flow": [], "confidence": "high"}
```

## Step 2D — `data_object`

Explicit data symbols, and data implied by an activity that plainly creates or
consumes something. Mark inferred ones `implicit: true` so a reviewer can tell what
the diagram said from what you concluded.

```json
{"__type": "data_object", "id": "invoice_pdf", "type": "document", "description": "Generated customer invoice", "implicit": false, "confidence": "high"}
{"__type": "data_object", "id": "order_status", "type": "data_record", "description": "Current status of the order", "implicit": true, "confidence": "medium"}
```

## Step 2E — `failure_handling`

Events attached to an activity's border. `associated_activity`, `handler_activity` and
`trigger` are all mandatory.

```json
{"__type": "failure_handling", "id": "boundary_error_pmt", "type": "error_boundary_event", "description": "Handles payment processing failure.", "associated_activity": "process_payment", "handler_activity": "notify_failure_and_refund", "trigger": {"error_code": "PAYMENT_FAILED"}, "confidence": "high"}
{"__type": "failure_handling", "id": "approval_timeout", "type": "timer_boundary_event", "description": "Approval took longer than three days.", "associated_activity": "wait_manager_approval", "handler_activity": "send_approval_reminder", "trigger": {"timer_definition": "P3D"}, "confidence": "high"}
```

`type` is `error_boundary_event`, `timer_boundary_event`, `message_boundary_event`,
`signal_boundary_event` or `conditional_boundary_event`.

## Step 2F — `unrecognized_item`

The record that keeps the extractor honest. Anything unmapped, ambiguous or missing
goes here instead of being smoothed over.

`category` is one of `gateway_condition`, `ambiguous_data_object`,
`ambiguous_timer_definition`, `missing_failure_path`, `ambiguous_gateway_role`,
`missing_start_symbol`, `flow_connector`, `uncategorized`, `annotation`, `other`.
`impact` is `high`, `medium` or `low`. `ask_user` decides whether the pipeline pauses.

```json
{"__type": "unrecognized_item", "id": "unrec_missing_cond_gw1", "description": "Missing condition on the outgoing path from 'gw_decision' to 'activity_x'.", "category": "gateway_condition", "impact": "high", "possible_interpretation": "Might be the default path.", "ask_user": true, "gateway_id": "gw_decision"}
{"__type": "unrecognized_item", "id": "unrec_connector_merge1", "description": "Non-standard shape labelled 'Merging' acting as a converging junction.", "category": "flow_connector", "impact": "high", "possible_interpretation": "Likely a parallel join. Inference required downstream.", "ask_user": false}
```

Any `ask_user: true` sets `feedback_required: true` in `metadata`. **Ask before
generating, not after.** A question answered after the code exists gets answered by
editing code, which is the expensive order.

## Step 2G — `start_end_node`

Plain circles only — thin border for start, thick for end. A start circle carrying a
trigger icon was already emitted as an activity in Step 2B and must not appear here.

No start symbol at all is allowed: log an `unrecognized_item` with
`category: "missing_start_symbol"`, `ask_user: false`, and let the generator take the
node with no incoming edges as the entry point.

```json
{"__type": "start_end_node", "id": "start_node", "type": "start", "description": "Order received", "confidence": "high"}
{"__type": "start_end_node", "id": "end_node_success", "type": "end", "description": "Order complete", "confidence": "high"}
```

## Step 3 — `edge`

One record per **solid** arrow actually drawn between two elements that exist.

```json
{"__type": "edge", "from": "start_node", "to": "validate_order", "type": "synchronous", "visual_label": null, "gw_flow_condition": null, "confidence": "high"}
{"__type": "edge", "from": "check_amount", "to": "process_large_order", "type": "synchronous", "visual_label": null, "gw_flow_condition": "Amount > 1000", "confidence": "high"}
{"__type": "edge", "from": "activity_1", "to": "act2", "type": "synchronous", "visual_label": "Branch B", "gw_flow_condition": null, "confidence": "high"}
```

The two label fields are not interchangeable and the distinction drives gateway
inference:

- `gw_flow_condition` is **decision logic** — `Amount > 100`, `Yes`, `No`,
  `Status == 'Approved'`, `Type A`. Its presence on a split is what makes the split
  exclusive.
- `visual_label` is **description** — "Parallel execution", "Main path", "Branch B".
  It documents; it does not route.

Put a description in `gw_flow_condition` and the generator emits a branch on a
condition that does not exist. Put a condition in `visual_label` and the branch
silently disappears.

Also:

- Start nodes appear only in `from`. End nodes appear only in `to`.
- No edge touches a `data_object`.
- No edges for dashed or dotted lines.
- A `wait_for_event` activity gets one edge per entry in its `events` array,
  `from` the activity `to` that entry's `next`. Optionally label it with the event
  name. Without these the wait looks like a dead end.
- Trace curved and long arrows to where they actually land. Bypass arrows that skip
  several boxes are the ones most often attached to the wrong element, and a
  misattached edge produces a workflow that runs and is wrong.
- Omit `visual_label` on edges leaving an explicit diverging gateway; the logic is
  already in `flows`.

## Step 4 — Validate, and stop if it fails

Run all of these. Each has a stable `check_id` so a failure can be referred to.

| `check_id` | Assertion |
| --- | --- |
| `CONNECTIVITY` | No activity, gateway or start/end node is isolated. `data_object` is exempt. |
| `DATA_OBJECT_USAGE` | Every `data_object` is referenced by some `data_objects_flow`. |
| `GATEWAY_COND_FLOW_VALIDITY` | Conditional diverging `flows` entries are complete and every `next` resolves. |
| `GATEWAY_EVENT_FLOW_VALIDITY` | Event-based diverging `flows` entries are complete and every `next` resolves. |
| `CONVERGING_GATEWAY_EDGES` | Every converging gateway has exactly one outgoing edge. |
| `CONVERGING_GATEWAY_STRUCTURE` | Converging gateways also have more than one incoming edge and an empty `flows`. |
| `DIVERGING_GATEWAY_STRUCTURE` | Diverging gateways have one incoming edge and non-empty `flows` where required. |
| `GATEWAY_COUNT` | The number of `gateway` records equals the number of diamonds in the picture. |
| `START_END_EDGE_RULES` | Start nodes only in `from`, end nodes only in `to`. |
| `EDGE_TARGET_VALIDITY` | Every `from` and `to` names an existing activity, gateway or start/end node. |
| `WAIT_EVENT_STRUCTURE_VALIDITY` | Every `wait_for_event` has a non-empty `events`; each entry has `event_type`, `name`, `next`; timers have `event_definition`. |
| `TASK_TYPE_USAGE` | `task_type` present exactly when `type` is `"task"`. |
| `FAILURE_HANDLING_VALIDITY` | `associated_activity` and `handler_activity` resolve, and the handler has an outgoing path. |
| `PARTICIPANT_ASSIGNMENT` | Every activity and gateway names a real participant. |
| `DEAD_ENDS` | Nothing has incoming edges but no outgoing edges unless it precedes an end node. |
| `LABEL_UNIQUENESS` | Every `condition_label` and `event_label` is unique across the stream. |
| `GLOBAL_ID_UNIQUENESS` | Every `id` is unique across the stream. |
| `COMPLEXITY_ASSESSMENT` | The `complexity` in `metadata` matches what was extracted. Subjective. |
| `ACTIVITY_DESCRIPTION_QUALITY` | Descriptions are meaningful. Subjective. |

`GATEWAY_COUNT` is the check worth arguing with. It is the only one that compares the
IR back against the *picture* rather than against itself, so it is the only one that
catches a diamond you never saw. Count the diamonds again before you trust it.

On failure: emit one `error` per failure, then a `result` with `"success": false`,
then **stop**. No code generation, and no `end_of_ir_stream`.

```json
{"__type": "error", "check_id": "CONNECTIVITY", "element_id": "gw_final_check", "error": "Validation Failed: Explicit gateway 'gw_final_check' is orphaned (no incoming edge)."}
{"__type": "error", "check_id": "LABEL_UNIQUENESS", "error": "Validation Failed: Duplicate condition_label 'is_approved' in gateways 'gw_level1_approval' and 'gw_level2_approval'."}
{"__type": "result", "success": false, "failed_checks": [{"check_id": "CONNECTIVITY", "description": "gw_final_check has no incoming edge."}], "confidence": "low"}
```

Include `element_id` when one element is to blame. Omit it when the failure is global
or involves a pair — `GATEWAY_COUNT` and `LABEL_UNIQUENESS` name their elements in
the message instead, because a single id there would point at the wrong half.

## Steps 5 and 6 — Verdict

Run the checks a second time. The second pass is not ceremony: the first pass runs
while the extraction is still fresh in context and tends to confirm what was just
written, and re-reading the emitted stream as a stranger is what catches a dead end
or a missing gateway.

```json
{"__type": "result", "success": true, "failed_checks": [], "confidence": "high"}
{"__type": "end_of_ir_stream", "__description": "End of JSON Lines IR output."}
```

Then, and only then, generate code.
