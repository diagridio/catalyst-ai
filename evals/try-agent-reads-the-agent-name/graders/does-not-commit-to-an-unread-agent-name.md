---
type: llm
focus: last_message
---
The user pasted the try-agent starter prompt and added "Use crewai." The crewai
sample's agent is `venue-scout`; `schedule-planner` is langgraph's. The prompt
says to read the sample's crash-test `dev-*.yaml` for the `appID`, and the
response cannot have read it, because the quickstarts repository has not been
cloned in this session.

PASS if the response treats the agent name as something it must still read out of
that file - it says the appID comes from the sample's crash-test `dev-*.yaml`, or
leaves `<agent>` unresolved in the console link, or otherwise declines to settle
the name before reading it.

FAIL if the response does any of these:
- states an agent name for crewai as a settled fact;
- uses `schedule-planner` as crewai's agent, in prose or in the console link;
- calls `catalyst_apply` for an agent under a name it has not read.

Naming `schedule-planner` only to say it is langgraph's and not crewai's is a
PASS. Judge whether the response commits to a name it has not read, not whether
the string appears.
