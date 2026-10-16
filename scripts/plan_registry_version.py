#!/usr/bin/env python3
"""Decide the next MCP Registry version for server.json, and whether to publish at all.

The registry is the source of truth for the version line. Nobody edits the version
in server.json by hand: this reads every version the registry holds for the server
and bumps the highest.

* Nothing published yet: publish 0.0.1, whatever bump was asked for.
* This workflow run already published a version (a re-run after a later step
  failed): skip, and report that version so the tag can still be made. A run is
  recognised by the `runId` the workflow writes into the entry's publisher-provided
  metadata, which the registry keeps. A published version can never be reused, so
  publishing twice would burn a second one for the same change.
* A patch bump whose metadata is identical to the latest entry: skip. Nothing changed,
  and an identical entry per run would make the history meaningless. A minor or major
  bump is a deliberate request, so it publishes even when nothing else changed.
* Otherwise: publish the bumped version.

Versions are plain X.Y.Z. A prerelease sorts before its release and would never
become latest, so the registry's own entries that are not plain are ignored when
finding the highest, but still count as taken.

Run: python3 scripts/plan_registry_version.py --bump patch --run-id <id>
Writes `action` (publish|skip) and `version` to $GITHUB_OUTPUT when it is set.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER_JSON = REPO / "server.json"
REGISTRY = "https://registry.modelcontextprotocol.io"
PUBLISHER_META = "io.modelcontextprotocol.registry/publisher-provided"
RUN_ID_KEY = "runId"
FIRST_VERSION = (0, 0, 1)
BUMPS = ("patch", "minor", "major")
PLAIN_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# Fields the workflow sets per publish, so they never count as a metadata change.
PER_PUBLISH_FIELDS = ("version", "$schema", "_meta")
HTTP_NOT_FOUND = 404
TIMEOUT_SECONDS = 30

Version = tuple[int, int, int]


def parse(version: str) -> Version | None:
    match = PLAIN_SEMVER.match(version)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def render(version: Version) -> str:
    return ".".join(str(part) for part in version)


def bumped(version: Version, bump: str) -> Version:
    major, minor, patch = version
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def comparable(server: dict) -> dict:
    return {k: v for k, v in server.items() if k not in PER_PUBLISH_FIELDS}


def run_id_of(server: dict) -> str | None:
    meta = server.get("_meta")
    if not isinstance(meta, dict):
        return None
    provided = meta.get(PUBLISHER_META)
    if not isinstance(provided, dict):
        return None
    value = provided.get(RUN_ID_KEY)
    return str(value) if value is not None else None


def plan(entries: list[dict], local: dict, bump: str, run_id: str) -> tuple[str, str]:
    """Return (action, version) for the registry's entries and the checked-in server.json."""
    if bump not in BUMPS:
        raise ValueError(f"bump must be one of {', '.join(BUMPS)}, got {bump!r}")

    servers = [e["server"] for e in entries if isinstance(e.get("server"), dict)]
    for server in servers:
        if run_id and run_id_of(server) == run_id:
            return "skip", server["version"]

    taken = {s.get("version") for s in servers}
    plain = [(parse(s["version"]), s) for s in servers if isinstance(s.get("version"), str) and parse(s["version"])]
    if not plain:
        return "publish", render(FIRST_VERSION)

    latest_version, latest = max(plain, key=lambda pair: pair[0])
    if bump == "patch" and comparable(latest) == comparable(local):
        return "skip", render(latest_version)

    following = render(bumped(latest_version, bump))
    if following in taken:
        raise ValueError(f"version {following} is already in the registry")
    return "publish", following


def fetch_entries(name: str) -> list[dict]:
    """Every version the registry holds for `name`, deleted ones included, or [] if none."""
    encoded = urllib.parse.quote(name, safe="")
    url = f"{REGISTRY}/v0.1/servers/{encoded}/versions?include_deleted=true"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == HTTP_NOT_FOUND:
            return []
        raise
    servers = body.get("servers")
    if not isinstance(servers, list):
        raise ValueError(f"unexpected registry response from {url}: no servers list")
    return servers


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bump", choices=BUMPS, default="patch")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    local = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    try:
        entries = fetch_entries(local["name"])
        action, version = plan(entries, local, args.bump, args.run_id)
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        print(f"cannot plan the registry version: {exc}", file=sys.stderr)
        return 1

    print(f"action={action}\nversion={version}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"action={action}\nversion={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
