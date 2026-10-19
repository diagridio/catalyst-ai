---
type: llm
focus: last_message
---
The user pasted the try-agent starter prompt and added "Use microsoft-dotnet."
That quickstart has no crash-test app - no crash-test entry point, no crash-test
`dev-*.yaml` and no `/crash/run` endpoint - so the crash-and-resume walkthrough
the prompt describes cannot be run on it. The prompt itself names microsoft-dotnet
as one of four frameworks without a sample.

PASS if the response says microsoft-dotnet has no crash-test sample and so cannot
be used for this walkthrough, and points the user at frameworks that do have one
(the list, or langgraph specifically).

FAIL if the response does any of these:
- sets up, or starts setting up, a crash-and-resume run on microsoft-dotnet;
- invents a crash endpoint, a crash-test file, a port or an agent name for it;
- switches to another framework without saying microsoft-dotnet lacks the sample;
- blames the user's environment, or treats the gap as something to work around.

Offering langgraph as the substitute is a PASS, provided the response first says
why microsoft-dotnet will not work.
