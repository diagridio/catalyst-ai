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
SCRIPTS = REPO / "scripts"

# Every module the linter needs at the fixture root. `skill_links` is imported
# rather than inlined so that this gate and scripts/check_install.py cannot
# disagree about what counts as a link; the cost is that the fixture needs it
# too, and forgetting it fails every case with an ImportError that looks like a
# defect in the case.
MODULES = ("lint_skills.py", "skill_links.py")

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
    for module in MODULES:
        shutil.copy(SCRIPTS / module, scripts / module)
    return subprocess.run(
        [sys.executable, str(scripts / "lint_skills.py")],
        cwd=root,
        capture_output=True,
        text=True,
    )


def case(name: str, build, expect: str = "reject") -> tuple[str, str, bool, str]:
    """Build a fixture repo, lint it, return (name, expect, rejected, output).

    `expect` is explicit rather than inferred from the case name: the suite has
    more than one pass-expected case now, and deducing intent from wording is
    how a test suite silently starts asserting the opposite of what it reads.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "skills").mkdir()
        build(root / "skills")
        proc = run_linter(root)
        return name, expect, proc.returncode != 0, (proc.stderr + proc.stdout).strip()


def write(skills: Path, dirname: str, content: str) -> None:
    d = skills / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


def main() -> int:
    cases = []

    # The control: a valid skill must PASS, or every other case below proves
    # nothing except that the linter rejects everything.
    cases.append(case(
        "a valid skill passes",
        lambda s: write(s, "ok-skill", GOOD.format(name="ok-skill")),
        expect="pass",
    ))

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
        "a frontmatter key outside name/description",
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
        expect="pass",
    ))

    cases.append(case(
        "a NuGet id that returns 404",
        lambda s: write(s, "bad-pkg", "---\nname: bad-pkg\ndescription: Fine.\n---\n\nAdd `Diagrid.Agents.Workflow`.\n"),
    ))

    # The flag that shipped. It reads like a plural of `appid`, which is exactly
    # why review missed it twice.
    cases.append(case(
        "a flag that does not exist on any command",
        lambda s: write(s, "bad-flag", "---\nname: bad-flag\ndescription: Fine.\n---\n\nRun `diagrid project logs --appids x --type dapr`.\n"),
    ))

    cases.append(case(
        "no description at all",
        lambda s: write(s, "no-desc", "---\nname: no-desc\n---\n\nBody.\n"),
    ))

    cases.append(case(
        "no frontmatter at all",
        lambda s: write(s, "no-fm", "# Just a heading\n\nBody.\n"),
    ))

    # Descriptions alike enough to compete for the same trigger. This is the
    # defect the gate missed on the real set: two scaffold skills sharing
    # "add, create or generate ..." and "Detects the language rather than
    # asking", which scored 0.296 against a 0.20 cap.
    def colliding(s: Path) -> None:
        tmpl = ("---\nname: {n}\ndescription: Scaffold a {thing} on the platform. "
                "Use when someone wants to add, create or generate a {thing}, or asks how "
                "to run {thing} code. Detects the language rather than asking.\n---\n\nBody.\n")
        write(s, "scaffold-alpha", tmpl.format(n="scaffold-alpha", thing="workflow"))
        write(s, "scaffold-beta", tmpl.format(n="scaffold-beta", thing="agent"))

    cases.append(case("descriptions that compete for the same trigger", colliding))

    # The control for that rule, and the one that keeps it honest. These two are
    # genuinely adjacent — both are about reviewing the body of a workflow — and
    # they are the real pair that measured 0.116. A rule that flags them is
    # useless, because it would force apart skills that SHOULD sit next to each
    # other and differ only in their subject nouns.
    def adjacent(s: Path) -> None:
        write(s, "determinism", "---\nname: determinism\ndescription: Replay-safety rails for "
              "the body of an orchestrator. Use when writing or reviewing code inside a workflow "
              "function, or when a run diverges on replay — clocks, randomness, ids, iteration "
              "order, direct I/O, threads and mutable global state.\n---\n\nBody.\n")
        write(s, "idempotency", "---\nname: idempotency\ndescription: Make activities safe to "
              "run twice. Use when writing or reviewing an activity body with a side effect — "
              "payment, email, write, third-party call — or when a retry produced a duplicate. "
              "Activities execute at least once.\n---\n\nBody.\n")

    cases.append(case(
        "genuinely adjacent skills are not forced apart",
        adjacent,
        expect="pass",
    ))

    def too_many(s: Path) -> None:
        for i in range(13):
            write(s, f"skill-{i:02d}", GOOD.format(name=f"skill-{i:02d}"))

    cases.append(case("more than 12 skills", too_many))

    # The scope rule, which lives in two skills' prose because this repo has no
    # shared-fragment mechanism. The defect being guarded is real and measured:
    # before the rule existed, "is anything broken in my project?" made
    # catalyst-operate read every project in a ten-project organization, well
    # over half its calls landing on projects nobody asked about. The rule then
    # went into catalyst-operate only — and the very next measured run routed to
    # catalyst-debug instead, which did not have it. Same question, same defect,
    # different front door. That is what this case exists to stop recurring.
    SCOPED = ("---\nname: {n}\ndescription: {d}\n---\n\n"
              "Resolve the current project, name it, and stay inside it.\n\n"
              "Widening the scope is a decision you state first.\n")
    OPERATE_D = ("Inspect a running project read-only — what is deployed, what "
                 "state it sits in, which quota is close.")
    DEBUG_D = ("Diagnose why a resource is stuck, then stop, kill or rerun a run. "
               "Covers a failed run, an unready App ID, a silent agent.")

    def scope_rule_dropped(s: Path) -> None:
        write(s, "catalyst-operate", SCOPED.format(n="catalyst-operate", d=OPERATE_D))
        # catalyst-debug keeps its body but loses the bounding rule entirely.
        write(s, "catalyst-debug",
              f"---\nname: catalyst-debug\ndescription: {DEBUG_D}\n---\n\n"
              "Route by symptom, then read the project.\n")

    cases.append(case("a scope-bounded skill that lost the one-project rule", scope_rule_dropped))

    # Control for that rule: both skills carrying it must pass, or the gate would
    # fail the very state it is meant to protect.
    def scope_rule_present(s: Path) -> None:
        write(s, "catalyst-operate", SCOPED.format(n="catalyst-operate", d=OPERATE_D))
        write(s, "catalyst-debug", SCOPED.format(n="catalyst-debug", d=DEBUG_D))

    cases.append(case(
        "both scope-bounded skills carrying the rule",
        scope_rule_present,
        expect="pass",
    ))

    # Report. The control expects PASS; everything else expects REJECT.
    failures = 0
    for name, expect, rejected, output in cases:
        expect_reject = expect == "reject"
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
