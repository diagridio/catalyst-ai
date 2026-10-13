---
name: starter-agent-loads-a-skill
description: The docs' durable-agent starter prompt names the catalyst_* tools explicitly. A Catalyst skill must still load, so its guidance reaches the model.
tags: [routing]
plugins: ["../.."]
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Loads a catalyst-* skill (setup or develop, or a scaffold) before acting on the
  starter prompt, rather than going straight to the tools the prompt names.
---

I'm new to Diagrid Catalyst. Show me a durable AI agent that survives a crash, using the Catalyst MCP tools for everything in Catalyst, and your shell for git and running the app. The sample runs on a built-in offline model, so no API key is needed.
`<project>` in this prompt is the name, not the numeric ID, of the project settled in step 2: `default` unless step 2 settles another.
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link as a markdown link, never in backticks or a code block, so I can click it: [Run <instance-id> in Catalyst](https://catalyst.diagrid.io/workflows/schedule-planner/<instance-id>?project=<project>). Put the plain URL on the line after it as well, also outside backticks, in case my terminal does not render links.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Check with `catalyst_list_projects` that project `default` exists, and use it if it does. If it does not, never create a project: if I have other projects, list them and ask me which to use; if I have none, say so in one sentence, give me [the project list](https://catalyst.diagrid.io/admin/projects) to create one in, and wait for me to tell you its name.
3. Clone https://github.com/diagridio/catalyst-quickstarts and take `agents/langgraph`. With `catalyst_apply`, make sure agent `schedule-planner` exists in project `<project>`. Catalyst provides its state, pub/sub and registry, so apply only the agent itself.
4. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start `crash_test.py` on port 8001 in the background with its environment loaded from it.
5. Start a run with `POST /crash/run` and `kill_after_seconds`, so the agent dies mid-run. Show me with `catalyst_get_workflow_run` that the run is RUNNING and waiting, not failed, and wait until I type continue.
6. Restart it the same way. When the run completes, show me from its history that the steps finished before the crash ran once and only the one it cut off ran again.
7. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
