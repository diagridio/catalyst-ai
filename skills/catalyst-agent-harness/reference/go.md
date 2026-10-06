# Go

Authoring is `github.com/dapr/durabletask-go/workflow`; the worker connection comes from
`github.com/dapr/go-sdk/client`. This is the whole harness, exactly as it ran against a
Dapr 1.18.1 sidecar with durabletask-go v0.14.0 and go-sdk v1.15.0, through the same six
cases as the other languages. Both modules need Go 1.26 — go-sdk v1.15.0 declares 1.26.4. The model call is the harness's
existing client behind a one-method `Model` interface.

```go
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"time"

	"github.com/dapr/durabletask-go/workflow"
)

// ---------------------------------------------------------------------------
// Wire types. Assistant content is json.RawMessage: the blocks exactly as the
// model API returned them, replayed unchanged on every later request.
// ---------------------------------------------------------------------------

type Message struct {
	Role    string          `json:"role"`
	Content json.RawMessage `json:"content"` // a JSON string, or a block array
}

type ToolSpec struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"input_schema"`
}

type ModelRequest struct {
	Model     string     `json:"model"`
	MaxTokens int        `json:"max_tokens"`
	System    string     `json:"system"`
	Tools     []ToolSpec `json:"tools"`
	Messages  []Message  `json:"messages"`
}

type ModelReply struct {
	Content    json.RawMessage `json:"content,omitempty"`
	StopReason string          `json:"stop_reason,omitempty"`
	Error      *ModelRejected  `json:"error,omitempty"`
}

type ToolUse struct {
	Type  string          `json:"type"`
	ID    string          `json:"id"`
	Name  string          `json:"name"`
	Input json.RawMessage `json:"input"`
}

type ToolResult struct {
	Type      string `json:"type"`
	ToolUseID string `json:"tool_use_id"`
	Content   string `json:"content"`
	IsError   bool   `json:"is_error,omitempty"`
}

type ToolRequest struct {
	Call           ToolUse `json:"call"`
	IdempotencyKey string  `json:"idempotency_key"`
}

// ---------------------------------------------------------------------------
// Process-local registry: the model client and tool functions cannot cross a
// JSON boundary, so they stay here and activities look them up by name.
// ---------------------------------------------------------------------------

// Model is your harness's existing client, behind one method. Return a
// *ModelRejected for a permanent 4xx; return any other error - connection
// failures, timeouts, 408, 409, 429, 5xx - to have the workflow retry the call.
type Model interface {
	Complete(ctx context.Context, req ModelRequest) (ModelReply, error)
}

type ModelRejected struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
}

func (e *ModelRejected) Error() string { return fmt.Sprintf("model rejected the request (%d): %s", e.Status, e.Message) }

// RetryableToolError marks a failure worth retrying in an idempotent tool.
type RetryableToolError struct{ Err error }

func (e RetryableToolError) Error() string { return e.Err.Error() }

type Tool struct {
	Spec          ToolSpec
	Run           func(ctx context.Context, input json.RawMessage, idempotencyKey string) (string, error)
	NeedsApproval bool
}

var (
	model Model
	tools = map[string]Tool{}
)

// ---------------------------------------------------------------------------
// Activities: everything that talks to the outside world.
// ---------------------------------------------------------------------------

type Agent struct {
	Request       ModelRequest `json:"request"`
	NeedsApproval []string     `json:"needs_approval"`
	MaxTurns      int          `json:"max_turns"`
}

// LoadAgent is recorded once per run, so a redeploy changes new runs only.
func LoadAgent(ctx workflow.ActivityContext) (any, error) {
	agent := Agent{
		Request: ModelRequest{
			Model:     "claude-opus-5-5",
			MaxTokens: 16000,
			System:    "You are a concise assistant. Use the tools when they help.",
		},
		NeedsApproval: []string{},
		MaxTurns:      20,
	}
	names := make([]string, 0, len(tools))
	for name := range tools {
		names = append(names, name)
	}
	sort.Strings(names) // a stable tool list keeps the model's prompt prefix stable
	for _, name := range names {
		agent.Request.Tools = append(agent.Request.Tools, tools[name].Spec)
		if tools[name].NeedsApproval {
			agent.NeedsApproval = append(agent.NeedsApproval, name)
		}
	}
	return agent, nil
}

func CallLLM(ctx workflow.ActivityContext) (any, error) {
	var req ModelRequest
	if err := ctx.GetInput(&req); err != nil {
		return nil, err
	}
	reply, err := model.Complete(ctx.Context(), req)
	var rejected *ModelRejected
	if errors.As(err, &rejected) {
		return ModelReply{Error: rejected}, nil // the same request fails the same way
	}
	if err != nil {
		return nil, err // transient: the call-site retry policy retries it
	}
	return reply, nil
}

func RunTool(ctx workflow.ActivityContext) (any, error) {
	var req ToolRequest
	if err := ctx.GetInput(&req); err != nil {
		return nil, err
	}
	t, ok := tools[req.Call.Name]
	if !ok { // the model named a tool that does not exist
		return toolResult(req.Call.ID, fmt.Sprintf("Unknown tool %q.", req.Call.Name), true), nil
	}
	out, err := t.Run(ctx.Context(), req.Call.Input, req.IdempotencyKey)
	var retryable RetryableToolError
	if errors.As(err, &retryable) {
		return nil, err // the call-site retry policy retries it, durably
	}
	if err != nil { // the model sees the failure and can correct itself
		return toolResult(req.Call.ID, err.Error(), true), nil
	}
	return toolResult(req.Call.ID, out, false), nil
}

func toolResult(id, content string, isError bool) ToolResult {
	return ToolResult{Type: "tool_result", ToolUseID: id, Content: content, IsError: isError}
}

// ---------------------------------------------------------------------------
// The workflow: the loop itself. Deterministic - it decides, activities act.
// Await unwinds a pending task with a panic, so a deferred call runs on every
// suspension: never defer a context call, and never recover() in a workflow.
// ---------------------------------------------------------------------------

var (
	llmRetry = workflow.RetryPolicy{
		MaxAttempts:          6,
		InitialRetryInterval: 2 * time.Second,
		BackoffCoefficient:   2,
		MaxRetryInterval:     time.Minute,
	}
	toolRetry = workflow.RetryPolicy{
		MaxAttempts:          3,
		InitialRetryInterval: time.Second,
		BackoffCoefficient:   2,
		MaxRetryInterval:     20 * time.Second,
	}
	approvalTimeout = 24 * time.Hour // never a computed zero: zero cancels the wait at once
)

type Run struct {
	Task    string    `json:"task"`
	History []Message `json:"history,omitempty"`
}

type Result struct {
	Status   string          `json:"status"`
	Content  json.RawMessage `json:"content,omitempty"`
	Error    *ModelRejected  `json:"error,omitempty"`
	Messages []Message       `json:"messages"`
}

func AgentLoop(ctx *workflow.WorkflowContext) (any, error) {
	var run Run
	if err := ctx.GetInput(&run); err != nil {
		return nil, err
	}
	var agent Agent
	if err := ctx.CallActivity("load_agent").Await(&agent); err != nil {
		return nil, err
	}
	task, _ := json.Marshal(run.Task)
	// Earlier turns, verbatim, then the new user message: append-only, never rebuilt.
	messages := append(slices.Clone(run.History), Message{Role: "user", Content: task})

	for turn := 0; turn < agent.MaxTurns; turn++ {
		req := agent.Request
		req.Messages = messages
		var reply ModelReply
		err := ctx.CallActivity("call_llm",
			workflow.WithActivityInput(req),
			workflow.WithActivityRetryPolicy(&llmRetry)).Await(&reply)
		if err != nil {
			return nil, err
		}
		if reply.Error != nil {
			return Result{Status: "rejected", Error: reply.Error, Messages: messages}, nil
		}

		messages = append(messages, Message{Role: "assistant", Content: reply.Content})
		switch reply.StopReason {
		case "pause_turn": // a server tool paused the turn: send it back as-is
			continue
		case "tool_use":
		case "end_turn":
			return Result{Status: "completed", Content: reply.Content, Messages: messages}, nil
		default: // max_tokens, refusal: never run tools from these
			return Result{Status: reply.StopReason, Content: reply.Content, Messages: messages}, nil
		}

		var blocks []ToolUse
		if err := json.Unmarshal(reply.Content, &blocks); err != nil {
			return nil, err
		}
		calls := slices.DeleteFunc(blocks, func(b ToolUse) bool { return b.Type != "tool_use" })
		results, err := json.Marshal(runTools(ctx, agent, calls))
		if err != nil {
			return nil, err
		}
		messages = append(messages, Message{Role: "user", Content: results}) // all results, one message
	}
	return Result{Status: "max_turns", Messages: messages}, nil
}

func runTools(ctx *workflow.WorkflowContext, agent Agent, calls []ToolUse) []ToolResult {
	results := make(map[string]ToolResult, len(calls))
	for _, call := range calls { // a slice, in the model's order: deterministic
		if slices.Contains(agent.NeedsApproval, call.Name) && !waitForApproval(ctx, call) {
			results[call.ID] = toolResult(call.ID, "The user did not approve this call.", true)
		}
	}

	type pending struct {
		call ToolUse
		task workflow.Task
	}
	var scheduled []pending
	for _, call := range calls {
		if _, done := results[call.ID]; done {
			continue
		}
		in := ToolRequest{Call: call, IdempotencyKey: ctx.ID() + ":" + call.ID}
		scheduled = append(scheduled, pending{call, ctx.CallActivity("run_tool",
			workflow.WithActivityInput(in),
			workflow.WithActivityRetryPolicy(&toolRetry))})
	}
	// Go has no when-all. Every task was created above, so they run in parallel;
	// awaiting each in turn keeps a failure local to its own call. Awaiting one
	// before creating the next would silently serialise them.
	for _, p := range scheduled {
		var r ToolResult
		if err := p.task.Await(&r); err != nil {
			r = toolResult(p.call.ID, "Tool failed after retries: "+err.Error(), true)
		}
		results[p.call.ID] = r
	}

	out := make([]ToolResult, 0, len(calls))
	for _, call := range calls { // never range over the map: its order is random
		out = append(out, results[call.ID])
	}
	return out
}

func waitForApproval(ctx *workflow.WorkflowContext, call ToolUse) bool {
	status, _ := json.Marshal(map[string]string{"awaiting_approval": call.ID, "tool": call.Name})
	ctx.SetCustomStatus(string(status))
	var decision struct {
		Approved bool `json:"approved"`
	}
	err := ctx.WaitForExternalEvent("approval:"+call.ID, approvalTimeout).Await(&decision)
	ctx.SetCustomStatus(`{"awaiting_approval":null}`)
	return err == nil && decision.Approved // a timeout comes back as an error
}

type Session struct {
	History []Message `json:"history,omitempty"`
	Turn    int       `json:"turn"`
}

func AgentSession(ctx *workflow.WorkflowContext) (any, error) {
	var session Session
	if err := ctx.GetInput(&session); err != nil {
		return nil, err
	}
	var message struct {
		Text string `json:"text"`
	}
	if err := ctx.WaitForExternalEvent("user_message", -1).Await(&message); err != nil {
		return nil, err
	}
	var result Result
	err := ctx.CallChildWorkflow("agent_loop",
		workflow.WithChildWorkflowInput(Run{Task: message.Text, History: session.History}),
		workflow.WithChildWorkflowInstanceID(fmt.Sprintf("%s-turn-%d", ctx.ID(), session.Turn))).Await(&result)
	if err != nil {
		return nil, err
	}
	// Keep unprocessed events: a message that arrived during this turn waits in the next one.
	ctx.ContinueAsNew(Session{History: result.Messages, Turn: session.Turn + 1}, workflow.WithKeepUnprocessedEvents())
	return nil, nil
}

func register() (*workflow.Registry, error) {
	r := workflow.NewRegistry()
	for name, w := range map[string]workflow.Workflow{"agent_loop": AgentLoop, "agent_session": AgentSession} {
		if err := r.AddWorkflowN(name, w); err != nil {
			return nil, err
		}
	}
	for name, a := range map[string]workflow.Activity{"load_agent": LoadAgent, "call_llm": CallLLM, "run_tool": RunTool} {
		if err := r.AddActivityN(name, a); err != nil {
			return nil, err
		}
	}
	return r, nil
}
```

The entry point sets the registry and starts the worker:

```go
import dapr "github.com/dapr/go-sdk/client"

func main() {
	model = newModel() // your harness's client, behind the Model interface
	tools["get_weather"] = Tool{Spec: weatherSpec, Run: getWeather}

	r, err := register()
	if err != nil {
		log.Fatal(err)
	}
	c, err := dapr.NewWorkflowClient() // DAPR_GRPC_ENDPOINT and DAPR_API_TOKEN from the environment
	if err != nil {
		log.Fatal(err)
	}
	if err := c.StartWorker(context.Background(), r); err != nil {
		log.Fatal(err)
	}
	select {} // a worker dials out and polls for work: no port, no HTTP server
}
```

## Spelling

| Need | Spelling |
| --- | --- |
| Orchestrator | `func(ctx *workflow.WorkflowContext) (any, error)` — the input is **not** a parameter; `ctx.GetInput(&v)` |
| Activity | `func(ctx workflow.ActivityContext) (any, error)` — by value, not a pointer |
| Register | `r := workflow.NewRegistry()`, then `r.AddWorkflowN(name, fn)` and `r.AddActivityN(name, fn)` |
| Call an activity | `ctx.CallActivity("name", workflow.WithActivityInput(v), workflow.WithActivityRetryPolicy(&policy))` |
| Retry | `workflow.RetryPolicy{MaxAttempts, InitialRetryInterval, BackoffCoefficient, MaxRetryInterval, RetryTimeout, Handle}` — `MaxAttempts` counts the first try |
| Await | `.Await(&out)`, returning the activity's failure as an error |
| External event | `ctx.WaitForExternalEvent(name, timeout)` — the timeout comes back as an error from `Await` |
| Custom status | `ctx.SetCustomStatus(string)` |
| Child workflow | `ctx.CallChildWorkflow("name", workflow.WithChildWorkflowInput(v), workflow.WithChildWorkflowInstanceID(id))` |
| Continue as new | `ctx.ContinueAsNew(input, workflow.WithKeepUnprocessedEvents())`, then return |
| Instance id | `ctx.ID()` — the activity context has none, so build keys in the workflow |
| Replay-safe now | `ctx.CurrentTimeUTC()` |
| Start a run from code | `c.ScheduleWorkflow(ctx, "agent_loop", workflow.WithInstanceID(id), workflow.WithInput(v))` on the client from `dapr.NewWorkflowClient()` |
| Send an approval from code | `c.RaiseEvent(ctx, id, "approval:<tool-call-id>", workflow.WithEventPayload(v))` |

## Traps

**There is no when-all and no when-any.** Parallel means *create every task, then await
each in turn*, which is what `runTools` does. Awaiting the first before creating the
second silently serialises them: the workflow is still correct, and the parallelism is
gone, invisibly in a diff.

**`Await` unwinds a pending task with a panic.** While a task has not completed, `Await`
panics with `ErrTaskBlocked` so the SDK can stop the function and re-run it when the
result arrives. Two consequences: a `defer` in a workflow function runs on every
suspension — a deferred `SetCustomStatus` would clear an approval notice while the
approval is still pending — and a `recover()` would swallow the unwinding. Never defer a
context call, and never recover in a workflow.

**Never range over a map in the body.** Go randomizes map iteration order on purpose, so a
map that drives scheduling or builds a message emits a different sequence on replay.
`runTools` keeps results in a map but builds its output by walking the `calls` slice.

**Classify inside the activity, not in `Handle`.** `RetryPolicy.Handle` is a real retry
predicate, but it runs in the workflow on the error `Await` returns, which is
`task failed with an error: <message>` — the typed error the activity returned did not
survive the wire. `errors.As` in the activity, as in `CallLLM` and `RunTool`, is the only
place the type still exists.

**A zero timeout cancels at once.** `WaitForExternalEvent` with `0` fails immediately; a
negative duration waits forever. Never pass a zero you computed. Event names are
case-insensitive.

**`json.RawMessage` is the verbatim transcript.** It keeps the model's content blocks as
bytes through every hop, so nothing re-renders them. `encoding/json` still compacts
whitespace and escapes `<`, `>` and `&` when it marshals, which changes the bytes and not
the JSON.
