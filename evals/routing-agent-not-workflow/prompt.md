---
name: routing-agent-not-workflow
description: An AI-assistant-with-memory request fires catalyst-agent-scaffold and must not fire catalyst-workflow-scaffold. The other half of the sharpest trigger pair.
tags: [routing]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  catalyst-agent-scaffold fires. catalyst-workflow-scaffold does not. The prompt
  avoids the words "agent", "workflow", "orchestration", "pipeline" and "saga" so
  neither skill can win on a keyword echo.
---

We want a support assistant that answers customer questions, can look a customer's
order history up on its own, and hands over to a human when it is out of its depth.
It has to remember where a conversation got to even if the process it is running in
gets killed and comes back. Stand it up on Catalyst.
