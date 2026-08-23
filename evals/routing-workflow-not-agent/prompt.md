---
name: routing-workflow-not-agent
description: A multi-step orchestration request fires catalyst-workflow-scaffold and must not fire catalyst-agent-scaffold. Half of the sharpest trigger pair in the plugin.
tags: [routing]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  catalyst-workflow-scaffold fires. catalyst-agent-scaffold does not. The prompt
  deliberately avoids the literal words "workflow" and "Dapr" so the routing
  decision is made on the description's distinctive terms rather than on a
  keyword echo.
---

Our order pipeline has to reserve stock, charge the card, then book a courier, in
that order, and it has to pick up where it left off if the service restarts
half way through an order. Set that up in our Catalyst project.
