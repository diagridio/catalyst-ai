---
name: routing-workflow-not-agent
description: A multi-step orchestration request fires diagrid-workflow-scaffold and must not fire diagrid-agent-scaffold. Half of the sharpest trigger pair in the plugin.
tags: [routing]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  diagrid-workflow-scaffold fires. diagrid-agent-scaffold does not. The prompt
  deliberately avoids the literal words "workflow" and "Dapr" so the routing
  decision is made on the description's distinctive terms rather than on a
  keyword echo.
---

Our order pipeline has to reserve stock, charge the card, then book a courier, in
that order, and it has to pick up where it left off if the service restarts
half way through an order. Set that up in our Catalyst project.
