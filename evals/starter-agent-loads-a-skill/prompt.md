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
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link: https://catalyst.diagrid.io/workflows/schedule-planner/<instance-id>?project=<project>, where <project> is `default` unless a new one was created.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Clone https://github.com/diagridio/catalyst-quickstarts and take `agents/langgraph`. With `catalyst_apply`, make sure agent `schedule-planner` exists in project `default`. If `default` is missing, do not reuse another project: offer to create a new one with managed pub/sub, KV store, workflow store and agent infrastructure, wait for my agreement, and use `?project=<new project>` in the console links. Catalyst provides its state, pub/sub and registry, so apply only the agent itself.
3. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start `crash_test.py` on port 8001 in the background with its environment loaded from it.
4. Start a run with `POST /crash/run` and `kill_after_seconds`, so the agent dies mid-run. Show me with `catalyst_get_workflow_run` that the run is RUNNING and waiting, not failed, and wait until I type continue.
5. Restart it the same way. When the run completes, show me from its history that the steps finished before the crash ran once and only the one it cut off ran again.
6. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
