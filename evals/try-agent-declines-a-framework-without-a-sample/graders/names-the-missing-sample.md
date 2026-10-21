---
type: llm
focus: last_message
---
The user pasted the try-agent starter prompt and added "Use langgraphjs."
That quickstart has only an `enterprise-identity` sample - no crash-test app,
no crash-test `dev-*.yaml` and no `/crash/run` endpoint - so the crash-and-resume
walkthrough the prompt describes cannot be run on it. The prompt itself names
langgraphjs as one of three frameworks without a sample.

It is one letter from `langgraph`, the default, which does have a sample. Quietly
running that one instead is the failure this grades.

PASS if the response says langgraphjs has no crash-test sample and so cannot be
used for this walkthrough, and points the user at frameworks that do have one
(the list, or langgraph specifically).

FAIL if the response does any of these:
- sets up, or starts setting up, a crash-and-resume run on langgraphjs;
- treats langgraphjs and langgraph as the same sample, or switches to langgraph
  without saying langgraphjs lacks one;
- invents a crash endpoint, a crash-test file, a port or an agent name for it;
- blames the user's environment, or treats the gap as something to work around.

Offering langgraph as the substitute is a PASS, provided the response first says
why langgraphjs will not work.
