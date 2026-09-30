---
name: degrade-no-mcp-tools
description: No catalyst_* tools are connected in this session. An inventory question must degrade to connecting the MCP server, not to "Catalyst is unreachable" and not to an invented inventory.
tags: [degradation]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Notes that no catalyst_* MCP tools are available in this session and says how to
  connect: add the remote Catalyst MCP server and sign in, after which the read that
  answers the question is catalyst_list_apps (or catalyst_get_app). Does not present the missing
  tools as Catalyst being unreachable, and does not invent app names or
  statuses to fill the gap — no tool in this run can read a live project.
---

What apps are running in our Catalyst project right now, and which of them are
not ready? I need the list for a handover in ten minutes.
