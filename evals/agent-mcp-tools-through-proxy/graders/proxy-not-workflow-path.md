---
type: llm
focus: last_message
---
A Catalyst agent must call tools on the MCPServer `travel`, and the user wants the access
grant verified. The supported path is the agent's own sidecar MCP proxy:
`$DAPR_HTTP_ENDPOINT/v1.0/diagrid/mcp/travel`, a plain streamable HTTP MCP endpoint,
called with the agent's `dapr-api-token`. The MCPServerAccessPolicy is enforced there.

PASS if the response does all of these:
- has the agent call the server through `/v1.0/diagrid/mcp/travel` (or discovers it via
  `GET /v1.0/diagrid/mcp` and its `connect.path`) with an ordinary MCP client;
- grants `weather-assistant` access to `get_local_time` with `catalyst_grant_access` (or
  describes that grant), leaving `cancel_booking` out;
- verifies the grant through that endpoint: `tools/list` without `cancel_booking`, and a
  call to `cancel_booking` refused (403).

FAIL if the response does any of these:
- uses `DaprMCPClient`, or schedules `dapr.internal.mcp.travel.ListTools` /
  `CallTool.*` workflows, as the way the agent calls the tools;
- has the agent call the MCP server's own upstream URL directly;
- relies on the MCPServer's `scopes` to grant or deny access;
- grants every tool (`*`) or includes `cancel_booking`;
- asks the user to paste a token or API key.

Mentioning the workflow path only to warn against it is neither a pass nor a fail.
