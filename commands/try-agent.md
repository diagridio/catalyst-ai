---
description: Try Catalyst in one step. A durable AI agent (LangGraph, no API key) crashes mid-run and resumes where it stopped, driven through the Catalyst MCP tools.
---

I'm new to Diagrid Catalyst. Show me a durable AI agent that survives a crash, using the Catalyst MCP tools for everything in Catalyst, and your shell for git and running the app. The sample runs on a built-in offline model, so no API key is needed.
`<project>` in this prompt is the name, not the numeric ID, of the project settled in step 2: `default` unless step 2 settles another.
Whenever a run starts, whenever you wait for me, and at the end, give me that run's console link as a markdown link, never in backticks or a code block, so I can click it: [Run <instance-id> in Catalyst](https://catalyst.diagrid.io/workflows/schedule-planner/<instance-id>?project=<project>). Put the plain URL on the line after it as well, also outside backticks, in case my terminal does not render links.
1. Call `catalyst_whoami` and tell me which org I'm signed in to. If that fails, help me sign in.
2. Settle the project from the `getDefaultProject` part of step 1's answer. It already reports this, so do not re-derive it with `catalyst_list_projects`.
   - `outcome: ready` — use the project it names.
   - `outcome: pending` — it is still being bootstrapped, and asking is what nudges it along. Tell me you are waiting, wait about five seconds, call `catalyst_whoami` again, and repeat up to five times. Never create a project while it is pending.
   - `outcome: unavailable` — it will never arrive. Say which `reason` in one sentence. If `otherProjects` has names, list them and ask me which to use, offering a new project as one more choice. If it is empty, say so and offer to create one.
   To create one, propose the name `catalyst-try`, let me rename it to anything that is not already in `otherProjects`, tell me it spends one of the few projects my plan allows per region (`catalyst_get_usage` has the live number), and wait for my pick. Then `catalyst_apply` a `Project` whose `spec` sets `defaultPubsubEnabled`, `defaultKVStoreEnabled` and `defaultWorkflowStoreEnabled` to `true`, leaving `spec.region` out so my organization's default region is used. Send it with `dry_run` first, because apply replaces a project that already has that name. If it is refused for the project limit, say so plainly and ask me which existing project to use instead.
   Whichever project we settle on, read it with `catalyst_get_project` and confirm `status.defaultWorkflowStoreEnabled` before step 3. Without the managed workflow store the sidecar boots with no workflow support and step 5 cannot work; turning it on later only helps if the app is created afterwards.
3. Clone https://github.com/diagridio/catalyst-quickstarts and take `agents/langgraph`. With `catalyst_apply`, make sure agent `schedule-planner` exists in project `<project>`. Catalyst provides its state, pub/sub and registry, so apply only the agent itself.
4. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start `crash_test.py` on port 8001 in the background with its environment loaded from it.
5. Start a run with `POST /crash/run` and `kill_after_seconds`, so the agent dies mid-run. Show me with `catalyst_get_workflow_run` that the run is RUNNING and waiting, not failed, and wait until I type continue.
6. Restart it the same way. When the run completes, show me from its history that the steps finished before the crash ran once and only the one it cut off ran again.
7. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
