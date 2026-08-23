# Go

Authoring is `github.com/dapr/durabletask-go/workflow`. The client factory is
`github.com/dapr/go-sdk/client`. Signatures below were read from the SDK source at
`durabletask-go` v0.12.x and `go-sdk` v1.15.0.

```go
import (
	"time"

	"github.com/dapr/durabletask-go/workflow"
	dapr "github.com/dapr/go-sdk/client"
)

func OrderFulfilment(ctx *workflow.WorkflowContext) (any, error) {
	var order Order
	if err := ctx.GetInput(&order); err != nil {
		return nil, err
	}

	var valid bool
	if err := ctx.CallActivity(ValidateOrder,
		workflow.WithActivityInput(order)).Await(&valid); err != nil {
		return nil, err
	}

	// implied parallel fan-out: create both tasks BEFORE awaiting either
	charge := ctx.CallActivity(ChargeCard, workflow.WithActivityInput(order))
	label := ctx.CallActivity(PrintShippingLabel, workflow.WithActivityInput(order))
	if err := charge.Await(nil); err != nil {
		return nil, err
	}
	if err := label.Await(nil); err != nil {
		return nil, err
	}

	// wait_for_restock: a message event with a P7D timer, expressed as the timeout
	var restock RestockNotice
	if err := ctx.WaitForExternalEvent("restocked", 7*24*time.Hour).Await(&restock); err != nil {
		// restock_wait_expired
		if err := ctx.CallActivity(CancelOrder,
			workflow.WithActivityInput(order)).Await(nil); err != nil {
			return nil, err
		}
		return OrderResult{Status: "cancelled"}, nil
	}
	return OrderResult{Status: "shipped"}, nil
}

func ValidateOrder(ctx workflow.ActivityContext) (any, error) {
	var order Order
	if err := ctx.GetInput(&order); err != nil {
		return nil, err
	}
	return len(order.Lines) > 0, nil
}
```

| Need | Spelling |
| --- | --- |
| Orchestrator | `func(ctx *workflow.WorkflowContext) (any, error)` — the input is **not** a parameter |
| Activity | `func(ctx workflow.ActivityContext) (any, error)` — by value, not a pointer |
| Call an activity | `ctx.CallActivity(fn, opts...)` — functional options, not `(name, input)` |
| Activity input | `workflow.WithActivityInput(v)` |
| Retry | `workflow.WithActivityRetryPolicy(&workflow.RetryPolicy{MaxAttempts, InitialRetryInterval, BackoffCoefficient, MaxRetryInterval, RetryTimeout})` |
| Timer | `ctx.CreateTimer(d time.Duration, opts...)` |
| External event | `ctx.WaitForExternalEvent(name string, timeout time.Duration)` |
| Child workflow | `ctx.CallChildWorkflow(fn, workflow.WithChildWorkflowInput(v), workflow.WithChildWorkflowInstanceID(id))` |
| Await anything | `.Await(&out)`, or `.Await(nil)` to discard |
| Instance id | `ctx.ID()` |
| Replay-safe now | `ctx.CurrentTimeUTC()` |
| Am I replaying | `ctx.IsReplaying()` |
| Register | `r := workflow.NewRegistry()`, then `r.AddWorkflow(fn)` / `r.AddActivity(fn)`, or the `...N` variants to name them |
| Run the worker | `c, _ := dapr.NewWorkflowClient()`, then `c.StartWorker(ctx, r)` |
| Start a run | `c.ScheduleWorkflow(ctx, "OrderFulfilment", workflow.WithInput(order))` |

## Traps

**There is no `when_any` and no `when_all`.** The module exports neither, under any
name. Two consequences for generated code:

- A parallel gateway is *create every task, then await each in turn*. Calling `Await`
  on the first task before creating the second silently serialises the branches — the
  workflow is correct and the parallelism is gone, which is the hardest kind of bug to
  see in a diff.
- An event raced against a timer uses the `timeout` argument on
  `WaitForExternalEvent`. A negative duration waits forever; **zero cancels
  immediately**, so never pass a zero you computed. Racing two *events* against each
  other cannot be expressed — say so instead of approximating it.

**Do not import `github.com/dapr/go-sdk/workflow`.** It was real once, in go-sdk
v1.10.0 through v1.13.0, and it was removed in v1.14.0 — which is why stale samples and
even some documentation still say `go get` on it. Code written against it does not
compile now: `ctx.InstanceID()` is `ctx.ID()`, and `worker.RegisterActivity()` is
`registry.AddActivity()`.

**The activity context is passed by value.** `func(ctx *workflow.ActivityContext)` will
not satisfy the registry.

<!-- The removed import path is named here in order to steer away from it, which is the
     opposite of instructing anyone to use it.
     lint-allow-banned: go-sdk/workflow — taught as an import path removed in v1.14.0 -->

## Serialization

Everything crossing an activity or child-workflow boundary is JSON. Design the structs
for it from the start.

```go
type Order struct {
	ID        string   `json:"id"`
	Lines     []Line   `json:"lines"`
	Total     float64  `json:"total"`
	CreatedAt string   `json:"created_at"`  // ISO 8601, not time.Time
	Note      *string  `json:"note,omitempty"`
}
```

What does not survive: `func` fields, `chan`, `sync.Mutex`, anything unexported, and
`time.Time` — which technically marshals but round-trips inconsistently enough to be
worth avoiding in workflow payloads. Tag them `json:"-"` or keep them out of the
payload type. An unexported field simply vanishes, with no error at any point.
