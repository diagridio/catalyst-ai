---
name: starter-workflow-loads-a-skill
description: The docs' workflow starter prompt names the catalyst_* tools explicitly. A Catalyst skill must still load, so its guidance reaches the model.
tags: [routing]
plugins: ["../.."]
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Loads a catalyst-* skill (setup or develop, or a scaffold) before acting on the
  starter prompt, rather than going straight to the tools the prompt names.
---

I'm new to Diagrid Catalyst. Show me a durable workflow that survives a crash, using the Catalyst MCP tools for everything in Catalyst, and your shell for git and running the app.
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link: https://catalyst.r1.diagrid.io/workflows/<app-id>/<instance-id>?project=<project>.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Clone https://github.com/diagridio/catalyst-quickstarts, take the durable workflow sample in my language (Python if unsure), and make sure App ID `durable-workflow` exists in project `default`.
3. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start the sample in the background with its environment loaded from it.
4. Run one workflow to completion. Then start one through the sample's crash endpoint, show me with `catalyst_get_workflow_run` that it's RUNNING and waiting, not failed, and wait until I type continue.
5. Restart the app. When the run completes, show me from its history that finished steps ran once and only the step the crash cut off ran again.
6. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
