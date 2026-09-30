---
name: degrade-no-mcp-tools
description: No catalyst_* tools are connected in this session. An inventory question must degrade to the diagrid CLI, not to "Catalyst is unreachable" and not to an invented inventory.
tags: [degradation]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Notes that no catalyst_* MCP tools are available in this session and hands over
  the CLI reads that answer the question instead. Does not present the missing
  tools as Catalyst being unreachable, and does not invent app names or
  statuses to fill the gap — no tool in this run can read a live project.
---

What apps are running in our Catalyst project right now, and which of them are
not ready? I need the list for a handover in ten minutes.
