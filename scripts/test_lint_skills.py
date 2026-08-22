#!/usr/bin/env python3
"""Tests for the skills linter.

Every case here is a defect that got past `claude plugin validate --strict` in
practice. A linter nobody has pointed at a broken fixture is not a gate, so each
rule is asserted by building the broken thing and requiring a non-zero exit.

Run: python3 scripts/test_lint_skills.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LINTER = REPO / "scripts" / "lint_skills.py"

GOOD = """---
name: {name}
description: A short, valid description that stays well inside the character cap.
---

# Heading

Body text.
"""


def run_linter(root: Path) -> subprocess.CompletedProcess:
    """Run the linter against a throwaway repo root.

    The linter derives its repo root as `__file__/../..`, so it has to live in a
    `scripts/` subdirectory of the fixture — not at the fixture root. Getting
    this wrong made every rejection below spurious: each case failed with "no
    skills/ directory" rather than on its own defect, and the suite reported
    eleven passes that proved nothing. The control case is what caught it, which
    is the whole reason a control case is here.
    """
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(LINTER, scripts / "lint_skills.py")
    return subprocess.run(
        [sys.executable, str(scripts / "lint_skills.py")],
        cwd=root,
        capture_output=True,
        text=True,
    )


def case(name: str, build) -> tuple[str, bool, str]:
    """Build a fixture repo, lint it, return (name, rejected, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "skills").mkdir()
        build(root / "skills")
        proc = run_linter(root)
        return name, proc.returncode != 0, (proc.stderr + proc.stdout).strip()


def write(skills: Path, dirname: str, content: str) -> None:
    d = skills / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


def main() -> int:
    cases = []

    # The control: a valid skill must PASS, or every other case below proves
    # nothing except that the linter rejects everything.
    cases.append(case("a valid skill passes", lambda s: write(s, "ok-skill", GOOD.format(name="ok-skill"))))

    cases.append(case(
        "name disagreeing with its directory",
        lambda s: write(s, "real-dir", GOOD.format(name="WRONG-NAME")),
    ))

    cases.append(case(
        "description over the 260 cap",
        lambda s: write(s, "long-desc", "---\nname: long-desc\ndescription: " + ("x" * 400) + "\n---\n\nBody.\n"),
    ))

    # The worst failure mode: validate --strict passes this, and it only breaks
    # when a client tries to load the skill.
    cases.append(case(
        "frontmatter that is not valid YAML (colon-space in a plain scalar)",
        lambda s: write(s, "bad-yaml", "---\nname: bad-yaml\ndescription: covers project: App IDs and more\n---\n\nBody.\n"),
    ))

    cases.append(case(
        "a Claude-Code-only frontmatter key",
        lambda s: write(s, "extra-key", "---\nname: extra-key\ndescription: Fine.\nallowed-tools: Read\n---\n\nBody.\n"),
    ))

    cases.append(case(
        "a link escaping the skill directory with ../",
        lambda s: write(s, "escapes", "---\nname: escapes\ndescription: Fine.\n---\n\nSee [shared](../shared/thing.md).\n"),
    ))

    cases.append(case(
        "a local link that does not resolve",
        lambda s: write(s, "dangling", "---\nname: dangling\ndescription: Fine.\n---\n\nSee [ref](references/missing.md).\n"),
    ))

    cases.append(case(
        "a CLI flag removed in v1.63.0",
        lambda s: write(s, "dead-flag", "---\nname: dead-flag\ndescription: Fine.\n---\n\nRun `diagrid project create x --enable-agent-infrastructure`.\n"),
    ))

    # The gate's first real run rejected three legitimate counter-examples. Both
    # directions are now pinned: an unacknowledged banned string still fails, and
    # an acknowledged one passes.
    cases.append(case(
        "an acknowledged counter-example is allowed",
        lambda s: write(s, "counter-ex", "---\nname: counter-ex\ndescription: Fine.\n---\n\nThere is no `Diagrid.Agents.Workflow` package; never write it.\n\n<!-- lint-allow-banned: Diagrid.Agents.Workflow — taught as a coordinate that 404s -->\n"),
    ))

    cases.append(case(
        "a NuGet id that returns 404",
        lambda s: write(s, "bad-pkg", "---\nname: bad-pkg\ndescription: Fine.\n---\n\nAdd `Diagrid.Agents.Workflow`.\n"),
    ))

    cases.append(case(
        "no description at all",
        lambda s: write(s, "no-desc", "---\nname: no-desc\n---\n\nBody.\n"),
    ))

    cases.append(case(
        "no frontmatter at all",
        lambda s: write(s, "no-fm", "# Just a heading\n\nBody.\n"),
    ))

    def too_many(s: Path) -> None:
        for i in range(13):
            write(s, f"skill-{i:02d}", GOOD.format(name=f"skill-{i:02d}"))

    cases.append(case("more than 12 skills", too_many))

    # Report. The control expects PASS; everything else expects REJECT.
    failures = 0
    for i, (name, rejected, output) in enumerate(cases):
        expect_reject = i != 0 and 'is allowed' not in name
        ok = rejected == expect_reject
        if not ok:
            failures += 1
        verdict = "ok  " if ok else "FAIL"
        wanted = "reject" if expect_reject else "pass"
        got = "rejected" if rejected else "passed"
        print(f"  {verdict}  {name}\n           wanted {wanted}, got {got}")
        if not ok:
            print(f"           linter said:\n{output}\n")

    print()
    if failures:
        print(f"{failures} of {len(cases)} linter tests failed — the gate does not catch what it claims", file=sys.stderr)
        return 1
    print(f"all {len(cases)} linter tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
