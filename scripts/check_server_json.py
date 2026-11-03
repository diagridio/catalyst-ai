#!/usr/bin/env python3
"""Hold server.json, the MCP Registry entry, to what the plugin actually ships.

The schema itself is checked by `mcp-publisher validate` in CI. This gate covers
what the schema cannot know:

* The name is `io.diagrid/catalyst` and nothing else. The registry lets each
  remote URL belong to one server name only, so a typo here would publish
  under a name that then owns the URL for good.
* There is exactly one remote, streamable HTTP, at the same URL as the default
  in .claude-plugin/plugin.json. Two copies of one URL drift, and the registry
  entry would then send clients somewhere the plugin does not.
* The version is plain X.Y.Z with no `v`. The publish workflow overwrites it,
  but a leading `v` or a prerelease suffix would never sort as latest.

Run: python3 scripts/check_server_json.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER_JSON = Path("server.json")
PLUGIN_JSON = Path(".claude-plugin") / "plugin.json"
PLUGIN_SERVER = "catalyst"
SERVER_NAME = "io.diagrid/catalyst"
REMOTE_TYPE = "streamable-http"
PLAIN_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# `${VAR:-default}`, the form plugin.json uses so a developer can point the plugin
# elsewhere. Only the default is what ships.
ENV_DEFAULT = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:-(?P<default>[^}]+)\}$")


def load(path: Path) -> tuple[object, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path.name}: missing"
    except json.JSONDecodeError as exc:
        return None, f"{path.name}: not valid JSON ({exc})"


def plugin_url(plugin: object) -> str | None:
    """The URL the plugin ships for the catalyst server, with any env default resolved."""
    try:
        raw = plugin["mcpServers"][PLUGIN_SERVER]["url"]  # type: ignore[index]
    except (KeyError, TypeError):
        return None
    if not isinstance(raw, str):
        return None
    match = ENV_DEFAULT.match(raw)
    return match.group("default") if match else raw


def check(root: Path) -> list[str]:
    server, error = load(root / SERVER_JSON)
    if error:
        return [error]
    if not isinstance(server, dict):
        return [f"{SERVER_JSON}: must be a JSON object"]

    findings: list[str] = []
    if server.get("name") != SERVER_NAME:
        findings.append(
            f"{SERVER_JSON}: name is {server.get('name')!r}, must be {SERVER_NAME!r}. "
            "The first publish locks the remote URL to one name for good."
        )

    version = server.get("version")
    if not isinstance(version, str) or not PLAIN_SEMVER.match(version):
        findings.append(f"{SERVER_JSON}: version {version!r} must be plain X.Y.Z, with no 'v' and no suffix")

    if "packages" in server:
        findings.append(f"{SERVER_JSON}: declares packages; this server is remote only")

    remotes = server.get("remotes")
    if not isinstance(remotes, list) or len(remotes) != 1 or not isinstance(remotes[0], dict):
        findings.append(f"{SERVER_JSON}: must declare exactly one remote")
        return findings
    remote = remotes[0]
    if remote.get("type") != REMOTE_TYPE:
        findings.append(f"{SERVER_JSON}: remote type is {remote.get('type')!r}, must be {REMOTE_TYPE!r}")

    plugin, error = load(root / PLUGIN_JSON)
    if error:
        findings.append(error)
        return findings
    want = plugin_url(plugin)
    if want is None:
        findings.append(f"{PLUGIN_JSON}: has no mcpServers.{PLUGIN_SERVER}.url to compare against")
    elif remote.get("url") != want:
        findings.append(
            f"{SERVER_JSON}: remote url {remote.get('url')!r} differs from {PLUGIN_JSON}'s {want!r}. "
            "Change both together."
        )
    return findings


def main() -> int:
    findings = check(REPO)
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"{SERVER_JSON} matches {PLUGIN_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
