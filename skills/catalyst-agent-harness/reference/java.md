# Java

`io.dapr:dapr-sdk-workflows`, managed through `io.dapr:dapr-sdk-bom`. This is the whole
harness, exactly as it ran against a Dapr 1.18.1 sidecar with the 1.18.1 SDK on Java 17,
through the same six cases as the other languages. The model call is the harness's
existing client behind a one-method `Model` interface, handed to the activity instance at
start-up.

```java
package harness;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.TextNode;
import io.dapr.durabletask.Task;
import io.dapr.durabletask.TaskCanceledException;
import io.dapr.durabletask.TaskFailedException;
import io.dapr.workflows.Workflow;
import io.dapr.workflows.WorkflowActivity;
import io.dapr.workflows.WorkflowActivityContext;
import io.dapr.workflows.WorkflowContext;
import io.dapr.workflows.WorkflowStub;
import io.dapr.workflows.WorkflowTaskOptions;
import io.dapr.workflows.WorkflowTaskRetryPolicy;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BiFunction;

public final class Agent {
  private Agent() {}

  // -------------------------------------------------------------------------
  // Wire types. Assistant content is a JsonNode: the blocks exactly as the model
  // API returned them, replayed unchanged on every later request.
  // -------------------------------------------------------------------------

  public record Message(@JsonProperty("role") String role, @JsonProperty("content") JsonNode content) {}

  public record ToolSpec(
      @JsonProperty("name") String name,
      @JsonProperty("description") String description,
      @JsonProperty("input_schema") JsonNode inputSchema) {}

  public record ModelRequest(
      @JsonProperty("model") String model,
      @JsonProperty("max_tokens") int maxTokens,
      @JsonProperty("system") String system,
      @JsonProperty("tools") List<ToolSpec> tools,
      @JsonProperty("messages") List<Message> messages) {
    ModelRequest withMessages(List<Message> m) {
      return new ModelRequest(model, maxTokens, system, tools, List.copyOf(m));
    }
  }

  public record ModelError(@JsonProperty("status") int status, @JsonProperty("message") String message) {}

  @JsonInclude(JsonInclude.Include.NON_NULL)
  public record ModelReply(
      @JsonProperty("content") JsonNode content,
      @JsonProperty("stop_reason") String stopReason,
      @JsonProperty("error") ModelError error) {}

  @JsonIgnoreProperties(ignoreUnknown = true)
  public record ToolUse(
      @JsonProperty("id") String id, @JsonProperty("name") String name, @JsonProperty("input") JsonNode input) {}

  @JsonInclude(JsonInclude.Include.NON_NULL)
  public record ToolResult(
      @JsonProperty("type") String type,
      @JsonProperty("tool_use_id") String toolUseId,
      @JsonProperty("content") String content,
      @JsonProperty("is_error") Boolean isError) {
    static ToolResult ok(String id, String content) {
      return new ToolResult("tool_result", id, content, null);
    }

    static ToolResult failed(String id, String content) {
      return new ToolResult("tool_result", id, content, true);
    }
  }

  public record ToolRequest(@JsonProperty("call") ToolUse call, @JsonProperty("idempotency_key") String idempotencyKey) {}

  // -------------------------------------------------------------------------
  // Process-local registry: the model client and the tool functions cannot
  // cross a JSON boundary, so they are handed to activity instances at start-up.
  // -------------------------------------------------------------------------

  /** Your harness's existing client, behind one method. */
  public interface Model {
    /**
     * Throw ModelRejectedException for a permanent 4xx; let everything else -
     * connection failures, timeouts, 408, 409, 429, 5xx - throw as-is so the
     * workflow retries the call.
     */
    ModelReply complete(ModelRequest request);
  }

  public static final class ModelRejectedException extends RuntimeException {
    final int status;

    public ModelRejectedException(int status, String message) {
      super(message);
      this.status = status;
    }
  }

  /** Throw from an idempotent tool for a failure worth retrying: a timeout, a 503. */
  public static final class RetryableToolException extends RuntimeException {
    public RetryableToolException(String message) {
      super(message);
    }
  }

  public record Tool(ToolSpec spec, BiFunction<JsonNode, String, String> run, boolean needsApproval) {}

  public static final class ToolRegistry {
    private final Map<String, Tool> tools = new HashMap<>();

    public ToolRegistry add(Tool tool) {
      tools.put(tool.spec().name(), tool);
      return this;
    }

    Tool get(String name) {
      return tools.get(name);
    }

    List<Tool> all() {
      return tools.values().stream().sorted(Comparator.comparing(t -> t.spec().name())).toList();
    }
  }

  // -------------------------------------------------------------------------
  // Activities: everything that talks to the outside world.
  // -------------------------------------------------------------------------

  public record AgentConfig(
      @JsonProperty("request") ModelRequest request,
      @JsonProperty("needs_approval") List<String> needsApproval,
      @JsonProperty("max_turns") int maxTurns) {}

  /** Recorded once per run, so a redeploy changes new runs only. */
  public record LoadAgent(ToolRegistry tools) implements WorkflowActivity {
    @Override
    public Object run(WorkflowActivityContext ctx) {
      return new AgentConfig(
          new ModelRequest("claude-opus-5-5", 16000, "You are a concise assistant. Use the tools when they help.",
              tools.all().stream().map(Tool::spec).toList(), List.of()),
          tools.all().stream().filter(Tool::needsApproval).map(t -> t.spec().name()).toList(),
          20);
    }
  }

  public record CallLlm(Model model) implements WorkflowActivity {
    @Override
    public Object run(WorkflowActivityContext ctx) {
      try {
        return model.complete(ctx.getInput(ModelRequest.class));
      } catch (ModelRejectedException e) { // the same request fails the same way
        return new ModelReply(null, null, new ModelError(e.status, e.getMessage()));
      }
      // Anything else propagates: the call-site retry policy retries it.
    }
  }

  public record RunTool(ToolRegistry tools) implements WorkflowActivity {
    @Override
    public Object run(WorkflowActivityContext ctx) {
      ToolRequest req = ctx.getInput(ToolRequest.class);
      Tool tool = tools.get(req.call().name());
      if (tool == null) { // the model named a tool that does not exist
        return ToolResult.failed(req.call().id(), "Unknown tool '" + req.call().name() + "'.");
      }
      try {
        return ToolResult.ok(req.call().id(), tool.run().apply(req.call().input(), req.idempotencyKey()));
      } catch (RetryableToolException e) {
        throw e; // the call-site retry policy retries it, durably
      } catch (RuntimeException e) { // the model sees the failure and can correct itself
        return ToolResult.failed(req.call().id(), e.getClass().getSimpleName() + ": " + e.getMessage());
      }
    }
  }

  // -------------------------------------------------------------------------
  // The workflow: the loop itself. Deterministic - it decides, activities act.
  // await() on a pending task throws OrchestratorBlockedException to unwind,
  // so around an await catch TaskFailedException only - never Exception.
  // -------------------------------------------------------------------------

  public record Run(@JsonProperty("task") String task, @JsonProperty("history") List<Message> history) {}

  @JsonInclude(JsonInclude.Include.NON_NULL)
  public record Result(
      @JsonProperty("status") String status,
      @JsonProperty("messages") List<Message> messages,
      @JsonProperty("content") JsonNode content,
      @JsonProperty("error") ModelError error) {}

  record ApprovalStatus(@JsonProperty("awaiting_approval") String awaitingApproval, @JsonProperty("tool") String tool) {}

  static final ObjectMapper JSON =
      new ObjectMapper().configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

  static WorkflowTaskOptions retry(int attempts, Duration first, Duration max) {
    return new WorkflowTaskOptions(WorkflowTaskRetryPolicy.newBuilder()
        .setMaxNumberOfAttempts(attempts)
        .setFirstRetryInterval(first)
        .setBackoffCoefficient(2.0)
        .setMaxRetryInterval(max)
        .build());
  }

  static final WorkflowTaskOptions LLM_RETRY = retry(6, Duration.ofSeconds(2), Duration.ofMinutes(1));
  static final WorkflowTaskOptions TOOL_RETRY = retry(3, Duration.ofSeconds(1), Duration.ofSeconds(20));
  static final Duration APPROVAL_TIMEOUT = Duration.ofHours(24);

  public static final class AgentLoop implements Workflow {
    @Override
    public WorkflowStub create() {
      return ctx -> {
        Run run = ctx.getInput(Run.class);
        AgentConfig agent = ctx.callActivity("load_agent", "default", AgentConfig.class).await();
        // Earlier turns, verbatim, then the new user message: append-only, never rebuilt.
        List<Message> messages = new ArrayList<>(run.history() == null ? List.of() : run.history());
        messages.add(new Message("user", TextNode.valueOf(run.task())));

        for (int turn = 0; turn < agent.maxTurns(); turn++) {
          ModelReply reply = ctx.callActivity(
              "call_llm", agent.request().withMessages(messages), LLM_RETRY, ModelReply.class).await();
          if (reply.error() != null) {
            ctx.complete(new Result("rejected", messages, null, reply.error()));
            return; // the stub is void: complete() is how a workflow returns its output
          }
          messages.add(new Message("assistant", reply.content()));
          if ("pause_turn".equals(reply.stopReason())) {
            continue; // a server tool paused the turn: send it back as-is
          }
          if (!"tool_use".equals(reply.stopReason())) { // end_turn, max_tokens, refusal
            String status = "end_turn".equals(reply.stopReason()) ? "completed" : reply.stopReason();
            ctx.complete(new Result(status, messages, reply.content(), null));
            return;
          }
          List<ToolUse> calls = new ArrayList<>();
          for (JsonNode block : reply.content()) {
            if ("tool_use".equals(block.path("type").asText())) {
              calls.add(JSON.convertValue(block, ToolUse.class));
            }
          }
          List<ToolResult> results = runTools(ctx, agent, calls);
          messages.add(new Message("user", JSON.valueToTree(results))); // all results, one message
        }
        ctx.complete(new Result("max_turns", messages, null, null));
      };
    }

    private static List<ToolResult> runTools(WorkflowContext ctx, AgentConfig agent, List<ToolUse> calls) {
      Map<String, ToolResult> results = new HashMap<>();
      for (ToolUse call : calls) { // the model's order: deterministic
        if (agent.needsApproval().contains(call.name()) && !waitForApproval(ctx, call)) {
          results.put(call.id(), ToolResult.failed(call.id(), "The user did not approve this call."));
        }
      }
      // Every call is scheduled here, so they run in parallel ...
      List<Map.Entry<ToolUse, Task<ToolResult>>> scheduled = new ArrayList<>();
      for (ToolUse call : calls) {
        if (!results.containsKey(call.id())) {
          ToolRequest in = new ToolRequest(call, ctx.getInstanceId() + ":" + call.id());
          scheduled.add(Map.entry(call, ctx.callActivity("run_tool", in, TOOL_RETRY, ToolResult.class)));
        }
      }
      // ... and awaiting each in turn keeps a failure local to its own call.
      for (Map.Entry<ToolUse, Task<ToolResult>> entry : scheduled) {
        String id = entry.getKey().id();
        try {
          results.put(id, entry.getValue().await());
        } catch (TaskFailedException e) {
          results.put(id, ToolResult.failed(id, "Tool failed after retries: " + e.getErrorDetails().getErrorMessage()));
        }
      }
      return calls.stream().map(call -> results.get(call.id())).toList(); // one per tool_use, in order
    }

    private static boolean waitForApproval(WorkflowContext ctx, ToolUse call) {
      ctx.setCustomStatus(new ApprovalStatus(call.id(), call.name()));
      boolean approved;
      try {
        JsonNode decision = ctx.waitForExternalEvent("approval:" + call.id(), APPROVAL_TIMEOUT, JsonNode.class).await();
        approved = decision != null && decision.path("approved").asBoolean(false);
      } catch (TaskCanceledException timeout) {
        approved = false;
      }
      ctx.setCustomStatus(new ApprovalStatus(null, null));
      return approved;
    }
  }

  public record Session(@JsonProperty("history") List<Message> history, @JsonProperty("turn") int turn) {}

  public static final class AgentSession implements Workflow {
    @Override
    public WorkflowStub create() {
      return ctx -> {
        Session session = ctx.getInput(Session.class);
        List<Message> history = session == null || session.history() == null ? List.of() : session.history();
        int turn = session == null ? 0 : session.turn();
        JsonNode message = ctx.waitForExternalEvent("user_message", JsonNode.class).await();
        Result result = ctx.callChildWorkflow(
            "agent_loop", new Run(message.path("text").asText(), history),
            ctx.getInstanceId() + "-turn-" + turn, Result.class).await();
        // true keeps unprocessed events: a message that arrived during this turn waits in the next one.
        ctx.continueAsNew(new Session(result.messages(), turn + 1), true);
      };
    }
  }
}
```

The entry point registers everything by explicit name and blocks:

```java
import io.dapr.workflows.runtime.WorkflowRuntime;
import io.dapr.workflows.runtime.WorkflowRuntimeBuilder;

public static void main(String[] args) {
  Agent.ToolRegistry tools = new Agent.ToolRegistry().add(new Agent.Tool(weatherSpec, Tools::getWeather, false));
  WorkflowRuntimeBuilder builder = new WorkflowRuntimeBuilder()
      .registerWorkflow("agent_loop", Agent.AgentLoop.class)
      .registerWorkflow("agent_session", Agent.AgentSession.class)
      .registerActivity("load_agent", new Agent.LoadAgent(tools))
      .registerActivity("call_llm", new Agent.CallLlm(yourModel)) // your harness's client
      .registerActivity("run_tool", new Agent.RunTool(tools));
  try (WorkflowRuntime runtime = builder.build()) {
    runtime.start(true); // blocks; a worker dials out and polls: no port, no HTTP server
  }
}
```

## Spelling

| Need | Spelling |
| --- | --- |
| Orchestrator | `class X implements Workflow` with `public WorkflowStub create()` returning a lambda over `ctx` |
| Returning output | `ctx.complete(result)`, then `return` — the stub lambda is `void` |
| Activity | `class Y implements WorkflowActivity` with `public Object run(WorkflowActivityContext ctx)` |
| Register | `registerWorkflow("name", X.class)`; `registerActivity("name", instance)` to hand an activity its dependencies |
| Call an activity | `ctx.callActivity("name", input, options, ReturnType.class).await()` |
| Retry | `new WorkflowTaskOptions(WorkflowTaskRetryPolicy.newBuilder().setMaxNumberOfAttempts(n).setFirstRetryInterval(d).setBackoffCoefficient(c).setMaxRetryInterval(d).build())` |
| Retry predicate | `new WorkflowTaskOptions(policy, handler)`, where a `WorkflowTaskRetryHandler` returns whether to keep retrying |
| A failed activity, in the body | `io.dapr.durabletask.TaskFailedException`; `e.getErrorDetails().getErrorMessage()` holds the activity's error |
| External event | `ctx.waitForExternalEvent(name, Duration, Type.class)` — a timeout throws `TaskCanceledException` at `await()` |
| Custom status | `ctx.setCustomStatus(object)` |
| Child workflow | `ctx.callChildWorkflow("name", input, instanceId, Type.class)` |
| Continue as new | `ctx.continueAsNew(input, true)` — `true` keeps messages that arrived mid-turn, and is also what the one-argument form defaults to |
| Instance id | `ctx.getInstanceId()`; the activity context has `getTaskExecutionId()` and no instance id |
| Replay-safe now, replay-safe id | `ctx.getCurrentInstant()`, `ctx.newUuid()` |

## Traps

**`await()` throws to unwind.** On a task that has not completed, `await()` throws
`OrchestratorBlockedException`, a `RuntimeException`, so the SDK can stop the lambda and
re-run it when the result arrives. The SDK's own documentation says orchestrator code must
never catch it. So around an `await()`, catch `TaskFailedException` and nothing broader —
a `catch (Exception e)` or `catch (RuntimeException e)` swallows the unwinding and breaks
the run.

**`TaskCanceledException` extends `TaskFailedException`.** An approval timeout is also a
task failure. Catch the narrower type first where the two mean different things.

**The first retry waits longer than the policy reads.** 1.18.1 computes each delay as
`firstRetryInterval × (long) pow(backoffCoefficient, attempt)` with the attempt already at
1 for the first retry. Measured: a 2-second first interval with a coefficient of 2.0
waited 4.1 seconds, where the other four SDKs waited 2.0. The `(long)` also truncates a
fractional coefficient — 1.5 rounds down to 1 for the first step — so use a whole-number
coefficient and set the first interval with the doubling in mind.

**Register by explicit name.** The default is the class's *canonical* name, and a nested
class's canonical name (`Agent.CallLlm`) differs from its `getName()` (`Agent$CallLlm`), so
a caller that builds the name from the class can miss the registration. One explicit
string on both sides avoids the question.

**The data converter is strict Jackson.** The SDK's mapper fails on unknown properties, so
every field on the wire must be declared on its record. The workflow's own `JSON` mapper
turns `FAIL_ON_UNKNOWN_PROPERTIES` off only to pick `tool_use` blocks out of the model's
content, whose other fields it does not model.

**`JsonNode` is the verbatim transcript.** It carries the model's content blocks through
every hop unchanged, and `withMessages` copies the list into the request so a later append
cannot reach an input that has already been scheduled.
