---
name: routing-agent-not-workflow
description: An AI-assistant-with-memory request fires diagrid-agent-scaffold and must not fire diagrid-workflow-scaffold. The other half of the sharpest trigger pair.
tags: [routing]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  diagrid-agent-scaffold fires. diagrid-workflow-scaffold does not. The prompt
  avoids the words "agent", "workflow", "orchestration", "pipeline" and "saga" so
  neither skill can win on a keyword echo.
---

We want a support assistant that answers customer questions, can look a customer's
order history up on its own, and hands over to a human when it is out of its depth.
It has to remember where a conversation got to even if the process it is running in
gets killed and comes back. Stand it up on Catalyst.
