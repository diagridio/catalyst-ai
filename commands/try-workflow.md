---
description: Try Catalyst in one step. A durable workflow crashes mid-run and resumes where it stopped, driven through the Catalyst MCP tools.
---

I'm new to Diagrid Catalyst. Show me a durable workflow that survives a crash, using the Catalyst MCP tools for everything in Catalyst, and your shell for git and running the app.
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link: https://catalyst.diagrid.io/workflows/<app-id>/<instance-id>?project=<project>.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Clone https://github.com/diagridio/catalyst-quickstarts, take the durable workflow sample in my language (Python if unsure), and make sure App ID `durable-workflow` exists in project `default`. If `default` is missing, do not reuse another project: offer to create a new one with managed pub/sub, KV store, workflow store and agent infrastructure, wait for my agreement, and use `?project=<new project>` in the console links.
3. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start the sample in the background with its environment loaded from it.
4. Run one workflow to completion. Then start one through the sample's crash endpoint, show me with `catalyst_get_workflow_run` that it's RUNNING and waiting, not failed, and wait until I type continue.
5. Restart the app. When the run completes, show me from its history that finished steps ran once and only the step the crash cut off ran again.
6. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
