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
2. Settle the project from the `getDefaultProject` part of step 1's answer. It already reports this, so do not re-derive it with `catalyst_list_projects`. It carries an `outcome`, a `reason`, my `otherProjects`, and an `instruction` written for you. The `instruction` is the authority on whether a project may be created for my organization — follow it, and never decide that for yourself.
   - `outcome: ready` — use the project it names.
   - `outcome: pending` — it is still being bootstrapped, and asking is what nudges it along. Tell me you are waiting, wait about five seconds, call `catalyst_whoami` again, and repeat up to five times. Never create a project while it is pending.
   - `outcome: unavailable` — it will never arrive. Say which `reason` in one sentence. If `otherProjects` has names, list them and ask me which to use. If it is empty, do what the `instruction` says: where it forbids a project, tell me what it tells you and stop there rather than improvising one — for a region group that means my organization needs a standalone region, and no project you could make would work. Where it permits one, it carries the spec: which region checks to make, whether to name `spec.region`, and which managed stores that region supports.
   Before you apply that spec: propose the name `catalyst-try`, never `default`, and let me rename it to anything that is not already in `otherProjects`; tell me it spends one of the few projects my plan allows per region (`catalyst_get_usage` has the live number); and wait for my pick. Make the instruction's region checks with `catalyst_get_region` before applying, not after. Send `catalyst_apply` with `dry_run` first, because apply replaces a project that already has that name. If it is refused for the project limit, say so plainly and ask me which existing project to use instead.
   Whichever project we settle on, read it back with `catalyst_get_project` before step 3 and tell me which managed stores it actually has — a managed store the region does not support is refused outright, and managed pub/sub is switched off silently, so read it rather than assume it. `status.defaultWorkflowStoreEnabled` must be true: without the managed workflow store the sidecar boots with no workflow support and step 5 cannot work, and turning it on later only helps if the app is created afterwards.
3. Clone https://github.com/diagridio/catalyst-quickstarts and take `agents/langgraph`. With `catalyst_apply`, make sure agent `schedule-planner` exists in project `<project>`. Catalyst provides its state, pub/sub and registry, so apply only the agent itself.
4. Get its connection with `catalyst_get_connection`, write the values to a `.env` in the sample folder (gitignored), and start `crash_test.py` on port 8001 in the background with its environment loaded from it.
5. Start a run with `POST /crash/run` and `kill_after_seconds`, so the agent dies mid-run. Show me with `catalyst_get_workflow_run` that the run is RUNNING and waiting, not failed, and wait until I type continue.
6. Restart it the same way. When the run completes, show me from its history that the steps finished before the crash ran once and only the one it cut off ran again.
7. Explain in at most three sentences why it survived, then offer one next step and wait for my pick.
