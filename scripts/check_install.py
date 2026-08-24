#!/usr/bin/env python3
"""Install the skills with the real `npx skills` and check what actually landed.

scripts/lint_skills.py already has `check_isolation`, which copies each skill
alone into a temp directory with `shutil.copytree` and asserts every link
resolves. That gate is good and this one does not replace it. But a copytree is
not what an install looks like, and it never runs the command the README tells
people to run.

Two things follow from that. First, the installed layout is not a flat copy: in
default mode `npx skills` writes the content once into `.agents/skills/<name>/`
and makes each other agent directory a symlink into it, so every relative link
is resolved *through a symlink*, which is a different traversal from the one a
copytree exercises. With `--copy` each agent directory gets its own real copy
instead. Both are documented modes and only one of them was being tested, by
proxy.

Second, and this is why the gate asserts a positive count rather than an exit
code: `npx skills add` exits 0 having installed nothing more than one way.

  A root `SKILL.md` in the source tree shadows the whole `skills/` directory.
  Verified on 1.5.22 and 1.5.23 against this repo: the installer reports
  `Found 1 skill`, installs that one, ignores the tree, and exits 0. Nine
  skills silently never arrive and nothing in the output reads as a failure.

  With nothing to prompt from — no terminal, and none of the environment that
  makes the installer announce "Agent detected" — and no `-y`, it finds the
  skills, installs none of them, and exits 0. That is a GitHub Actions runner
  exactly, so an exit-status check is worth the least in the place this gate
  runs.

So the count is the assertion, and it is derived from the repo's own `skills/`
directory rather than written down as `10`, because a hardcoded number is a gate
that gets weaker every time someone adds a skill.

The agent list uses repeated `-a` flags. `-a claude-code,codex,github-copilot`
is not the same thing: both 1.5.22 and 1.5.23 read the whole comma-joined string
as one unknown agent name, print `Invalid agents:`, and install nothing.

Everything happens in a throwaway directory, from the local checkout rather
than from GitHub — so the gate needs no credentials, and it tests the working
tree instead of what is already on main.

Run: python3 scripts/check_install.py [--source PATH] [--mode default|copy]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from skill_links import link_path, local_link_targets

REPO = Path(__file__).resolve().parent.parent

# Pinned, for the same reason the Diagrid CLI is pinned in .diagrid-cli-version:
# every behaviour asserted below was verified against this exact version, and an
# unpinned installer would make a red run ambiguous between "the skills broke"
# and "the installer changed". Bumping this is a deliberate act — re-verify the
# symlink layout and the agent list when you do.
SKILLS_PACKAGE = "skills@1.5.22"

# The three clients this repo ships for. Passed as REPEATED `-a` flags, never
# comma-joined — see the module docstring.
AGENTS = ("claude-code", "codex", "github-copilot")

# Where `npx skills` puts the content itself. Also the directory Codex and
# GitHub Copilot read from directly: 1.5.22 calls them "universal" agents and
# gives them no directory of their own, which is why there is no `.codex/` or
# `.github/` path below. Discovered by running it, not assumed.
CONTENT_ROOT = ".agents/skills"

# Every directory an agent reads skills from, and which agents read it. If a
# future version starts giving Codex or Copilot its own directory, the set
# comparison in `check_layout` fails on the untouched path rather than passing
# because it never looked.
AGENT_ROOTS: dict[str, tuple[str, ...]] = {
    CONTENT_ROOT: ("codex", "github-copilot"),
    ".claude/skills": ("claude-code",),
}

# The installer's own bookkeeping, and what `skills experimental_install`
# restores from. Structured output, unlike the boxed terminal report, so it is
# worth cross-checking against the filesystem.
LOCK_FILE = "skills-lock.json"

# Generous: the first run in a cold CI job downloads the package.
INSTALL_TIMEOUT = 900

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# npm failing on its own account, as distinct from the installer failing. Two
# concurrent `npx` invocations race on one shared cache directory keyed by the
# package spec, and the loser gets `ENOTEMPTY: directory not empty, rmdir
# ~/.npm/_npx/<hash>/node_modules/...` and exit 190. That reads nothing like a
# skills defect and must not be reported as one — it sent a maintainer looking
# at a fixture once already.
_NPM_FAILURE = re.compile(r"^npm (?:error|ERR!)", re.MULTILINE)

# Stated in the gate's own output so a green run is not read as more assurance
# than it is.
UNVERIFIABLE = [
    "Skill content. Whether a command exists, a flag is spelled right or a "
    "description will trigger is scripts/lint_skills.py and "
    "scripts/check_cli_surface.py — this gate only asks whether what the "
    "installer wrote is complete and internally resolvable.",
    "Global installs (`npx skills add -g`), which write into the user's home "
    "directory. Everything here happens inside a throwaway directory on "
    "purpose; a CI gate should not be editing ~/.claude.",
    "Installing from `diagridio/catalyst-ai` over the network. The source is "
    "the local checkout, so the gate needs no GitHub auth and tests the working "
    "tree rather than what is already on main. The one thing that buys nothing "
    "is coverage of the remote-fetch path itself.",
    "Windows. `npx skills` cannot create a symlink there without Developer "
    "Mode or an elevated shell, so default mode either falls back to copying or "
    "fails outright — a different assertion, not this one. Running the matrix "
    "there would either pass vacuously or fail for a reason that says nothing "
    "about this repo.",
    "Whether an agent then LOADS what landed. That the bytes are in the right "
    "place with working links is necessary, not sufficient; the eval suite in "
    "evals/ is what measures triggering.",
    "Single-agent installs, which is what the README actually shows (`-a "
    "github-copilot` on its own). Installing all three at once writes a superset "
    "of the directories, so this is a coverage gap rather than a blind spot — "
    "what it does not prove is that a lone `-a codex` still produces a complete "
    "`.agents/skills`.",
    "Whether a link ESCAPES its own skill with `../`. This gate installs "
    "everything at once (`-s '*'`), so `../other-skill/SKILL.md` genuinely "
    "resolves here — and would genuinely break for anyone who installed that "
    "skill on its own. That is a real and different property, owned by "
    "`check_skill` and `check_isolation` in lint_skills.py, which ban `../` "
    "outright and install each skill alone. Repeating the rule here would be "
    "duplication; leaving it unsaid would let 'every installed skill resolves' "
    "read as more than it means.",
]


@dataclass(frozen=True)
class Mode:
    """One documented install mode, and the layout it is supposed to produce."""

    name: str
    flags: tuple[str, ...]
    # Whether the non-content agent directories hold symlinks into CONTENT_ROOT.
    symlinked: bool
    what: str


MODES: tuple[Mode, ...] = (
    Mode(
        "default",
        (),
        True,
        "content once in .agents/skills, every other agent directory a symlink into it",
    ),
    Mode(
        "copy",
        ("--copy",),
        False,
        "a real, independent copy in every agent directory",
    ),
)

MODE_BY_NAME = {mode.name: mode for mode in MODES}


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where} mode: {msg}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)


@dataclass(frozen=True)
class Coverage:
    """What the link check actually read, so a silent no-op is visible."""

    files: int = 0
    links: int = 0


# --------------------------------------------------------------------------
# Running the installer
# --------------------------------------------------------------------------


def expected_skills(source: Path) -> list[str]:
    """The skills the source tree offers — the same rule lint_skills.py uses."""
    skills_dir = source / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        p.name for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def installer_argv(source: Path, mode: Mode) -> list[str]:
    """The exact command, with one `-a` per agent.

    The comma form `-a claude-code,codex,github-copilot` reads as one unknown
    agent name on 1.5.22 and installs nothing, so this builds repeated flags and
    there is a test asserting the shape.
    """
    argv = ["npx", "--yes", SKILLS_PACKAGE, "add", str(source)]
    for agent in AGENTS:
        argv += ["-a", agent]
    argv += ["-s", "*", "-y", *mode.flags]
    return argv


def clean_output(proc: subprocess.CompletedProcess) -> str:
    """The installer's output with its cursor and colour escapes removed."""
    raw = (proc.stdout or "") + (proc.stderr or "")
    return _ANSI.sub("", raw.replace("\r", ""))


def run_installer(source: Path, dest: Path, mode: Mode) -> tuple[int, str]:
    """Install into `dest`, returning (exit status, cleaned output).

    `stdin` is closed rather than inherited, so the installer can never block
    waiting for an answer nobody is going to type. That is also why `-y` is not
    optional in `installer_argv`: with no terminal and no `-y`, this installer
    finds the skills, installs none of them, and exits 0 — the failure the
    count assertion exists to catch, reproduced here every run.
    """
    try:
        proc = subprocess.run(
            installer_argv(source, mode),
            cwd=dest,
            capture_output=True,
            text=True,
            # Pinned rather than left to the locale, matching every read_text in
            # this repo. A runner with a C locale would otherwise fail to decode
            # the installer's box-drawing output and raise mid-check.
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 1, f"the installer did not finish within {INSTALL_TIMEOUT}s"
    return proc.returncode, clean_output(proc)


def tail(text: str, lines: int = 12) -> str:
    kept = [line for line in text.splitlines() if line.strip()][-lines:]
    return "\n     ".join(kept)


# --------------------------------------------------------------------------
# Checking what landed
# --------------------------------------------------------------------------


def markdown_files(root: Path) -> Iterator[Path]:
    """Every `.md` under `root`, following symlinks.

    `followlinks=True` is defensive rather than load-bearing, and it is worth
    being precise about which, because the obvious justification is wrong.
    Measured on 3.14 against a real default-mode layout:

        from the SKILL root (itself the symlink, which is how this is called)
            rglob, os.walk, os.walk(followlinks=True)   all find every file
        from the AGENT root (whose children are the symlinks)
            rglob -> nothing, os.walk -> nothing, followlinks=True -> everything

    So at this call site the flag changes nothing today: a symlink handed to a
    walk as its starting point is followed either way. It earns its place
    against the two ways that stops being true — a caller that walks one level
    up, and a skill that ever contains a symlinked subdirectory — both of which
    would otherwise read zero files and report no findings, which looks exactly
    like a clean tree. The non-zero assertions in `check_links` and `report` are
    what actually catch that, and a mutation that swaps this for `rglob`
    survives the test suite precisely because the two are equivalent here.
    """
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
        for filename in sorted(filenames):
            if filename.endswith(".md"):
                yield Path(dirpath) / filename


def _check_entry(
    dest: Path, agent_root: str, name: str, mode: Mode, f: Findings
) -> None:
    """The shape of one installed skill under one agent directory."""
    entry = dest / agent_root / name
    where = f"{agent_root}/{name}"

    if agent_root == CONTENT_ROOT:
        # The content root holds the files themselves in both modes.
        if entry.is_symlink() or not entry.is_dir():
            f.error(
                mode.name,
                f"{where} is not a real directory, but {CONTENT_ROOT} is where "
                f"`npx skills` puts the content itself",
            )
    elif mode.symlinked:
        if not entry.is_symlink():
            f.error(
                mode.name,
                f"{where} is not a symlink. Default mode writes content once "
                f"into {CONTENT_ROOT} and links every other agent directory "
                f"into it; if it stops doing that, this gate is no longer "
                f"resolving links through a symlink and passes vacuously.",
            )
        else:
            link = os.readlink(entry)
            if os.path.isabs(link):
                f.error(
                    mode.name,
                    f"{where} is an absolute symlink to `{link}`. It resolves "
                    f"here and breaks the moment the project directory is moved "
                    f"or renamed.",
                )
            elif entry.resolve() != (dest / CONTENT_ROOT / name).resolve():
                f.error(
                    mode.name,
                    f"{where} points at `{link}`, which is not "
                    f"{CONTENT_ROOT}/{name}",
                )
    else:
        if entry.is_symlink():
            f.error(
                mode.name,
                f"{where} is a symlink. The whole point of `--copy` is that "
                f"each agent directory is independently self-contained.",
            )
        else:
            linked = sorted(
                str(p.relative_to(entry))
                for dirpath, dirnames, filenames in os.walk(entry)
                for p in (Path(dirpath) / n for n in dirnames + filenames)
                if p.is_symlink()
            )
            if linked:
                f.error(
                    mode.name,
                    f"{where} contains {len(linked)} symlink(s) under `--copy`: "
                    f"{', '.join(linked[:5])}",
                )

    if not (entry / "SKILL.md").is_file():
        f.error(mode.name, f"{where}/SKILL.md is not a readable file as installed")


def check_layout(dest: Path, expected: Sequence[str], mode: Mode, f: Findings) -> None:
    """Every agent directory holds every skill, in the shape this mode promises."""
    want = set(expected)

    for agent_root, agents in AGENT_ROOTS.items():
        who = ", ".join(agents)
        root = dest / agent_root
        if not root.is_dir():
            f.error(
                mode.name,
                f"{agent_root} does not exist, so nothing was installed for {who}",
            )
            continue

        found = {p.name for p in root.iterdir() if not p.name.startswith(".")}
        # The count is compared against the source list rather than the set
        # built from it, so this stays a real assertion about "as many skills as
        # the repo offers" rather than a restatement of the set comparison next
        # to it. The count is the contract — see the module docstring — and it
        # should not quietly become implicit if someone relaxes the set check.
        if len(found) != len(expected) or found != want:
            missing = sorted(want - found)
            extra = sorted(found - want)
            detail = []
            if missing:
                detail.append(f"missing: {', '.join(missing)}")
            if extra:
                detail.append(f"unexpected: {', '.join(extra)}")
            f.error(
                mode.name,
                f"{agent_root} holds {len(found)} skill(s), expected "
                f"{len(expected)} for {who} — {'; '.join(detail)}. The installer "
                f"can finish successfully having installed the wrong number, "
                f"so this count is the assertion and not the exit status.",
            )

        for name in sorted(want & found):
            _check_entry(dest, agent_root, name, mode, f)

    check_lock(dest, expected, mode, f)


def check_lock(dest: Path, expected: Sequence[str], mode: Mode, f: Findings) -> None:
    """The installer's own record agrees with the filesystem."""
    lock = dest / LOCK_FILE
    if not lock.is_file():
        f.error(
            mode.name,
            f"{LOCK_FILE} was not written, so `skills experimental_install` has "
            f"nothing to restore from",
        )
        return
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        f.error(mode.name, f"{LOCK_FILE} is not readable JSON ({exc})")
        return
    if not isinstance(data, dict):
        # Valid JSON is not the same as the shape this reads. A bare list would
        # otherwise reach `.get` and raise, turning a finding into a traceback.
        f.error(
            mode.name,
            f"{LOCK_FILE} parsed as {type(data).__name__}, not an object",
        )
        return
    recorded = set(data.get("skills") or {})
    if recorded != set(expected):
        missing = sorted(set(expected) - recorded)
        extra = sorted(recorded - set(expected))
        f.error(
            mode.name,
            f"{LOCK_FILE} records {len(recorded)} skill(s), expected "
            f"{len(expected)}"
            + (f" — missing: {', '.join(missing)}" if missing else "")
            + (f" — unexpected: {', '.join(extra)}" if extra else ""),
        )


def check_links(dest: Path, expected: Sequence[str], mode: Mode, f: Findings) -> Coverage:
    """Every relative markdown link resolves, traversed as the agent would.

    Plain `.exists()` on the joined path, deliberately, rather than
    `.resolve().exists()`: an agent opening the file goes through the kernel,
    which follows the symlink and then applies any `..` from wherever that
    landed. Normalising the path in Python first would answer a slightly
    different question than the one that matters.

    Link extraction comes from skill_links so this and lint_skills.py cannot
    drift apart — and so this gate inherits the rule that a code span which
    looks like a path is prose. Three such spans in
    catalyst-workflow-from-diagram are correct as written.
    """
    files = 0
    links = 0
    for agent_root in AGENT_ROOTS:
        for name in expected:
            skill = dest / agent_root / name
            if not skill.is_dir():
                continue  # check_layout has already reported this
            here = 0
            for md in markdown_files(skill):
                here += 1
                text = md.read_text(encoding="utf-8")
                for target in local_link_targets(text):
                    links += 1
                    if not (md.parent / link_path(target)).exists():
                        f.error(
                            mode.name,
                            f"`{target}` in {agent_root}/{name}/"
                            f"{md.relative_to(skill).as_posix()} does not "
                            f"resolve as installed",
                        )
            if not here:
                f.error(
                    mode.name,
                    f"{agent_root}/{name} contains no markdown at all — either "
                    f"the install is empty or this walk is not descending into it",
                )
            files += here
    return Coverage(files, links)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def report(
    source: Path,
    expected: Sequence[str],
    coverage: dict[str, Coverage],
    f: Findings,
) -> int:
    print(f"`{SKILLS_PACKAGE}` installing {len(expected)} skill(s) from {source}")
    print(f"agents: {', '.join(AGENTS)}, as repeated -a flags\n")

    for name, cov in coverage.items():
        mode = MODE_BY_NAME[name]
        print(f"  {name} mode — {mode.what}")
        # Observed numbers only. An earlier version printed the EXPECTED skill
        # count on this line, which meant a run that installed one skill of ten
        # still opened with "10 skill(s)" and contradicted its own error list
        # four lines later. The count verdict lives in the problems section.
        print(
            f"    {cov.links} link(s) checked across {cov.files} markdown "
            f"file(s) in {', '.join(AGENT_ROOTS)}"
        )

    print("\nnot verified here, by design:")
    for item in UNVERIFIABLE:
        print(f"  - {item}")

    if f.notes:
        print()
        for note in f.notes:
            print(f"note: {note}")

    if f.errors:
        print(f"\n{len(f.errors)} problem(s):\n", file=sys.stderr)
        for err in f.errors:
            print(f"  ✗ {err}\n", file=sys.stderr)
        print(
            "A finding here is what a user gets from the install command in the "
            "README, so fix the skills or the layout expectation — not the "
            "assertion. Reproduce it locally with:\n"
            "  python3 scripts/check_install.py",
            file=sys.stderr,
        )
        return 1

    print("\nevery installed skill resolves, in every agent directory, in every mode checked")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO,
        help="the checkout to install from; defaults to the repo holding this script",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=sorted(MODE_BY_NAME),
        help="install mode to check, repeatable; defaults to all of them",
    )
    args = parser.parse_args(argv[1:])

    if shutil.which("npx") is None:
        print(
            "npx is not on PATH, and this gate is nothing without it — it exists "
            "to run the real installer. Install Node and try again.",
            file=sys.stderr,
        )
        return 1

    source = args.source.resolve()
    expected = expected_skills(source)
    if not expected:
        print(
            f"{source} has no skills to install, so there is nothing to assert. "
            f"A gate that checks an empty tree reports success on everything.",
            file=sys.stderr,
        )
        return 1

    modes = [MODE_BY_NAME[name] for name in (args.mode or list(MODE_BY_NAME))]

    f = Findings()
    coverage: dict[str, Coverage] = {}
    for mode in modes:
        with tempfile.TemporaryDirectory(prefix="catalyst-install-") as tmp:
            dest = Path(tmp)
            status, output = run_installer(source, dest, mode)
            if status != 0:
                # Not the gate — the count below is — but a non-zero exit means
                # the checks that follow would only describe the wreckage.
                if _NPM_FAILURE.search(output):
                    why = (
                        f"npm itself failed with exit {status}, before the "
                        f"installer had a verdict, so this is the environment "
                        f"and not this repo — a cache race between concurrent "
                        f"`npx` invocations looks exactly like this. It said:"
                    )
                else:
                    why = f"the installer exited {status}. It said:"
                f.error(mode.name, f"{why}\n     {tail(output)}")
                continue
            check_layout(dest, expected, mode, f)
            cov = check_links(dest, expected, mode, f)
            coverage[mode.name] = cov
            if not cov.files or not cov.links:
                # A gate that silently checks nothing is worse than no gate, and
                # this is the shape of that failure here: the walk stopped
                # descending, or link extraction stopped matching. Asserted at
                # the top level as well as per skill, because the per-skill
                # guard cannot fire if the loop it lives in never runs.
                f.error(
                    mode.name,
                    f"read {cov.files} markdown file(s) and {cov.links} link(s) — "
                    f"nothing was actually examined, so a pass here would mean "
                    f"nothing",
                )

    return report(source, expected, coverage, f)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
