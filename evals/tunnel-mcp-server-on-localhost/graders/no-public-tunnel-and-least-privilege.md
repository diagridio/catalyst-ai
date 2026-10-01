---
type: llm
focus: last_message
---
The user has an MCP server on their laptop and wants a Catalyst agent to call two of its
three tools through Catalyst. The correct path is an app tunnel on the MCPServer's own
identity (`diagrid dev run --id travel --app-port 8000`), after the MCPServer exists, plus
an access grant for the agent.

PASS if the response does all of these:
- creates (or tells the user to create) an `MCPServer` named `travel` whose URL path is
  `/mcp`, before opening the tunnel;
- tunnels the identity named `travel`, the MCP server's own, with `diagrid dev run`;
- grants `weather-assistant` access to `get_local_time` and `convert_currency` with
  `catalyst_grant_access` (or describes that grant), and leaves `cancel_booking` out.

FAIL if the response does any of these:
- suggests cloudflared, ngrok, localtunnel or any other public URL for the server;
- creates a separate App ID for the MCP server, or tunnels `weather-assistant` instead;
- grants every tool (`*`) or includes `cancel_booking`;
- relies on the MCPServer's `scopes` to grant access;
- asks the user to paste a token or API key.

Mentioning `diagrid listen` as a way to inspect traffic is neither a pass nor a fail.
