---
type: llm
focus: last_message
---
The user has a hand-written loop that calls a model API, runs the functions the model
asks for, and repeats. They want it to resume after a crash without re-paying for model
calls, and without adopting a framework.

PASS if the response keeps their loop and makes it durable at the right granularity:
the loop itself becomes the orchestrating code, each model call is its own separately
recorded step, and each function call the model requests is its own separately recorded
step — so a crash re-runs only the call that was interrupted.

FAIL if the response does any of these:
- wraps the whole loop, or a whole turn (model call plus its function calls), in a single
  step, so a crash repeats model calls or re-runs functions that already finished;
- tells the user to move to an agent framework or a framework adapter instead of keeping
  their loop;
- makes the model call or a function call directly inside the orchestrating code rather
  than in a recorded step;
- offers a hosted or managed agent as the way to do it.

Judge the design, not the vocabulary: "activity", "durable step" and "checkpointed call"
all count, as long as each model call and each function call is its own one.
