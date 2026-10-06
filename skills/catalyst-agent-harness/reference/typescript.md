# TypeScript and JavaScript

Everything comes from `@dapr/dapr`. This is the whole harness, exactly as it ran against
a Dapr 1.18.1 sidecar with `@dapr/dapr` 3.18.0, through the same six cases as the other
languages. The model call is the harness's existing client behind a one-method `Model`
interface: set `registry.model` and register tools with `tool(...)` before calling
`startWorker()`.

```ts
import {
  TWorkflow,
  WorkflowActivityContext,
  WorkflowContext,
  WorkflowRuntime,
} from "@dapr/dapr";

// ---------------------------------------------------------------------------
// Process-local registry: the model client and the tool functions cannot cross
// a JSON boundary, so they stay here and activities look them up by name.
// ---------------------------------------------------------------------------

type Block = { type: string; [key: string]: unknown };
type ToolUse = { type: "tool_use"; id: string; name: string; input: Record<string, unknown> };
type Message = { role: "user" | "assistant"; content: string | Block[] };
type ToolSpec = { name: string; description: string; input_schema: object };

export type ModelRequest = {
  model: string;
  max_tokens: number;
  system: string;
  tools: ToolSpec[];
  messages: Message[];
};
export type ModelReply = { content: Block[]; stop_reason: string; usage?: object };

// Your harness's existing model call, behind one method. Throw ModelRejected for
// a permanent 4xx; let everything else (connection errors, timeouts, 408, 409,
// 429, 5xx) throw as-is so the workflow retries it.
export interface Model {
  complete(req: ModelRequest): Promise<ModelReply>;
}
export class ModelRejected extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}
export class RetryableToolError extends Error {}

type ToolFn = (args: Record<string, unknown>, idempotencyKey: string) => Promise<string> | string;
export const TOOLS = new Map<string, { spec: ToolSpec; fn: ToolFn; needsApproval: boolean }>();
export const registry: { model?: Model } = {};

export function tool(spec: ToolSpec, fn: ToolFn, needsApproval = false) {
  TOOLS.set(spec.name, { spec, fn, needsApproval });
}

tool(
  {
    name: "get_weather",
    description: "Current weather for a city.",
    input_schema: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
  },
  (args) => `Sunny and 21C in ${args.city}.`,
);

// ---------------------------------------------------------------------------
// Activities: everything that talks to the outside world.
// ---------------------------------------------------------------------------

type Agent = { request: Omit<ModelRequest, "messages">; needsApproval: string[]; maxTurns: number };

// Recorded once per run, so a redeploy changes new runs only.
const loadAgent = async (_ctx: WorkflowActivityContext, _name: string): Promise<Agent> => ({
  request: {
    model: "claude-opus-5-5",
    max_tokens: 16000,
    system: "You are a concise assistant. Use the tools when they help.",
    tools: [...TOOLS.values()].map((t) => t.spec),
  },
  needsApproval: [...TOOLS.values()].filter((t) => t.needsApproval).map((t) => t.spec.name).sort(),
  maxTurns: 20,
});

const callLlm = async (_ctx: WorkflowActivityContext, req: ModelRequest) => {
  try {
    return await registry.model!.complete(req);
  } catch (e) {
    if (e instanceof ModelRejected) return { error: { status: e.status, message: e.message } };
    throw e; // transient: the workflow retries it
  }
};

const runTool = async (_ctx: WorkflowActivityContext, req: { call: ToolUse; idempotencyKey: string }) => {
  const entry = TOOLS.get(req.call.name);
  if (!entry) return toolResult(req.call.id, `Unknown tool '${req.call.name}'.`, true);
  try {
    return toolResult(req.call.id, await entry.fn(req.call.input, req.idempotencyKey));
  } catch (e) {
    if (e instanceof RetryableToolError) throw e; // the workflow retries it
    return toolResult(req.call.id, `${(e as Error).name}: ${(e as Error).message}`, true);
  }
};

function toolResult(toolUseId: string, content: string, isError = false): Block {
  return { type: "tool_result", tool_use_id: toolUseId, content, ...(isError ? { is_error: true } : {}) };
}

// ---------------------------------------------------------------------------
// The workflow. Every orchestrator is `async function*` - a plain `function*`
// completes immediately without running a single activity. Activities and child
// workflows are called by the same string they were registered under: a
// function reference resolves to `fn.name` ("loadAgent"), which is not the
// registered name ("load_agent").
// ---------------------------------------------------------------------------

type Retry = { attempts: number; firstDelayMs: number; maxDelayMs: number };
const LLM_RETRY: Retry = { attempts: 6, firstDelayMs: 2_000, maxDelayMs: 60_000 };
const TOOL_RETRY: Retry = { attempts: 3, firstDelayMs: 1_000, maxDelayMs: 20_000 };
const APPROVAL_TIMEOUT_MS = 24 * 60 * 60 * 1000;

// callActivity has no retry policy in JavaScript, so retries are workflow code:
// a durable timer between attempts, with the delay taken from the replay-safe
// clock. `first` is already scheduled, which lets first attempts run in parallel.
async function* awaitWithRetry(ctx: WorkflowContext, first: any, activity: string, input: unknown, retry: Retry): any {
  let lastError: unknown;
  for (let attempt = 1; attempt <= retry.attempts; attempt++) {
    try {
      return yield attempt === 1 ? first : ctx.callActivity(activity, input);
    } catch (e) {
      lastError = e;
      if (attempt === retry.attempts) break;
      const delay = Math.min(retry.firstDelayMs * 2 ** (attempt - 1), retry.maxDelayMs);
      yield ctx.createTimer(new Date(ctx.getCurrentUtcDateTime().getTime() + delay));
    }
  }
  throw lastError;
}

export const agentLoop: TWorkflow = async function* (ctx: WorkflowContext, run: any): any {
  const agent: Agent = yield ctx.callActivity("load_agent", run.agent ?? "default");
  // Earlier turns, verbatim, then the new user message: append-only, never rebuilt.
  const messages: Message[] = [...(run.history ?? []), { role: "user", content: run.task }];

  for (let turn = 0; turn < agent.maxTurns; turn++) {
    const req = { ...agent.request, messages };
    const reply = yield* awaitWithRetry(ctx, ctx.callActivity("call_llm", req), "call_llm", req, LLM_RETRY);
    if (reply.error) return { status: "rejected", error: reply.error, messages };

    messages.push({ role: "assistant", content: reply.content });
    if (reply.stop_reason === "pause_turn") continue; // a server tool paused the turn
    if (reply.stop_reason !== "tool_use") {
      const status = reply.stop_reason === "end_turn" ? "completed" : reply.stop_reason;
      return { status, content: reply.content, messages };
    }

    const calls = (reply.content as Block[]).filter((b): b is ToolUse => b.type === "tool_use");
    const results = yield* runTools(ctx, agent, calls);
    messages.push({ role: "user", content: results }); // all results, one message
  }
  return { status: "max_turns", messages };
};

async function* runTools(ctx: WorkflowContext, agent: Agent, calls: ToolUse[]): any {
  const results = new Map<string, Block>();
  for (const call of calls) {
    if (agent.needsApproval.includes(call.name) && !(yield* waitForApproval(ctx, call))) {
      results.set(call.id, toolResult(call.id, "The user did not approve this call.", true));
    }
  }

  const pending = calls
    .filter((call) => !results.has(call.id))
    .map((call) => {
      const input = { call, idempotencyKey: `${ctx.getWorkflowInstanceId()}:${call.id}` };
      return { call, input, first: ctx.callActivity("run_tool", input) };
    });
  // All first attempts are scheduled above and run in parallel. Awaiting them
  // one at a time keeps a failure local to its own call.
  for (const { call, input, first } of pending) {
    try {
      results.set(call.id, yield* awaitWithRetry(ctx, first, "run_tool", input, TOOL_RETRY));
    } catch (e) {
      results.set(call.id, toolResult(call.id, `Tool failed after retries: ${(e as Error).message}`, true));
    }
  }
  return calls.map((call) => results.get(call.id)!); // one result per tool_use, in order
}

async function* waitForApproval(ctx: WorkflowContext, call: ToolUse): any {
  ctx.setCustomStatus(JSON.stringify({ awaiting_approval: call.id, tool: call.name }));
  const decision = ctx.waitForExternalEvent(`approval:${call.id}`);
  const timeout = ctx.createTimer(new Date(ctx.getCurrentUtcDateTime().getTime() + APPROVAL_TIMEOUT_MS));
  const winner = yield ctx.whenAny([decision, timeout]);
  ctx.setCustomStatus(JSON.stringify({ awaiting_approval: null }));
  return winner !== timeout && Boolean(decision.getResult()?.approved);
}

export const agentSession: TWorkflow = async function* (ctx: WorkflowContext, session: any): any {
  const message = yield ctx.waitForExternalEvent("user_message");
  const turn = session?.turn ?? 0;
  const result = yield ctx.callChildWorkflow(
    "agent_loop",
    { task: message.text, history: session?.history ?? [] },
    `${ctx.getWorkflowInstanceId()}-turn-${turn}`,
  );
  // saveEvents: a message that arrived during this turn waits in the next one.
  ctx.continueAsNew({ history: result.messages, turn: turn + 1 }, true);
};

export async function startWorker(): Promise<WorkflowRuntime> {
  // Reads DAPR_GRPC_ENDPOINT and DAPR_API_TOKEN from the environment. A worker
  // dials the sidecar and polls for work: no port, no HTTP server.
  const runtime = new WorkflowRuntime()
    .registerWorkflowWithName("agent_loop", agentLoop)
    .registerWorkflowWithName("agent_session", agentSession)
    .registerActivityWithName("load_agent", loadAgent)
    .registerActivityWithName("call_llm", callLlm)
    .registerActivityWithName("run_tool", runTool);
  await runtime.start();
  return runtime;
}
```

The entry point is two lines: `registry.model = yourModel;` then `await startWorker();`.
The runtime keeps the process alive; it needs no HTTP server.

## Spelling

| Need | Spelling |
| --- | --- |
| Orchestrator | `const wf: TWorkflow = async function* (ctx, input): any { ... }` |
| Activity | `async (ctx: WorkflowActivityContext, input) => output` |
| Register | `new WorkflowRuntime().registerWorkflowWithName(name, wf).registerActivityWithName(name, fn)`, then `await runtime.start()` |
| Call an activity | `ctx.callActivity("name", input)` — that is the whole signature |
| Retry | **none** — `awaitWithRetry` above, a durable timer between attempts |
| Delegate a helper that awaits | `yield* helper(ctx, ...)`, where the helper is itself an `async function*` |
| Timer | `ctx.createTimer(fireAt: Date)`, or a bare number meaning **seconds** |
| External event | `ctx.waitForExternalEvent(name)` — no timeout parameter; race it with `ctx.whenAny([event, timer])` |
| Event payload | `task.getResult()` once the task has won |
| Custom status | `ctx.setCustomStatus(string)` |
| Child workflow | `ctx.callChildWorkflow("name", input, instanceId)` |
| Continue as new | `ctx.continueAsNew(newInput, true)` — the second argument keeps messages that arrived mid-turn, and has no default |
| Instance id | `ctx.getWorkflowInstanceId()` — a method, like every context accessor |
| Replay-safe now | `ctx.getCurrentUtcDateTime()` |
| Start a run from code | `new DaprWorkflowClient().scheduleNewWorkflow("agent_loop", input, instanceId)` |
| Send an approval from code | `new DaprWorkflowClient().raiseEvent(instanceId, "approval:<tool-call-id>", { approved: true })` |

`WorkflowRuntime` and `DaprWorkflowClient` read `DAPR_GRPC_ENDPOINT` (or
`DAPR_GRPC_PORT`) and `DAPR_API_TOKEN` from the environment when given no options.
`dapr run` sets the port for the process it launches; a remote sidecar, Catalyst's
included, needs the endpoint and token set explicitly.

## Traps

**Every orchestrator is `async function*`.** The executor checks for
`Symbol.asyncIterator`. A plain `function*` has none, so its generator object is
serialized as the output and the run is marked COMPLETED without one activity having run
— a green run that did nothing.

**Call by the registered string, never by function reference.** `ctx.callActivity(fn)`
resolves the name from `fn.name`. A `const loadAgent = async (...) => ...` registered with
`registerActivityWithName("load_agent", loadAgent)` is called as `"loadAgent"`, which is
registered nowhere. Registering and calling by one string removes the mismatch and makes
the wire names visible.

**Retries are workflow code.** `callActivity` takes no options. `awaitWithRetry` takes the
already-scheduled first attempt, so every tool's first attempt runs in parallel; retries,
which are rare, run one call at a time. The delay comes from `getCurrentUtcDateTime()`
and the attempt number, both replay-safe. Measured: a 429 on the first model call was
retried 2.0 seconds later, the configured first delay.

**Throw from the activity for a retry, return for everything else.** A thrown error
reaches the workflow as an exception at the `yield`; its message is the activity's
message prefixed with the instance and task, so pass `e.message` on to the model rather
than parsing it.

**`instanceof` works for the classification** because the activity runs in the same
process that defined `ModelRejected` and `RetryableToolError`. Across the workflow
boundary only the message survives — which is why the classification happens inside the
activity, never in the body.

**Every context accessor is a method.** TypeScript rejects `ctx.instanceId`; plain
JavaScript returns `undefined`, silently, and an idempotency key built from it is the
string `"undefined"`.
