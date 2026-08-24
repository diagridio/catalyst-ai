#!/usr/bin/env python3
"""Tests for the real-installer gate.

Two kinds of case, for two different reasons.

The layout checks are pure and build an installed tree by hand. They are the
only way to assert the *shape* properties, because you cannot make the real
installer produce a wrong shape on demand: `--copy` mode either symlinks or it
does not, and if it ever starts symlinking the gate has to say so rather than
pass. Building the wrong tree by hand is how you find out the assertion fires.

The installer cases run the real `npx skills` against a throwaway source tree,
because the whole claim of this gate is that it exercises the command the docs
tell users to run. A stub would only prove the assertions are self-consistent
with a fixture written from the same assumptions.

Both borrow the two load-bearing habits from scripts/test_lint_skills.py, whose
own first version was vacuous:

The control cases must PASS. Four rejections prove nothing if the gate rejects
everything, and that failure mode is easy to reach here — a fixture the
installer cannot read at all rejects for the wrong reason and looks like a win.

`must_say` is asserted, not just the exit code. "installed nothing" and
"`reference/missing.md` does not resolve" are the same exit code and very
different gates, and the message is the deliverable.

Run: python3 scripts/test_check_install.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_install
from check_install import AGENT_ROOTS, CONTENT_ROOT, LOCK_FILE, MODES, Findings

GATE = Path(__file__).resolve().parent / "check_install.py"

BODY = "---\nname: {name}\ndescription: A fixture skill, well inside the cap.\n---\n\n{extra}"

# Each case is an independent gate process that itself shells out to npx. Four
# keeps a two-core runner honest while still cutting the wall clock.
_WORKERS = 4

_DEFAULT = next(m for m in MODES if not m.flags)
_COPY = next(m for m in MODES if m.flags)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def write_skill(skills: Path, name: str, extra: str = "") -> Path:
    """One skill in a source tree, with a reference file its SKILL.md links to."""
    skill = skills / name
    (skill / "reference").mkdir(parents=True, exist_ok=True)
    (skill / "reference" / "detail.md").write_text("# Detail\n", encoding="utf-8")
    (skill / "SKILL.md").write_text(
        BODY.format(name=name, extra="See [detail](reference/detail.md).\n" + extra),
        encoding="utf-8",
    )
    return skill


def two_skills(source: Path) -> None:
    for name in ("fixture-alpha", "fixture-beta"):
        write_skill(source / "skills", name)


def fake_install(
    root: Path,
    names: Sequence[str],
    *,
    symlink: bool,
    absolute: bool = False,
    omit_from_agent: Sequence[str] = (),
    lock_names: Sequence[str] | None = None,
    dangling_link: bool = False,
    code_span: bool = False,
) -> None:
    """An installed layout built by hand, optionally with one defect in it."""
    content = root / CONTENT_ROOT
    content.mkdir(parents=True)
    for name in names:
        (content / name / "reference").mkdir(parents=True)
        (content / name / "reference" / "detail.md").write_text("# Detail\n", encoding="utf-8")
        extra = ""
        if dangling_link:
            extra += "And [gone](reference/missing.md).\n"
        if code_span:
            # The trap. These are prose in the real tree, crediting upstream.
            extra += "Upstream called it `prompts/ir-schema.md`, or `REFERENCE.md`.\n"
        (content / name / "SKILL.md").write_text(
            BODY.format(name=name, extra="See [detail](reference/detail.md).\n" + extra),
            encoding="utf-8",
        )

    for agent_root in AGENT_ROOTS:
        if agent_root == CONTENT_ROOT:
            continue
        target_dir = root / agent_root
        target_dir.mkdir(parents=True)
        depth_up = Path(*[".."] * len(Path(agent_root).parts))
        for name in names:
            if name in omit_from_agent:
                continue
            if symlink:
                target = content / name if absolute else depth_up / CONTENT_ROOT / name
                (target_dir / name).symlink_to(target, target_is_directory=True)
            else:
                shutil.copytree(content / name, target_dir / name)

    recorded = names if lock_names is None else lock_names
    (root / LOCK_FILE).write_text(
        json.dumps({"version": 1, "skills": {n: {"sourceType": "local"} for n in recorded}}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# Layout checks — pure, no npx
# --------------------------------------------------------------------------


def layout_checks() -> list[tuple[str, bool, str]]:
    names = ["fixture-alpha", "fixture-beta"]
    checks: list[tuple[str, bool, str]] = []

    def verdict(build_kwargs: dict, mode) -> Findings:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "installed"
            root.mkdir()
            fake_install(root, names, **build_kwargs)
            f = Findings()
            check_install.check_layout(root, names, mode, f)
            check_install.check_links(root, names, mode, f)
            return f

    def add(name: str, build_kwargs: dict, mode, want_errors: bool) -> None:
        f = verdict(build_kwargs, mode)
        got = bool(f.errors)
        checks.append((
            name,
            got == want_errors,
            f"wanted {'errors' if want_errors else 'none'}, got: {f.errors or 'none'}",
        ))

    # The controls. Without these, every rejection below is consistent with a
    # checker that rejects any tree it is shown.
    add("a correct default-mode layout is accepted", {"symlink": True}, _DEFAULT, False)
    add("a correct copy-mode layout is accepted", {"symlink": False}, _COPY, False)

    # The one the brief singles out, and the reason this gate reuses
    # skill_links rather than growing its own regex: a code span that looks
    # like a path is prose. Three of these are correct as written in the real
    # tree and a hand-rolled checker flagged all three.
    add(
        "an inline code span that looks like a path is not flagged",
        {"symlink": True, "code_span": True},
        _DEFAULT,
        False,
    )

    add(
        "a markdown link that does not resolve in the installed layout",
        {"symlink": True, "dangling_link": True},
        _DEFAULT,
        True,
    )
    add(
        "the same dangling link through a real copy",
        {"symlink": False, "dangling_link": True},
        _COPY,
        True,
    )

    add(
        "a skill missing from an agent directory",
        {"symlink": True, "omit_from_agent": ["fixture-beta"]},
        _DEFAULT,
        True,
    )

    # If `--copy` mode ever starts symlinking, the agent directories stop being
    # independently self-contained and nobody finds out from an exit code.
    add("copy mode with symlinked entries", {"symlink": True}, _COPY, True)

    # And the mirror: if default mode ever stops symlinking, this gate is no
    # longer testing symlink traversal at all — a vacuous pass, which is the
    # failure mode worth the most here.
    add("default mode with copied entries", {"symlink": False}, _DEFAULT, True)

    # An absolute symlink resolves today and breaks the moment the project
    # directory is moved or renamed.
    add(
        "default mode with an absolute symlink",
        {"symlink": True, "absolute": True},
        _DEFAULT,
        True,
    )

    add(
        "a lock file that does not record every installed skill",
        {"symlink": True, "lock_names": ["fixture-alpha"]},
        _DEFAULT,
        True,
    )

    return checks


# --------------------------------------------------------------------------
# Installer cases — the real npx
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    name: str
    build: Callable[[Path], object]
    expect: str = "reject"
    must_say: str | None = None
    modes: tuple[str, ...] = ("default",)


@dataclass(frozen=True)
class Result:
    spec: Spec
    rejected: bool
    output: str

    @property
    def ok(self) -> bool:
        if self.rejected != (self.spec.expect == "reject"):
            return False
        return not self.spec.must_say or self.spec.must_say in self.output


def warm_npx() -> str | None:
    """Populate the npx cache once, serially. Returns a reason it could not.

    Every case below is a separate gate process running
    `npx --yes skills@<pinned>`, and npx unpacks that package into ONE cache
    directory keyed by the spec, whatever the concurrency. Four processes racing
    to create it is how this suite first went red, on macos CI only:

        npm error code ENOTEMPTY
        npm error ENOTEMPTY: directory not empty, rmdir
          '/Users/runner/.npm/_npx/<hash>/node_modules/yallist/dist'

    npm exited 190, the gate faithfully reported "the installer exited 190",
    and the case was rejected for a reason with nothing to do with its fixture.
    Worth dwelling on: the pass/fail verdict was still *correct*, because the
    case expected a rejection. `must_say` is the only reason anyone found out —
    which is exactly the argument for asserting on the message and not the
    exit code.

    `--help` rather than `add`: it populates the same cache entry and touches
    nothing else.
    """
    proc = subprocess.run(
        ["npx", "--yes", check_install.SKILLS_PACKAGE, "--help"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900,
    )
    if proc.returncode != 0:
        return f"exit {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-300:]}"
    return None


def run_case(spec: Spec) -> Result:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        spec.build(source)
        argv = [sys.executable, str(GATE), "--source", str(source)]
        for mode in spec.modes:
            argv += ["--mode", mode]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        return Result(spec, proc.returncode != 0, (proc.stdout + proc.stderr).strip())


def shadowing_root_skill(source: Path) -> None:
    """A root SKILL.md, which makes the installer ignore the whole skills/ tree.

    Verified on skills@1.5.22 and 1.5.23 against the real repo: with a root
    SKILL.md present the installer reports `Found 1 skill`, installs that one,
    and exits 0 — nine of the ten silently never arrive. This is the case that
    makes the positive count assertion load-bearing rather than decorative. An
    exit-code check is green here, and so is a check that merely asserts
    "something got installed".
    """
    two_skills(source)
    (source / "SKILL.md").write_text(
        BODY.format(name="source", extra="A root skill that shadows the tree.\n"),
        encoding="utf-8",
    )


def dangling_link(source: Path) -> None:
    two_skills(source)
    write_skill(source / "skills", "fixture-gamma", extra="And [gone](reference/missing.md).\n")


def escaping_link(source: Path) -> None:
    two_skills(source)
    write_skill(source / "skills", "fixture-gamma", extra="See [shared](../shared/thing.md).\n")


SPECS = (
    # The control, in both modes. If this does not pass, nothing below means
    # anything.
    Spec(
        "a valid source tree installs in both modes",
        two_skills,
        expect="pass",
        must_say="every installed skill resolves",
        modes=("default", "copy"),
    ),
    Spec(
        "a root SKILL.md that shadows the skills/ tree",
        shadowing_root_skill,
        must_say="missing",
    ),
    Spec(
        "a link that does not resolve once installed",
        dangling_link,
        must_say="does not resolve",
        modes=("default", "copy"),
    ),
    Spec(
        "a link that escapes the skill directory",
        escaping_link,
        must_say="does not resolve",
        modes=("default", "copy"),
    ),
    # Nothing to install must never read as nothing wrong. This one never
    # reaches npx, which is the point: the guard is before the install.
    Spec(
        "a source tree with no skills at all",
        lambda source: (source / "skills").mkdir(),
        must_say="no skills",
    ),
    Spec(
        "a source tree with no skills directory",
        lambda source: (source / "README.md").write_text("nothing here\n", encoding="utf-8"),
        must_say="no skills",
    ),
)


def main() -> int:
    started = time.monotonic()
    failures = 0

    checks = layout_checks()
    for name, ok, detail in checks:
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  layout: {name}")
        if not ok:
            print(f"           {detail}")

    # Before any fan-out. A failure here is the environment, not a finding, and
    # saying so beats six cases all blaming their own fixtures.
    reason = warm_npx()
    if reason is not None:
        print(f"\ncannot warm the npx cache, so nothing below would mean "
              f"anything — {reason}", file=sys.stderr)
        return 1

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(run_case, SPECS))

    for r in results:
        failures += not r.ok
        got = "rejected" if r.rejected else "passed"
        print(f"  {'ok  ' if r.ok else 'FAIL'}  {r.spec.name}\n"
              f"           wanted {r.spec.expect}, got {got}")
        if not r.ok:
            if r.spec.must_say and r.spec.must_say not in r.output:
                print(f"           expected the message to contain: {r.spec.must_say!r}")
            print(f"           gate said:\n{r.output}\n")

    total = len(checks) + len(results)
    print(f"\n{total} checks in {time.monotonic() - started:.0f}s")
    if failures:
        print(
            f"{failures} of {total} installer-gate tests failed — the gate does not "
            f"catch what it claims",
            file=sys.stderr,
        )
        return 1
    print(f"all {total} installer-gate tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
