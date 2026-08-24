#!/usr/bin/env python3
"""Tests for the shared link extractor.

`skill_links` is two lines of regex that both real gates depend on, which is
exactly why it needs its own tests rather than only being exercised through
their fixtures. Its own docstring makes the argument: "a gate whose extractor
stops matching reports no findings, which reads exactly like a clean tree." An
extractor that quietly matched nothing would leave scripts/lint_skills.py and
scripts/check_install.py both green and both blind, and neither one's fixtures
would notice, because every fixture link would simply go unexamined.

So the contract is pinned directly, in both directions: what must be extracted,
and — the half that actually caused trouble — what must NOT be.

Run: python3 scripts/test_skill_links.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skill_links import link_path, local_link_targets

# (name, markdown, the targets that must come out, in order)
EXTRACTION: tuple[tuple[str, str, list[str]], ...] = (
    ("a plain relative link", "See [d](reference/detail.md).", ["reference/detail.md"]),
    ("a link with a fragment", "See [d](reference/detail.md#why).", ["reference/detail.md#why"]),
    ("a bare fragment is not a file", "See [top](#heading).", []),
    ("an http link", "See [x](http://example.com/a.md).", []),
    ("an https link", "See [x](https://example.com/a.md).", []),
    ("a mailto link", "Mail [us](mailto:a@example.com).", []),
    # The rule that matters most. Three spans of exactly this shape are correct
    # as written in catalyst-workflow-from-diagram, crediting upstream, and a
    # hand-rolled checker reported all three as dangling.
    (
        "code spans that look like paths are prose, not links",
        "Upstream called it `prompts/ir-schema.md`, or `REFERENCE.md`, or "
        "`skills/x/reference/y.md`.",
        [],
    ),
    (
        "a real link beside a path-shaped code span",
        "Compare `prompts/ir-schema.md` with [ours](reference/ir-schema.md).",
        ["reference/ir-schema.md"],
    ),
    # `../` is passed straight through. Deciding what it means is the caller's
    # job: lint_skills.py rejects it outright, check_install.py resolves it and
    # says so in its `UNVERIFIABLE` list. A filter here would silently remove
    # the rule lint_skills.py is built on.
    ("a parent-relative link is passed through", "See [s](../shared/x.md).", ["../shared/x.md"]),
    ("several links on one line", "[a](one.md) then [b](two.md).", ["one.md", "two.md"]),
    ("a link across a table cell", "| CLI | [ref](reference/cli.md) |", ["reference/cli.md"]),
    ("an image is a link too", "![diagram](reference/flow.png)", ["reference/flow.png"]),
    ("an empty target matches nothing", "Broken [link]() here.", []),
    ("text with no links at all", "# Heading\n\nJust prose.\n", []),
    ("a link whose text contains brackets", "See [a [b] c](reference/d.md).", ["reference/d.md"]),
)

FRAGMENTS: tuple[tuple[str, str, str], ...] = (
    ("no fragment", "reference/detail.md", "reference/detail.md"),
    ("one fragment", "reference/detail.md#why", "reference/detail.md"),
    # Split once, so a `#` inside the fragment cannot eat the rest of the path.
    ("two fragments", "reference/detail.md#a#b", "reference/detail.md"),
    ("fragment only", "#heading", ""),
    ("parent-relative keeps its prefix", "../shared/x.md#z", "../shared/x.md"),
)


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    for name, text, want in EXTRACTION:
        got = list(local_link_targets(text))
        checks.append((f"extract: {name}", got == want, f"wanted {want}, got {got}"))

    for name, target, want in FRAGMENTS:
        got = link_path(target)
        checks.append((f"fragment: {name}", got == want, f"wanted {want!r}, got {got!r}"))

    # The whole-module guard: a regex that stopped matching would turn every
    # case above with an empty expectation green while breaking both gates. So
    # assert that something is extracted at all.
    extracted = sum(len(list(local_link_targets(t))) for _n, t, _w in EXTRACTION)
    checks.append((
        "the extractor matches something at all",
        extracted > 0,
        f"extracted {extracted} target(s) across {len(EXTRACTION)} fixtures — the "
        f"regex matches nothing, so both gates would report no findings",
    ))

    failures = 0
    for name, ok, detail in checks:
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"           {detail}")

    print()
    if failures:
        print(
            f"{failures} of {len(checks)} link-extractor tests failed — both gates "
            f"resolve links through this module",
            file=sys.stderr,
        )
        return 1
    print(f"all {len(checks)} link-extractor tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
