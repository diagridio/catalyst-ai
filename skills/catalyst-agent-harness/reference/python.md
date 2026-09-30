# Python

`dapr` and `dapr-ext-workflow`, with the model call made through the Anthropic SDK. This is
the whole harness, exactly as it ran: against a Dapr 1.18.1 sidecar, with
`dapr-ext-workflow` 1.18.3 and `anthropic` 1.9.0, through the kill test, a 429 retried by
the workflow, a 400 returned as a rejection, a tool that exhausted its retries, an
approval, and a two-message session.

Where the user's harness plugs in: their tools go in `TOOLS` through the `@tool`
decorator, their system prompt and request options in `load_agent`, and their model call
in `call_llm`. Everything else is the durable part and should survive the port unchanged.

```python
"""A hand-written agent loop, made durable with Dapr Workflows.

The loop is the workflow. Every model call is one activity and every tool call
is one activity, so a crash resumes at the unfinished step: turns the model has
already answered replay from history instead of being asked (and billed) again.
"""

import json
import threading
from datetime import timedelta

import anthropic
import dapr.ext.workflow as wf

wfr = wf.WorkflowRuntime()

# ---------------------------------------------------------------------------
# Process-local registry. Tool functions and the model client cannot cross a
# JSON boundary, so they stay here and activities look them up by name. The
# workflow only ever handles names and plain data.
# ---------------------------------------------------------------------------

TOOLS = {}  # name -> (spec sent to the model, function, needs_approval)


def tool(name, description, input_schema, *, needs_approval=False):
    def register(fn):
        spec = {"name": name, "description": description, "input_schema": input_schema}
        TOOLS[name] = (spec, fn, needs_approval)
        return fn

    return register


class RetryableToolError(Exception):
    """Raise from an idempotent tool for a failure worth retrying: a timeout, a 503."""


@tool(
    "get_weather",
    "Current weather for a city.",
    {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)
def get_weather(args, idempotency_key):
    return f"Sunny and 21C in {args['city']}."


@tool(
    "send_email",
    "Send an email to one recipient.",
    {
        "type": "object",
        "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
        "required": ["to", "body"],
    },
    needs_approval=True,
)
def send_email(args, idempotency_key):
    # A side effect. The key is the same on every retry and every replay of this
    # one call, so pass it to the provider as its idempotency key.
    return f"Sent to {args['to']} (idempotency key {idempotency_key})."


SYSTEM_PROMPT = "You are a concise assistant. Use the tools when they help."

_client = None


def llm():
    global _client
    if _client is None:
        # The workflow's retry policy owns retries, so every attempt is durable
        # and visible in the run history. The SDK's own retries (2 by default)
        # would multiply with it, invisibly.
        _client = anthropic.Anthropic(max_retries=0)
    return _client


# ---------------------------------------------------------------------------
# Activities: everything that talks to the outside world.
# ---------------------------------------------------------------------------


@wfr.activity(name="load_agent")
def load_agent(ctx: wf.WorkflowActivityContext, agent_name: str) -> dict:
    # Recorded once per run: a redeploy with a new prompt or tool set changes new
    # runs only, and every in-flight run keeps the configuration it started with.
    return {
        "request": {
            "model": "claude-opus-5-5",
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": [spec for spec, _, _ in TOOLS.values()],
        },
        "needs_approval": sorted(n for n, (_, _, gated) in TOOLS.items() if gated),
        "max_turns": 20,
    }


@wfr.activity(name="call_llm")
def call_llm(ctx: wf.WorkflowActivityContext, req: dict) -> dict:
    try:
        response = llm().messages.create(**req)
    except anthropic.APIConnectionError:
        raise  # network failure or timeout: let the retry policy retry it
    except anthropic.APIStatusError as e:
        if e.status_code in (408, 409, 429) or e.status_code >= 500:
            raise  # rate limit, overload, outage: retry
        # 400, 401, 403, 404, 413: the same request fails the same way. Return it.
        return {"error": {"status": e.status_code, "message": str(e.message)}}
    return {
        # Exactly the blocks the API sent, thinking blocks and signatures
        # included, so the next request replays this turn unchanged.
        "content": [block.to_dict(mode="json") for block in response.content],
        "stop_reason": response.stop_reason,
        "usage": response.usage.to_dict(mode="json"),
    }


@wfr.activity(name="run_tool")
def run_tool(ctx: wf.WorkflowActivityContext, req: dict) -> dict:
    call = req["call"]
    entry = TOOLS.get(call["name"])
    if entry is None:  # the model named a tool that does not exist
        return tool_result(call["id"], f"Unknown tool {call['name']!r}.", error=True)
    _, fn, _ = entry
    try:
        return tool_result(call["id"], fn(call["input"], req["idempotency_key"]))
    except RetryableToolError:
        raise  # the call-site retry policy retries it, durably
    except Exception as e:  # the model sees the failure and can correct itself
        return tool_result(call["id"], f"{type(e).__name__}: {e}", error=True)


def tool_result(tool_use_id, content, error=False):
    result = {"type": "tool_result", "tool_use_id": tool_use_id, "content": str(content)}
    if error:
        result["is_error"] = True
    return result


# ---------------------------------------------------------------------------
# The workflow: the loop itself. Deterministic - it decides, activities act.
# ---------------------------------------------------------------------------

LLM_RETRY = wf.RetryPolicy(
    first_retry_interval=timedelta(seconds=2),
    max_number_of_attempts=6,
    backoff_coefficient=2.0,
    max_retry_interval=timedelta(minutes=1),
)
TOOL_RETRY = wf.RetryPolicy(
    first_retry_interval=timedelta(seconds=1),
    max_number_of_attempts=3,
    backoff_coefficient=2.0,
    max_retry_interval=timedelta(seconds=20),
)
APPROVAL_TIMEOUT = timedelta(hours=24)


@wfr.workflow(name="agent_loop")
def agent_loop(ctx: wf.DaprWorkflowContext, run: dict):
    agent = yield ctx.call_activity(load_agent, input=run.get("agent", "default"))
    # Earlier turns, verbatim, then the new user message: append-only, never rebuilt.
    messages = [*run.get("history", []), {"role": "user", "content": run["task"]}]

    for turn in range(agent["max_turns"]):
        reply = yield ctx.call_activity(
            call_llm,
            input={**agent["request"], "messages": messages},
            retry_policy=LLM_RETRY,
        )
        if "error" in reply:
            return {"status": "rejected", "error": reply["error"], "messages": messages}

        messages.append({"role": "assistant", "content": reply["content"]})
        stop = reply["stop_reason"]
        if stop == "pause_turn":  # a server tool paused the turn: send it back as-is
            continue
        if stop != "tool_use":  # end_turn, max_tokens, refusal: never run tools from these
            status = "completed" if stop == "end_turn" else stop
            return {"status": status, "content": reply["content"], "messages": messages}

        calls = [block for block in reply["content"] if block["type"] == "tool_use"]
        results = yield from run_tools(ctx, agent, calls)
        messages.append({"role": "user", "content": results})  # all results, one message

    return {"status": "max_turns", "messages": messages}


def run_tools(ctx, agent, calls):
    results = {}
    for call in calls:  # the model's order, so approvals are asked deterministically
        if call["name"] in agent["needs_approval"]:
            approved = yield from wait_for_approval(ctx, call)
            if not approved:
                results[call["id"]] = tool_result(
                    call["id"], "The user did not approve this call.", error=True
                )

    pending = [
        (
            call,
            ctx.call_activity(
                run_tool,
                input={"call": call, "idempotency_key": f"{ctx.instance_id}:{call['id']}"},
                retry_policy=TOOL_RETRY,
            ),
        )
        for call in calls
        if call["id"] not in results
    ]
    # Every call was scheduled above, so they run in parallel. Awaiting them one
    # at a time keeps a failure local: one tool that exhausts its retries becomes
    # an error result instead of discarding the results of the others.
    for call, task in pending:
        try:
            results[call["id"]] = yield task
        except wf.TaskFailedError as e:
            results[call["id"]] = tool_result(
                call["id"], f"Tool failed after retries: {e.details.message}", error=True
            )
    return [results[call["id"]] for call in calls]  # one result per tool_use, in order


def wait_for_approval(ctx, call):
    # Custom status mirrors what is pending, but over MCP it is withheld at the default
    # data-sharing level, so a real deployment also notifies someone - from an activity,
    # never from here.
    ctx.set_custom_status(json.dumps({"awaiting_approval": call["id"], "tool": call["name"]}))
    decision = ctx.wait_for_external_event(f"approval:{call['id']}")
    timeout = ctx.create_timer(APPROVAL_TIMEOUT)
    winner = yield wf.when_any([decision, timeout])
    ctx.set_custom_status(json.dumps({"awaiting_approval": None}))
    if winner is timeout:
        return False
    return bool((decision.get_result() or {}).get("approved"))


@wfr.workflow(name="agent_session")
def agent_session(ctx: wf.DaprWorkflowContext, session: dict):
    # One instance per conversation. Each user message arrives as an event and runs
    # as its own child agent_loop; then the session continues as new carrying only
    # the transcript, so its own history never grows past a single turn.
    message = yield ctx.wait_for_external_event("user_message")
    turn = session.get("turn", 0)
    result = yield ctx.call_child_workflow(
        agent_loop,
        input={"task": message["text"], "history": session.get("history", [])},
        instance_id=f"{ctx.instance_id}-turn-{turn}",
    )
    # save_events: a message that arrived during this turn waits in the next one.
    ctx.continue_as_new({"history": result["messages"], "turn": turn + 1}, save_events=True)


def main():
    # A worker dials the sidecar and polls for work: no port, no HTTP server.
    wfr.start()
    try:
        threading.Event().wait()
    finally:
        wfr.shutdown()


if __name__ == "__main__":
    main()
```

Run it as section 12 of the skill says, with the app's connection values from
`catalyst_get_app_connection` in the worker's environment, and start a run of `agent_loop`
with a `{"task": "..."}` input. For a conversation, start
`agent_session` once with `{}` and raise one `user_message` event, carrying
`{"text": "..."}`, per message.

## Spelling

| Need | Spelling |
| --- | --- |
| Orchestrator | `@wfr.workflow(name=...)` on a **generator** function taking `(ctx, input)` |
| Activity | `@wfr.activity(name=...)` on a function taking `(ctx, input)` |
| Call an activity | `ctx.call_activity(fn_or_name, input=..., retry_policy=...)` — keyword-only after the first argument |
| Retry | `wf.RetryPolicy(first_retry_interval=, max_number_of_attempts=, backoff_coefficient=, max_retry_interval=, retry_timeout=)` |
| A failed activity, in the body | `wf.TaskFailedError`, raised at the `yield`; `e.details.message` holds the activity's error |
| Timer | `ctx.create_timer(timedelta(...))` |
| External event | `ctx.wait_for_external_event(name)`. 1.18.3 also takes `timeout=` and raises `TimeoutError`; the `when_any` race above works on older versions too |
| First to finish | `wf.when_any([...])` — module-level, and it returns the winning task, so compare with `is` |
| Custom status | `ctx.set_custom_status(str)` |
| Child workflow | `ctx.call_child_workflow(fn_or_name, input=, instance_id=)` |
| Continue as new | `ctx.continue_as_new(new_input, save_events=True)` — `save_events` keeps messages that arrived mid-turn |
| Delegate a helper that awaits | `yield from helper(ctx, ...)`, where the helper is itself a generator |
| Instance id | `ctx.instance_id`. The activity context has `ctx.workflow_id` and `ctx.task_id`, and no `instance_id` |
| Start a run from code | `wf.DaprWorkflowClient().schedule_new_workflow("agent_loop", input={...}, instance_id=...)` |
| Send an approval from code | `wf.DaprWorkflowClient().raise_workflow_event(instance_id, "approval:<tool-call-id>", data={"approved": True})` |

## Traps

**Every await is a `yield`.** A `ctx.call_activity` whose task is never yielded is a task
object, which is truthy — so a branch on it takes the same path every time, silently.

**Store blocks with `to_dict(mode="json")`.** It returns exactly what the API sent, with
fields the API omitted left out, which is the same shape the SDK sends when you append
`response.content` directly. `model_dump()` without `exclude_unset` adds fields the API
never sent, such as `caller` and `toolset_name` on a tool-use block — that is a rewrite of
the turn, not a replay of it.

**`max_retries=0` on the client, not a `with_options` per call.** The client is built once
per process, in the registry, and every activity reuses it. Leaving the SDK default of 2
retries in place multiplies with the workflow's 6 attempts into as many as 18 requests,
of which history shows 6.

**Classify by status code.** `anthropic.RetryableError` is a class your own middleware
raises to opt a request into the SDK's retries, not a base class of the transient errors.
The test that matches the SDK's own retry rule is the one in `call_llm`: `APIConnectionError`
(which includes `APITimeoutError`), or an `APIStatusError` with status 408, 409, 429 or
anything from 500 up, which covers 529 overload.

**Keep request options in `load_agent`.** Thinking, effort, prompt caching, a server-side
refusal fallback — whatever the harness already sends goes into `request` there, so it is
pinned per run and replayed with the transcript it belongs to. Read nothing from the
environment in the body; read the API key in the activity, where the client is built.

**An exhausted retry reaches the body as `wf.TaskFailedError`.** Catch that type around
the `yield`, not `Exception`, so a real bug in the body still fails the run loudly.

**Custom status is a string.** `set_custom_status` takes `str`; serialize a dict yourself,
as `wait_for_approval` does.

## MCP tools

An MCP tool is a tool: call your MCP client inside `run_tool`, like any other. On Dapr
1.18, `dapr-ext-workflow` 1.18.3 also ships `DaprMCPClient`, which lists the tools of an
MCP server the app loads and names a built-in workflow per tool,
`dapr.internal.mcp.<server>.CallTool.<tool>`. The Dapr Agents framework calls that as a
child workflow with the input `{"arguments": {...}}`, which makes every MCP call its own
durable step. That shape is read from the SDK and framework source; it was not run here,
so confirm one call against your project before building on it.
