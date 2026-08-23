# .NET

NuGet `Dapr.Workflow`, `using Dapr.Workflow;`. Signatures below were read from the SDK
source at 1.18.4.

```csharp
using Dapr.Workflow;

internal sealed class OrderFulfilment : Workflow<Order, OrderResult>
{
    public override async Task<OrderResult> RunAsync(WorkflowContext context, Order order)
    {
        var valid = await context.CallActivityAsync<bool>(nameof(ValidateOrder), order);
        if (!valid)
        {
            return new OrderResult("rejected");
        }

        // gw_in_stock: exclusive, diverging
        var inStock = await context.CallActivityAsync<bool>(nameof(CheckInventory), order);
        if (inStock)                                     // stock_available
        {
            // implied parallel fan-out and join
            var charge = context.CallActivityAsync(nameof(ChargeCard), order);
            var label = context.CallActivityAsync(nameof(PrintShippingLabel), order);
            await Task.WhenAll(charge, label);
            await context.CallActivityAsync(nameof(ShipOrder), order);
            return new OrderResult("shipped");
        }

        // stock_unavailable
        await context.CallActivityAsync(nameof(NotifyBackorder), order);
        try
        {
            await context.WaitForExternalEventAsync<RestockNotice>(
                "restocked", TimeSpan.FromDays(7));
            return new OrderResult("retry");
        }
        catch (TaskCanceledException)                    // restock_wait_expired
        {
            await context.CallActivityAsync(nameof(CancelOrder), order);
            return new OrderResult("cancelled");
        }
    }
}

internal sealed class ValidateOrder : WorkflowActivity<Order, bool>
{
    public override Task<bool> RunAsync(WorkflowActivityContext context, Order order)
        => Task.FromResult(order.Lines.Count > 0);
}
```

| Need | Spelling |
| --- | --- |
| Orchestrator | `class X : Workflow<TIn, TOut>`, override `RunAsync(WorkflowContext, TIn)` |
| Activity | `class Y : WorkflowActivity<TIn, TOut>`, override `RunAsync(WorkflowActivityContext, TIn)` |
| Call an activity | `CallActivityAsync<T>(string name, object? input = null, WorkflowTaskOptions? options = null)` |
| Retry | `new WorkflowTaskOptions(RetryPolicy: new WorkflowRetryPolicy(maxNumberOfAttempts, firstRetryInterval, backoffCoefficient, maxRetryInterval, retryTimeout))` |
| Timer | `CreateTimer(TimeSpan delay)`, or `CreateTimer(DateTime fireAt, CancellationToken)` |
| External event | `WaitForExternalEventAsync<T>(name, TimeSpan timeout)`, or `(name, CancellationToken)` |
| Wait for all / first | plain TPL `Task.WhenAll` / `Task.WhenAny`. There is no SDK equivalent and none is needed |
| Child workflow | `CallChildWorkflowAsync<T>(name, input, new ChildWorkflowTaskOptions(InstanceId: ..., RetryPolicy: ..., TargetAppId: ...))` |
| Instance id | `context.InstanceId` |
| Replay-safe now | `context.CurrentUtcDateTime` |
| Replay-safe id | `context.NewGuid()` |
| Am I replaying | `context.IsReplaying` |
| Logger | `context.CreateReplaySafeLogger<T>()` — returns `ILogger`, **not** `ILogger<T>` |
| Register | `builder.Services.AddDaprWorkflow(options => { options.RegisterWorkflow<OrderFulfilment>(); options.RegisterActivity<ValidateOrder>(); });` |
| Start a run | `DaprWorkflowClient.ScheduleNewWorkflowAsync(name, instanceId, input)` |

## Traps

**A workflow class cannot take constructor injection.** The SDK ships an analyzer,
DAPR1305, that fails the build for it. Activities may inject freely, which is where the
dependency belongs anyway — the workflow orchestrates, the activity talks to things.
Generating a workflow with an injected `HttpClient` is a build error, and generating one
with an injected repository would have been a determinism bug if it had compiled.

**`CreateTimer(DateTime)` has no default cancellation token.** `CreateTimer(fireAt)`
does not compile; `CreateTimer(TimeSpan)` does. Prefer the `TimeSpan` overload, which is
also what an ISO 8601 duration from the IR converts to directly.

**`WaitForExternalEventAsync` with a timeout throws on expiry.** It raises
`TaskCanceledException`, so the timeout branch of an event-or-timer wait is a `catch`,
not a return value. Catch that specific type — a bare `catch` swallows genuine activity
failures into the timeout path.

**Register explicitly.** 1.18 added source-generated auto-registration and a
parameterless `AddDaprWorkflow()`, and both work; every official sample still writes
`RegisterWorkflow<T>()` and `RegisterActivity<T>()`, and neither is obsolete. Explicit
registration is the form that reads correctly against every version the user might be
on.

## Serialization

System.Text.Json across every boundary. Records are ideal for the models generated from
`data_object` records. Keep the property names stable — renaming one after instances are
in flight breaks their replay just as surely as renaming an activity does.
