# Java

`io.dapr:dapr-sdk-workflows`, managed through the `io.dapr:dapr-sdk-bom`. Signatures
below were read from the SDK source at 1.18.1.

```java
import io.dapr.durabletask.Task;
import io.dapr.workflows.Workflow;
import io.dapr.workflows.WorkflowActivity;
import io.dapr.workflows.WorkflowActivityContext;
import io.dapr.workflows.WorkflowStub;
import java.time.Duration;
import java.util.List;

public class OrderFulfilment implements Workflow {
  @Override
  public WorkflowStub create() {
    return ctx -> {
      Order order = ctx.getInput(Order.class);

      boolean valid = ctx.callActivity(
          ValidateOrder.class.getName(), order, Boolean.class).await();
      if (!valid) {
        ctx.complete(new OrderResult("rejected"));
        return;
      }

      // implied parallel fan-out and join
      Task<Void> charge = ctx.callActivity(ChargeCard.class.getName(), order, Void.class);
      Task<Void> label = ctx.callActivity(PrintShippingLabel.class.getName(), order, Void.class);
      ctx.allOf(List.of(charge, label)).await();

      // wait_for_restock: message racing a P7D timer
      Task<RestockNotice> restocked =
          ctx.waitForExternalEvent("restocked", RestockNotice.class);
      Task<Void> deadline = ctx.createTimer(Duration.ofDays(7));
      Task<?> winner = ctx.anyOf(restocked, deadline).await();
      if (winner == deadline) {                       // restock_wait_expired
        ctx.callActivity(CancelOrder.class.getName(), order, Void.class).await();
        ctx.complete(new OrderResult("cancelled"));
        return;
      }

      ctx.complete(new OrderResult("shipped"));
    };
  }
}

public class ValidateOrder implements WorkflowActivity {
  @Override
  public Object run(WorkflowActivityContext ctx) {
    Order order = ctx.getInput(Order.class);
    return !order.getLines().isEmpty();
  }
}
```

| Need | Spelling |
| --- | --- |
| Orchestrator | `class X implements Workflow` — an **interface**, not a superclass — with `public WorkflowStub create()` returning a lambda over `ctx` |
| Returning output | `ctx.complete(obj)`. The `WorkflowStub` lambda is `void`; a `return` returns nothing |
| Activity | `class Y implements WorkflowActivity` with `public Object run(WorkflowActivityContext ctx)` |
| Call an activity | `ctx.callActivity(String name, Object input, WorkflowTaskOptions options, Class<V> returnType)`, plus five shorter overloads |
| Retry | `new WorkflowTaskOptions(WorkflowTaskRetryPolicy.newBuilder().setMaxNumberOfAttempts(n).setFirstRetryInterval(Duration).build())` — a builder, with no `new` on the policy |
| Timer | `ctx.createTimer(Duration)` or `ctx.createTimer(ZonedDateTime)`. There is **no `Instant` overload** |
| External event | `ctx.waitForExternalEvent(name, Duration, Class<V>)`, plus shorter overloads |
| Wait for all | `ctx.allOf(List<Task<V>>)` returning `Task<List<V>>` — an **instance method**, not static |
| Wait for first | `ctx.anyOf(Task<?>...)` or `ctx.anyOf(List<Task<?>>)` returning `Task<Task<?>>` |
| Child workflow | `ctx.callChildWorkflow(name, input, instanceId, options, Class<V>)`, plus shorter overloads |
| Await | `.await()` on the `Task` |
| Instance id | `ctx.getInstanceId()` |
| Replay-safe now | `ctx.getCurrentInstant()` |
| Replay-safe id | `ctx.newUuid()` |
| Logger | `ctx.getLogger()` |
| Register | `new WorkflowRuntimeBuilder().registerWorkflow(X.class).registerActivity(Y.class)`, then `WorkflowRuntime rt = builder.build(); rt.start();` |
| Start a run | `new DaprWorkflowClient().scheduleNewWorkflow(X.class, input)`, returning the instance id as a `String` |

Import surface: `io.dapr.workflows.{Workflow, WorkflowStub, WorkflowContext,
WorkflowActivity, WorkflowActivityContext, WorkflowTaskOptions,
WorkflowTaskRetryPolicy}`, `io.dapr.workflows.runtime.{WorkflowRuntime,
WorkflowRuntimeBuilder}`, `io.dapr.workflows.client.{DaprWorkflowClient, WorkflowState,
WorkflowRuntimeStatus}`.

## Traps

**`Task` comes from `io.dapr.durabletask`, not from `io.dapr.workflows`.** The SDK
vendors a fork of the durable-task client, so `io.dapr.durabletask.Task`,
`TaskFailedException`, `TaskCanceledException` and `CompositeTaskFailedException` are
the types to import. Before 1.14 they lived under `com.microsoft.durabletask`, which is
why older snippets do not compile.

**`TaskOrchestration`, `TaskActivity`, `TaskOrchestrationContext` and
`DurableTaskGrpcWorker` are not the authoring API.** They exist inside the SDK as
internal adapters. A workflow written against them will not compile against
`io.dapr.workflows`, and this is the single commonest wrong shape in circulating Java
Dapr Workflow examples.

**`ctx.callSubOrchestrator(...)` will not compile.** It is the private delegation
target of `callChildWorkflow`. Call `callChildWorkflow`.

**`start()` is on the runtime, not the builder.** `builder.build()` returns a
`WorkflowRuntime`, which is `AutoCloseable` and which you then `start()`.

**`ctx.getCurrentInstant()` does exist.** Some circulating guidance claims it does not
and steers people toward a wall clock instead, which is the exact determinism bug the
method exists to prevent.

## Serialization

Jackson, everywhere. Data classes need a **default constructor** and getters, or use
records, which Jackson has handled since 2.12 and which suit generated models well:

```java
public record RestockNotice(String sku, int quantity, String receivedAt) {}
```

What breaks: a class with only an all-args constructor, a lambda field, a circular
reference, a nested type that is not itself serializable. And client and worker must
use the same `DataConverter` — if one is customised, both are.
