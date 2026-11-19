# .NET

NuGet `Dapr.Workflow`, `using Dapr.Workflow;`. This is the whole harness, exactly as it ran
against a Dapr 1.18.1 sidecar with `Dapr.Workflow` 1.18.5 on net8.0, through the same six
cases as the other languages. The model call is the harness's existing client behind a
one-method `IModel` interface; activities receive it, and the tool registry, by
constructor injection.

```csharp
using System.Text.Json;
using System.Text.Json.Serialization;
using Dapr.Workflow;

namespace Harness;

// ---------------------------------------------------------------------------
// Wire types. Assistant content is a JsonElement: the blocks exactly as the
// model API returned them, replayed unchanged on every later request. Property
// names are pinned, so they do not depend on the SDK serializer's policy.
// ---------------------------------------------------------------------------

public sealed record Message(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("content")] JsonElement Content); // a JSON string, or a block array

public sealed record ToolSpec(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("input_schema")] JsonElement InputSchema);

public sealed record ModelRequest(
    [property: JsonPropertyName("model")] string Model,
    [property: JsonPropertyName("max_tokens")] int MaxTokens,
    [property: JsonPropertyName("system")] string System,
    [property: JsonPropertyName("tools")] IReadOnlyList<ToolSpec> Tools,
    [property: JsonPropertyName("messages")] IReadOnlyList<Message> Messages);

public sealed record ModelError(
    [property: JsonPropertyName("status")] int Status,
    [property: JsonPropertyName("message")] string Message);

public sealed record ModelReply(
    [property: JsonPropertyName("content")] JsonElement? Content,
    [property: JsonPropertyName("stop_reason")] string? StopReason,
    [property: JsonPropertyName("error")] ModelError? Error = null);

public sealed record ToolUse(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("input")] JsonElement Input);

public sealed record ToolResult(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("tool_use_id")] string ToolUseId,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("is_error"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] bool IsError = false)
{
    public static ToolResult Ok(string id, string content) => new("tool_result", id, content);
    public static ToolResult Failed(string id, string content) => new("tool_result", id, content, true);
}

public sealed record ToolRequest(
    [property: JsonPropertyName("call")] ToolUse Call,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

// ---------------------------------------------------------------------------
// Process-local registry, through DI: the model client and the tool functions
// cannot cross a JSON boundary, so activities receive them by injection.
// Workflow classes cannot take constructor injection at all (DAPR1305).
// ---------------------------------------------------------------------------

// Your harness's existing client, behind one method. Throw ModelRejectedException
// for a permanent 4xx; let everything else - connection failures, timeouts, 408,
// 409, 429, 5xx - throw as-is so the workflow retries the call.
public interface IModel
{
    Task<ModelReply> CompleteAsync(ModelRequest request, CancellationToken cancellationToken);
}

public sealed class ModelRejectedException(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}

// Throw from an idempotent tool for a failure worth retrying: a timeout, a 503.
public sealed class RetryableToolException(string message) : Exception(message);

public sealed record Tool(
    ToolSpec Spec,
    Func<JsonElement, string, CancellationToken, Task<string>> RunAsync,
    bool NeedsApproval = false);

public sealed class ToolRegistry
{
    private readonly Dictionary<string, Tool> _tools = new();
    public void Add(Tool tool) => _tools[tool.Spec.Name] = tool;
    public bool TryGet(string name, out Tool tool) => _tools.TryGetValue(name, out tool!);
    public IEnumerable<Tool> All => _tools.Values.OrderBy(t => t.Spec.Name, StringComparer.Ordinal);
}

// ---------------------------------------------------------------------------
// Activities: everything that talks to the outside world.
// ---------------------------------------------------------------------------

public sealed record AgentConfig(
    [property: JsonPropertyName("request")] ModelRequest Request,
    [property: JsonPropertyName("needs_approval")] IReadOnlyList<string> NeedsApproval,
    [property: JsonPropertyName("max_turns")] int MaxTurns);

// Recorded once per run, so a redeploy changes new runs only.
internal sealed class LoadAgent(ToolRegistry tools) : WorkflowActivity<string, AgentConfig>
{
    public override Task<AgentConfig> RunAsync(WorkflowActivityContext context, string agentName) =>
        Task.FromResult(new AgentConfig(
            new ModelRequest(
                Model: "claude-opus-5-5",
                MaxTokens: 16000,
                System: "You are a concise assistant. Use the tools when they help.",
                Tools: tools.All.Select(t => t.Spec).ToList(),
                Messages: []),
            NeedsApproval: tools.All.Where(t => t.NeedsApproval).Select(t => t.Spec.Name).ToList(),
            MaxTurns: 20));
}

internal sealed class CallLlm(IModel model) : WorkflowActivity<ModelRequest, ModelReply>
{
    public override async Task<ModelReply> RunAsync(WorkflowActivityContext context, ModelRequest request)
    {
        try
        {
            return await model.CompleteAsync(request, CancellationToken.None);
        }
        catch (ModelRejectedException e) // the same request fails the same way
        {
            return new ModelReply(null, null, new ModelError(e.Status, e.Message));
        }
        // Anything else propagates: the call-site retry policy retries it.
    }
}

internal sealed class RunTool(ToolRegistry tools) : WorkflowActivity<ToolRequest, ToolResult>
{
    public override async Task<ToolResult> RunAsync(WorkflowActivityContext context, ToolRequest request)
    {
        var call = request.Call;
        if (!tools.TryGet(call.Name, out var tool)) // the model named a tool that does not exist
        {
            return ToolResult.Failed(call.Id, $"Unknown tool '{call.Name}'.");
        }
        try
        {
            return ToolResult.Ok(call.Id, await tool.RunAsync(call.Input, request.IdempotencyKey, CancellationToken.None));
        }
        catch (RetryableToolException)
        {
            throw; // the call-site retry policy retries it, durably
        }
        catch (Exception e) // the model sees the failure and can correct itself
        {
            return ToolResult.Failed(call.Id, $"{e.GetType().Name}: {e.Message}");
        }
    }
}

// ---------------------------------------------------------------------------
// The workflow: the loop itself. Deterministic - it decides, activities act.
// ---------------------------------------------------------------------------

public sealed record Run(
    [property: JsonPropertyName("task")] string Task,
    [property: JsonPropertyName("history")] IReadOnlyList<Message>? History = null);

public sealed record Result(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("messages")] IReadOnlyList<Message> Messages,
    [property: JsonPropertyName("content")] JsonElement? Content = null,
    [property: JsonPropertyName("error")] ModelError? Error = null);

internal sealed class AgentLoop : Workflow<Run, Result>
{
    private static readonly WorkflowTaskOptions LlmRetry = new(new WorkflowRetryPolicy(
        maxNumberOfAttempts: 6, firstRetryInterval: TimeSpan.FromSeconds(2),
        backoffCoefficient: 2.0, maxRetryInterval: TimeSpan.FromMinutes(1)));
    private static readonly WorkflowTaskOptions ToolRetry = new(new WorkflowRetryPolicy(
        maxNumberOfAttempts: 3, firstRetryInterval: TimeSpan.FromSeconds(1),
        backoffCoefficient: 2.0, maxRetryInterval: TimeSpan.FromSeconds(20)));
    private static readonly TimeSpan ApprovalTimeout = TimeSpan.FromHours(24);

    public override async Task<Result> RunAsync(WorkflowContext context, Run run)
    {
        var agent = await context.CallActivityAsync<AgentConfig>("load_agent", "default");
        // Earlier turns, verbatim, then the new user message: append-only, never rebuilt.
        var messages = new List<Message>(run.History ?? []) { new("user", JsonSerializer.SerializeToElement(run.Task)) };

        for (var turn = 0; turn < agent.MaxTurns; turn++)
        {
            var reply = await context.CallActivityAsync<ModelReply>(
                "call_llm", agent.Request with { Messages = messages }, LlmRetry);
            if (reply.Error is not null)
            {
                return new Result("rejected", messages, Error: reply.Error);
            }

            messages.Add(new Message("assistant", reply.Content!.Value));
            if (reply.StopReason == "pause_turn") continue; // a server tool paused the turn
            if (reply.StopReason != "tool_use") // end_turn, max_tokens, refusal: never run tools from these
            {
                return new Result(reply.StopReason == "end_turn" ? "completed" : reply.StopReason!, messages, reply.Content);
            }

            var calls = reply.Content!.Value.EnumerateArray()
                .Where(b => b.GetProperty("type").GetString() == "tool_use")
                .Select(b => b.Deserialize<ToolUse>()!)
                .ToList();
            var results = await RunToolsAsync(context, agent, calls);
            messages.Add(new Message("user", JsonSerializer.SerializeToElement(results))); // all results, one message
        }
        return new Result("max_turns", messages);
    }

    private static async Task<List<ToolResult>> RunToolsAsync(WorkflowContext context, AgentConfig agent, List<ToolUse> calls)
    {
        var results = new Dictionary<string, ToolResult>();
        foreach (var call in calls) // the model's order: deterministic
        {
            if (agent.NeedsApproval.Contains(call.Name) && !await WaitForApprovalAsync(context, call))
            {
                results[call.Id] = ToolResult.Failed(call.Id, "The user did not approve this call.");
            }
        }

        // ToList() schedules every call now, so they run in parallel. Without it the
        // LINQ query is lazy and each call would be scheduled only when awaited below.
        var scheduled = calls
            .Where(call => !results.ContainsKey(call.Id))
            .Select(call => (call, task: context.CallActivityAsync<ToolResult>(
                "run_tool", new ToolRequest(call, $"{context.InstanceId}:{call.Id}"), ToolRetry)))
            .ToList();
        // Awaiting each in turn keeps a failure local to its own call.
        foreach (var (call, task) in scheduled)
        {
            try
            {
                results[call.Id] = await task;
            }
            catch (WorkflowTaskFailedException e)
            {
                results[call.Id] = ToolResult.Failed(call.Id, $"Tool failed after retries: {e.FailureDetails.ErrorMessage}");
            }
        }
        return calls.Select(call => results[call.Id]).ToList(); // one result per tool_use, in order
    }

    private static async Task<bool> WaitForApprovalAsync(WorkflowContext context, ToolUse call)
    {
        context.SetCustomStatus(new Dictionary<string, string?> { ["awaiting_approval"] = call.Id, ["tool"] = call.Name });
        bool approved;
        try
        {
            var decision = await context.WaitForExternalEventAsync<JsonElement>($"approval:{call.Id}", ApprovalTimeout);
            approved = decision.TryGetProperty("approved", out var value) && value.GetBoolean();
        }
        catch (TaskCanceledException) // the timeout, and only the timeout
        {
            approved = false;
        }
        context.SetCustomStatus(new Dictionary<string, string?> { ["awaiting_approval"] = null });
        return approved;
    }
}

public sealed record Session(
    [property: JsonPropertyName("history")] IReadOnlyList<Message>? History = null,
    [property: JsonPropertyName("turn")] int Turn = 0);

internal sealed class AgentSession : Workflow<Session?, object?>
{
    public override async Task<object?> RunAsync(WorkflowContext context, Session? session)
    {
        session ??= new Session();
        var message = await context.WaitForExternalEventAsync<JsonElement>("user_message");
        var result = await context.CallChildWorkflowAsync<Result>(
            "agent_loop",
            new Run(message.GetProperty("text").GetString()!, session.History),
            new ChildWorkflowTaskOptions(InstanceId: $"{context.InstanceId}-turn-{session.Turn}"));
        // A message that arrived during this turn waits in the next one.
        context.ContinueAsNew(new Session(result.Messages, session.Turn + 1), preserveUnprocessedEvents: true);
        return null;
    }
}
```

The entry point is the generic host. `Dapr.Workflow` 1.18.5 already brings
`Microsoft.Extensions.Hosting` 10.x, so do not pin an older one next to it — the build
fails with a package-downgrade error.

```csharp
using Harness;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var tools = new ToolRegistry();
tools.Add(new Tool(weatherSpec, GetWeatherAsync));

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddSingleton<IModel, YourModel>(); // your harness's client
builder.Services.AddSingleton(tools);
builder.Services.AddDaprWorkflow(options =>
{
    options.RegisterWorkflow<AgentLoop>("agent_loop");
    options.RegisterWorkflow<AgentSession>("agent_session");
    options.RegisterActivity<LoadAgent>("load_agent");
    options.RegisterActivity<CallLlm>("call_llm");
    options.RegisterActivity<RunTool>("run_tool");
});
await builder.Build().RunAsync(); // a worker dials out and polls: no port, no HTTP server
```

The sidecar address and token come from the environment — `DAPR_GRPC_ENDPOINT` or
`DAPR_GRPC_PORT`, and `DAPR_API_TOKEN`, read by the Dapr client library the workflow client
builds on.

## Spelling

| Need | Spelling |
| --- | --- |
| Orchestrator | `class X : Workflow<TIn, TOut>`, override `RunAsync(WorkflowContext, TIn)` |
| Activity | `class Y : WorkflowActivity<TIn, TOut>`, override `RunAsync(WorkflowActivityContext, TIn)`; constructor injection is allowed here |
| Register | `options.RegisterWorkflow<X>("name")`, `options.RegisterActivity<Y>("name")` inside `AddDaprWorkflow` |
| Call an activity | `context.CallActivityAsync<T>("name", input, options)` |
| Retry | `new WorkflowTaskOptions(new WorkflowRetryPolicy(maxNumberOfAttempts:, firstRetryInterval:, backoffCoefficient:, maxRetryInterval:, retryTimeout:))` — no retry predicate |
| A failed activity, in the body | `WorkflowTaskFailedException`; `e.FailureDetails.ErrorMessage` holds the activity's error |
| External event | `context.WaitForExternalEventAsync<T>(name, TimeSpan timeout)` — a timeout throws `TaskCanceledException` |
| Custom status | `context.SetCustomStatus(object)` |
| Child workflow | `context.CallChildWorkflowAsync<T>("name", input, new ChildWorkflowTaskOptions(InstanceId: ...))` |
| Continue as new | `context.ContinueAsNew(newInput, preserveUnprocessedEvents: true)` |
| Instance id | `context.InstanceId`; the activity context has `InstanceId` too |
| Replay-safe now, replay-safe id | `context.CurrentUtcDateTime`, `context.NewGuid()` |

## Traps

**A workflow class cannot take constructor injection.** The SDK's analyzer, DAPR1305,
fails the build. That is why the model client and the tool registry reach the
*activities* through DI, and the workflow gets its configuration from `load_agent`.

**`ToList()` is what starts the calls.** A LINQ `Select` over
`context.CallActivityAsync(...)` is lazy: without the `ToList()` in `RunToolsAsync`, each
call would be scheduled only when the `foreach` reached it, one at a time, and the turn's
tools would run serially — with no error and no visible difference in the code's shape.

**Catch the exact exceptions.** `WorkflowTaskFailedException` around an activity await,
`TaskCanceledException` around an event wait with a timeout. A bare `catch` would turn a
genuine activity failure into a denied approval, or the reverse.

**`JsonElement` is the verbatim transcript.** It carries the model's content blocks
through every hop unchanged. Clone any `JsonElement` you parse yourself
(`JsonDocument.Parse(...).RootElement.Clone()`), because an element whose document has
been disposed is invalid.

**Pin the JSON names.** Every wire record here carries `[JsonPropertyName]`, so the
snake_case field names the model API expects do not depend on the serializer's naming
policy, and neither does replay if that policy ever changes.

**No retry predicate.** `WorkflowRetryPolicy` has none, so a permanent rejection must come
back as a value — `ModelReply.Error` — rather than an exception. Throwing it would spend
every retry on a request that cannot succeed.
