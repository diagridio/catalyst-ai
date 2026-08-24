"""The reviewer-org seed worker: three workflows, one of which genuinely fails.

Run by scripts/seed_reviewer_org.py, via:

    diagrid dev run --project default --id catalyst-demo -- python scripts/seed/app.py

NOT RUN as part of preparing CAT-1734. It is here so the seeding plan references real
code rather than a description of code.

Two shape decisions worth stating, because both are easy to get wrong:

  * No HTTP server, and `dev run` is invoked with no --app-port. A pure workflow worker
    dials Catalyst outbound and polls for work items; there is no inbound endpoint to
    expose and nothing should be listening. Adding a port fails confusingly — every
    workflow registers successfully and then the process dies at bind.

  * The failure is produced by an activity that RAISES. Nothing here writes a Failed
    record into a store. A forged failure has no history, no failing step and no error
    text, so the execution graph a reviewer opens would be empty — a worse demo than
    none, and dishonest about what the platform did.

The bodies obey the replay rules: no wall-clock reads, no randomness, no I/O, no
unsorted iteration. Every side effect is in an activity, and each activity is idempotent
on the instance id plus a stable step name, because activities are at-least-once.
"""

from __future__ import annotations

import dapr.ext.workflow as wf

wfr = wf.WorkflowRuntime()


# --------------------------------------------------------------------------------------
# process-order — the plain happy path, so a reviewer sees a completed multi-step run
# --------------------------------------------------------------------------------------
@wfr.workflow(name="process-order")
def process_order(ctx: wf.DaprWorkflowContext, order: dict):
    validated = yield ctx.call_activity(validate_order, input=order)
    reserved = yield ctx.call_activity(reserve_stock, input=validated)
    return (yield ctx.call_activity(confirm_order, input=reserved))


@wfr.activity(name="validate_order")
def validate_order(ctx, order: dict) -> dict:
    items = int(order.get("items", 0))
    if items <= 0:
        raise ValueError(f"order {order.get('orderId')!r} has no items")
    return {**order, "validated": True}


@wfr.activity(name="reserve_stock")
def reserve_stock(ctx, order: dict) -> dict:
    # Idempotent by construction: keyed on the order id, and re-reserving the same order
    # is a no-op rather than a second reservation.
    return {**order, "reservationId": f"res-{order['orderId']}"}


@wfr.activity(name="confirm_order")
def confirm_order(ctx, order: dict) -> dict:
    return {"orderId": order["orderId"], "status": "confirmed",
            "reservationId": order["reservationId"]}


# --------------------------------------------------------------------------------------
# reconcile-invoice — the one that fails, on demand, for real
# --------------------------------------------------------------------------------------
@wfr.workflow(name="reconcile-invoice")
def reconcile_invoice(ctx: wf.DaprWorkflowContext, invoice: dict):
    ctx.set_custom_status("charging")
    charged = yield ctx.call_activity(charge_card, input=invoice)
    ctx.set_custom_status("reconciling")
    return (yield ctx.call_activity(record_payment, input=charged))


@wfr.activity(name="charge_card")
def charge_card(ctx, invoice: dict) -> dict:
    # The deliberate failure. `card == "expired"` is supplied by the seeding script for
    # exactly two of the twenty-four runs. Everything about the resulting run is real:
    # the activity raises, the orchestrator surfaces it, the run reaches Failed, and
    # catalyst_get_workflow_run shows THIS step with THIS message.
    if invoice.get("card") == "expired":
        raise RuntimeError(
            f"card declined: expired (invoice {invoice.get('invoiceId')!r}) "
            "[seed: deliberate failure, see scripts/seed/app.py]"
        )
    return {**invoice, "chargeId": f"ch-{invoice['invoiceId']}"}


@wfr.activity(name="record_payment")
def record_payment(ctx, invoice: dict) -> dict:
    return {"invoiceId": invoice["invoiceId"], "status": "reconciled",
            "chargeId": invoice["chargeId"]}


# --------------------------------------------------------------------------------------
# fan-out-report — a fan-out, so the execution graph a reviewer opens is not a straight
# line. This is the run worth pointing a reviewer at first.
# --------------------------------------------------------------------------------------
@wfr.workflow(name="fan-out-report")
def fan_out_report(ctx: wf.DaprWorkflowContext, request: dict):
    # sorted(), because iteration order must be stable across replays.
    regions = sorted(request.get("regions", []))
    parts = yield wf.when_all(
        [ctx.call_activity(collect_region, input={"region": r}) for r in regions]
    )
    return (yield ctx.call_activity(assemble_report, input={"parts": parts}))


@wfr.activity(name="collect_region")
def collect_region(ctx, payload: dict) -> dict:
    region = payload["region"]
    # A fixed table rather than a computed figure: a random or clock-derived value would
    # make two runs of the same input differ, which is exactly what a reviewer comparing
    # runs should not have to explain.
    counts = {"eu": 412, "us": 918, "apac": 227}
    return {"region": region, "events": counts.get(region, 0)}


@wfr.activity(name="assemble_report")
def assemble_report(ctx, payload: dict) -> dict:
    parts = payload["parts"]
    return {
        "regions": [p["region"] for p in parts],
        "total": sum(p["events"] for p in parts),
    }


if __name__ == "__main__":
    wfr.start()
    print("seed worker: 3 workflows registered — process-order, reconcile-invoice, fan-out-report")
    # Blocks until interrupted. `dev run` owns the lifecycle; stopping it stops this.
    try:
        import threading

        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        wfr.shutdown()
