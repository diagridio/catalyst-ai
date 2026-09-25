#!/usr/bin/env python3
"""Resolve every package coordinate the skills emit against its real registry.

lint_skills.py bans coordinates someone already found to be wrong. That cannot
catch the next one, and it cannot notice a coordinate that was right and then
moved: a package renamed, a version yanked, an adapter released past the version
a skill still quotes. This asks the registries.

contracts/package-coordinates.txt is the list. Offline, this also checks that
the list and skills/ agree in both directions, so neither can drift from the
other. Online, it resolves each line on PyPI, npm, NuGet, Maven Central or the Go
module proxy.

    python3 scripts/check_coordinates.py                    # PR mode
    python3 scripts/check_coordinates.py --strict-versions  # scheduled: also fail when a newer release exists
    python3 scripts/check_coordinates.py --offline          # list/skills agreement only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "contracts" / "package-coordinates.txt"
SKILLS = REPO / "skills"

ECOSYSTEMS = ("pypi", "npm", "nuget", "maven", "go")
ABSENT = "absent"
UNVERSIONED = "-"
TIMEOUT_SECONDS = 30
ATTEMPTS = 3

# Coordinate-shaped strings, looked for inside inline code spans only. Fenced
# blocks are left out on purpose: they are full of namespaces and import paths
# that look like coordinates and are not what a user installs.
SCAN_PATTERNS: dict[str, re.Pattern[str]] = {
    "npm": re.compile(r"@(?:diagrid|dapr|mastra)/[a-z0-9-]+"),
    "nuget": re.compile(r"\b(?:Diagrid|Dapr)(?:\.[A-Z][A-Za-z]*)+"),
    "maven": re.compile(r"\bio\.(?:diagrid|dapr):[a-z0-9-]+"),
    "go": re.compile(r"\bgithub\.com/(?:diagridio|dapr)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"),
    "pypi": re.compile(r"\bdiagrid(?=\[)|\bdapr-ext-[a-z-]+"),
}
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`([^`\n]+)`")


class RegistryUnreachable(Exception):
    """The registry did not answer, so nothing can be concluded either way."""


@dataclass(frozen=True)
class Entry:
    ecosystem: str
    coordinate: str
    version: str  # a version, UNVERSIONED or ABSENT


@dataclass(frozen=True)
class Lookup:
    found: bool
    versions: frozenset[str] = frozenset()
    latest: str | None = None


def parse_manifest(text: str) -> list[Entry]:
    entries: list[Entry] = []
    seen: set[tuple[str, str]] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"line {number}: want <ecosystem> <coordinate> <version>, got {raw!r}")
        ecosystem, coordinate, version = fields
        if ecosystem not in ECOSYSTEMS:
            raise ValueError(f"line {number}: unknown ecosystem {ecosystem!r}")
        if (ecosystem, coordinate) in seen:
            raise ValueError(f"line {number}: {ecosystem} {coordinate} is listed twice")
        seen.add((ecosystem, coordinate))
        entries.append(Entry(ecosystem, coordinate, version))
    return entries


def scan_skills(texts: list[str]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for text in texts:
        for span in INLINE_CODE.findall(FENCE.sub("", text)):
            for ecosystem, pattern in SCAN_PATTERNS.items():
                found.update((ecosystem, match) for match in pattern.findall(span))
    return found


def covered(ecosystem: str, coordinate: str, entries: list[Entry]) -> bool:
    for entry in entries:
        if entry.ecosystem != ecosystem:
            continue
        if entry.coordinate == coordinate:
            return True
        # An import path is covered by the module that contains it.
        if ecosystem == "go" and coordinate.startswith(entry.coordinate + "/"):
            return True
    return False


def agreement_problems(entries: list[Entry], texts: list[str]) -> list[str]:
    """The list and skills/ must describe the same coordinates."""
    problems: list[str] = []
    corpus = "\n".join(texts)
    lines = corpus.splitlines()
    for entry in entries:
        if entry.coordinate not in corpus:
            problems.append(f"{entry.ecosystem} {entry.coordinate}: listed, but no skill mentions it — remove the line")
        elif entry.version not in (UNVERSIONED, ABSENT) and not any(
            entry.coordinate in line and entry.version in line for line in lines
        ):
            problems.append(
                f"{entry.ecosystem} {entry.coordinate}: listed at {entry.version}, but no skill line quotes that version beside it"
            )
    for ecosystem, coordinate in sorted(scan_skills(texts)):
        if not covered(ecosystem, coordinate, entries):
            problems.append(
                f"{ecosystem} {coordinate}: a skill names it, but contracts/package-coordinates.txt does not — add it"
            )
    return problems


def registry_problems(entries: list[Entry], lookup: Callable[[Entry], Lookup], strict_versions: bool) -> list[str]:
    problems: list[str] = []
    for entry in entries:
        label = f"{entry.ecosystem} {entry.coordinate}"
        try:
            result = lookup(entry)
        except RegistryUnreachable as exc:
            problems.append(f"{label}: registry unreachable, so this is unverified — {exc}")
            continue
        if entry.version == ABSENT:
            if result.found:
                problems.append(f"{label}: a skill says this does not exist, and it now resolves — update the skill")
            continue
        if not result.found:
            problems.append(f"{label}: does not resolve — a skill tells users to install something that is not there")
            continue
        if entry.version == UNVERSIONED:
            continue
        if entry.version not in result.versions:
            problems.append(f"{label}: the skills quote {entry.version}, which the registry does not have")
        elif strict_versions and result.latest and result.latest != entry.version:
            problems.append(f"{label}: the skills quote {entry.version}, and {result.latest} is out — update the skill")
    return problems


# ------------------------------------------------------------------ registries


def _get(url: str) -> tuple[int, bytes]:
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "catalyst-ai-coordinate-check"})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return exc.code, b""
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        time.sleep(2**attempt)
    raise RegistryUnreachable(f"{url}: {last}")


def _stable(version: str) -> bool:
    return "-" not in version and not re.search(r"(?:a|b|rc|dev)\d*$", version)


def lookup_pypi(name: str) -> Lookup:
    status, body = _get(f"https://pypi.org/pypi/{name}/json")
    if status != 200:
        return Lookup(False)
    data = json.loads(body)
    return Lookup(True, frozenset(data["releases"]), data["info"]["version"])


def lookup_npm(name: str) -> Lookup:
    status, body = _get(f"https://registry.npmjs.org/{name.replace('/', '%2F')}")
    if status != 200:
        return Lookup(False)
    data = json.loads(body)
    return Lookup(True, frozenset(data.get("versions", {})), data.get("dist-tags", {}).get("latest"))


def lookup_nuget(package_id: str) -> Lookup:
    status, body = _get(f"https://api.nuget.org/v3-flatcontainer/{package_id.lower()}/index.json")
    if status != 200:
        return Lookup(False)
    versions = json.loads(body)["versions"]
    stable = [v for v in versions if _stable(v)]
    return Lookup(True, frozenset(versions), (stable or versions)[-1])


def lookup_maven(coordinate: str) -> Lookup:
    group, artifact = coordinate.split(":", 1)
    status, body = _get(f"https://repo1.maven.org/maven2/{group.replace('.', '/')}/{artifact}/maven-metadata.xml")
    if status != 200:
        return Lookup(False)
    xml = body.decode()
    release = re.search(r"<release>([^<]+)</release>", xml)
    return Lookup(True, frozenset(re.findall(r"<version>([^<]+)</version>", xml)), release.group(1) if release else None)


def _go_escape(module: str) -> str:
    # The module proxy protocol encodes capitals as `!` plus the lower-case letter.
    return urllib.parse.quote(re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module))


def lookup_go(module: str) -> Lookup:
    escaped = _go_escape(module)
    status, body = _get(f"https://proxy.golang.org/{escaped}/@v/list")
    if status != 200:
        return Lookup(False)
    versions = frozenset(body.decode().split())
    status, body = _get(f"https://proxy.golang.org/{escaped}/@latest")
    latest = json.loads(body)["Version"] if status == 200 else None
    return Lookup(bool(versions) or latest is not None, versions, latest)


LOOKUPS: dict[str, Callable[[str], Lookup]] = {
    "pypi": lookup_pypi,
    "npm": lookup_npm,
    "nuget": lookup_nuget,
    "maven": lookup_maven,
    "go": lookup_go,
}


def live_lookup(entry: Entry) -> Lookup:
    return LOOKUPS[entry.ecosystem](entry.coordinate)


def skill_texts(root: Path) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.md"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="only check that the list and skills/ agree")
    parser.add_argument("--strict-versions", action="store_true", help="also fail when a newer release than the quoted one exists")
    args = parser.parse_args()

    try:
        entries = parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"✗ {MANIFEST.relative_to(REPO)}: {exc}", file=sys.stderr)
        return 1

    problems = agreement_problems(entries, skill_texts(SKILLS))
    if not args.offline:
        problems += registry_problems(entries, live_lookup, args.strict_versions)

    for problem in problems:
        print(f"  ✗ {problem}")
    if problems:
        print(f"\n{len(problems)} coordinate problem(s)", file=sys.stderr)
        return 1
    mode = "offline" if args.offline else "resolved on their registries"
    print(f"all {len(entries)} coordinates check out ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
