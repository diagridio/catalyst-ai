# Python

`dapr` and `dapr-ext-workflow`. Signatures below were read from the SDK source at
1.17.3.

```python
from datetime import timedelta

import dapr.ext.workflow as wf

wfr = wf.WorkflowRuntime()


@wfr.workflow(name="order_fulfilment")
def order_fulfilment(ctx: wf.DaprWorkflowContext, order: dict):
    valid = yield ctx.call_activity(validate_order, input=order)
    if not valid:
        return {"status": "rejected"}

    # gw_in_stock: exclusive, diverging
    in_stock = yield ctx.call_activity(check_inventory, input=order)
    if in_stock:                                   # stock_available
        charge = ctx.call_activity(charge_card, input=order)
        label = ctx.call_activity(print_shipping_label, input=order)
        yield wf.when_all([charge, label])          # implied parallel join
        yield ctx.call_activity(ship_order, input=order)
        return {"status": "shipped"}

    # stock_unavailable
    yield ctx.call_activity(notify_backorder, input=order)
    restocked = ctx.wait_for_external_event("restocked")
    deadline = ctx.create_timer(timedelta(days=7))
    winner = yield wf.when_any([restocked, deadline])
    if winner is deadline:                          # restock_wait_expired
        yield ctx.call_activity(cancel_order, input=order)
        return {"status": "cancelled"}
    return {"status": "retry"}


@wfr.activity(name="validate_order")
def validate_order(ctx: wf.WorkflowActivityContext, order: dict) -> bool:
    return bool(order.get("lines"))
```

| Need | Spelling |
| --- | --- |
| Orchestrator | `@wfr.workflow(name=...)` on a **generator** function taking `(ctx, input)` |
| Activity | `@wfr.activity(name=...)` on a function taking `(ctx, input)` |
| Call an activity | `ctx.call_activity(fn, input=..., retry_policy=...)` — everything after the first argument is keyword-only |
| Retry | `wf.RetryPolicy(first_retry_interval=, max_number_of_attempts=, backoff_coefficient=, max_retry_interval=, retry_timeout=)` |
| Timer | `ctx.create_timer(timedelta(...))`, or a `datetime` to fire at |
| External event | `ctx.wait_for_external_event(name)` |
| Wait for all | `wf.when_all([...])` — **module-level**, not on the context |
| Wait for first | `wf.when_any([...])` — module-level |
| Child workflow | `ctx.call_child_workflow(fn, input=, instance_id=, retry_policy=)` |
| Instance id | `ctx.instance_id` |
| Replay-safe now | `ctx.current_utc_datetime` |
| Am I replaying | `ctx.is_replaying` |
| Register | the decorators, or `wfr.register_workflow(fn, name=)` / `wfr.register_activity(fn, name=)` |
| Run the worker | `wfr.start()`, `wfr.shutdown()` |
| Start a run | `wf.DaprWorkflowClient().schedule_new_workflow(fn, input=, instance_id=)` |

Import surface, all from `dapr.ext.workflow`: `WorkflowRuntime`,
`DaprWorkflowClient`, `DaprWorkflowContext`, `WorkflowActivityContext`, `RetryPolicy`,
`when_all`, `when_any`, `WorkflowState`, `WorkflowStatus`.

## Traps

**Every await is a `yield`.** A `call_activity` whose result is never yielded returns a
task object, and comparing a task to a boolean is truthy — so a gateway generated
without the `yield` takes the same branch every time and nothing errors.

**`when_any` returns the winning task, so compare by identity.** Keep a reference to
each task before racing them, then test `winner is deadline`. Comparing results instead
breaks the moment two branches can return the same value.

**`wait_for_external_event` has no timeout argument** at 1.17.3. An event-or-timeout
from the diagram is a `when_any` over the event and a `create_timer`, which is also the
shape that lets you tell the two outcomes apart. Newer checkouts add a `timeout=`
keyword — do not emit it unless the target version has it.

**The activity context is not the workflow context.** It exposes `ctx.workflow_id` and
`ctx.task_id`, and there is no `instance_id` on it. Key idempotency on
`ctx.workflow_id` plus the activity name.

## Serialization

Activity inputs and outputs go through JSON. Dataclasses and Pydantic models are fine
if every field is JSON-representable; keep timestamps as ISO 8601 strings rather than
`datetime`, and keep anything with a socket, a lock or a file handle out of the payload
entirely. If a `data_object` in the IR has no obvious JSON shape, generate a `TypedDict`
or a dataclass for it and say in the summary that the field types were inferred.
