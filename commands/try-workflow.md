---
description: Try Catalyst in one step. A durable workflow crashes mid-run and resumes where it stopped, driven through the Catalyst MCP tools.
---

I'm new to Diagrid Catalyst. Show me a durable workflow that survives a crash, using the Catalyst MCP tools for everything in Catalyst, and your shell for git and running the app.
`<project>` in this prompt is the name, not the numeric ID, of the project settled in step 2: `default`, or the new or existing project step 2 settles on.
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link as a markdown link, never in backticks or a code block, so I can click it: [Run <instance-id> in Catalyst](https://catalyst.diagrid.io/workflows/<app-id>/<instance-id>?project=<project>). Put the plain URL on the line after it as well, also outside backticks, in case my terminal does not render links.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Check with `catalyst_list_projects` that project `default` exists, and use it if it does. If it does not, offer to create a new project with managed pub/sub, KV store, workflow store and agent infrastructure (read the `Project` schema with `catalyst_get_resource_schema` first), wait for my agreement, create it with `catalyst_apply`, and confirm with `catalyst_list_projects` and `catalyst_get_project` that it has all of those attached. If I would rather use a project I already have, use the one I name.
3. Clone https://github.com/diagridio/catalyst-quickstarts, take the durable workflow sample in my language (Python if unsure), and make sure App ID `durable-workflow` exists in project `<project>`.
4. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start the sample in the background with its environment loaded from it.
5. Run one workflow to completion. Then start one through the sample's crash endpoint, show me with `catalyst_get_workflow_run` that it's RUNNING and waiting, not failed, and wait until I type continue.
6. Restart the app. When the run completes, show me from its history that finished steps ran once and only the step the crash cut off ran again.
7. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
