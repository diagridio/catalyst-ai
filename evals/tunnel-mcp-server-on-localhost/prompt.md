---
name: tunnel-mcp-server-on-localhost
description: An MCP server runs on the user's laptop and a Catalyst agent must call its tools under an access policy. The answer must tunnel the MCPServer's own identity with `diagrid dev run`, not a public tunnel, and grant the caller.
tags: [routing, tunnels]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Loads catalyst-app-tunnels. Creates an MCPServer named travel whose URL path is /mcp,
  waits for its identity to be ready, opens a tunnel on that same identity with
  `diagrid dev run --project default --id travel --app-port 8000`, and grants the agent
  weather-assistant access to the named tools with catalyst_grant_access, leaving
  cancel_booking out. Does not suggest cloudflared, ngrok or any other public URL, does
  not create a separate App ID for the server, and does not tunnel the agent.
---

I have a FastMCP server running on my laptop at http://127.0.0.1:8000/mcp with three
tools: get_local_time, convert_currency and cancel_booking. My Catalyst agent
weather-assistant (project default) should be able to call the first two through
Catalyst, and must not be able to call cancel_booking. The MCP server should be called
travel. How do I wire this up?
