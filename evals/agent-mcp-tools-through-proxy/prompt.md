---
name: agent-mcp-tools-through-proxy
description: A Catalyst agent built with the Python SDK must call tools on an MCPServer and the user wants the access grants verified. The answer must call the tools through the agent's sidecar MCP proxy, not as dapr.internal.mcp workflows through DaprMCPClient.
tags: [routing, mcp]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Loads catalyst-agent-scaffold or catalyst-develop. Has the agent weather-assistant call
  the MCPServer travel through its own sidecar, at
  $DAPR_HTTP_ENDPOINT/v1.0/diagrid/mcp/travel with its dapr-api-token, using an ordinary
  streamable HTTP MCP client. Grants get_local_time with catalyst_grant_access and
  verifies it by listing tools and calling one through that endpoint, expecting
  cancel_booking to be absent from tools/list and refused with 403. Does not use
  DaprMCPClient or schedule dapr.internal.mcp.* child workflows.
---

My Catalyst agent weather-assistant (project default) is a Python app built with the
Diagrid openai_agents adapter, and the Dapr Python SDK is installed in its venv. There is
an MCPServer called travel in the project with the tools get_local_time and
cancel_booking. I want the agent to use get_local_time, and I want us to verify the
access grant: it must not be able to call cancel_booking. How should the agent's code
call the MCP server, and how do we check the grant works?
