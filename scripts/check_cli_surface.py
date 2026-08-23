#!/usr/bin/env python3
"""Verify every `diagrid` command the skills document against a pinned CLI.

scripts/lint_skills.py catches banned *substrings* — strings someone already
knew were wrong and wrote down. That is the wrong shape of gate for this defect
class, and it has shipped twice in a week:

  `diagrid project logs --appids <id>`   no such flag; it is `--ids`
  `diagrid workflow start` without `--instance-id`   the flag is REQUIRED

Neither was catchable in advance. `--appids` reads exactly like a plural of
`appid` and only became a banned substring after it shipped. `--instance-id`
exists, is spelled correctly, and is documented in a help page that does not say
it is required — cobra's help renderer drops `MarkFlagRequired` entirely. A
substring list cannot express "this flag exists but is required", "this flag
exists but is a hidden deprecated alias", or "this subcommand is really a command
group with nothing runnable of its own".

So this gate asks the CLI. It downloads the version pinned in
.diagrid-cli-version, verifies it by checksum, and for every documented
invocation resolves the command path and checks each flag against what that
binary offers. Every probe is a `--help`; nothing is executed, no login is
needed, and no state is touched.

What it deliberately does NOT check is listed at the end of its own output. MCP
tool names, console routes, package coordinates and quota numbers are not in the
CLI and this gate says so rather than implying coverage it does not have.

Run: python3 scripts/check_cli_surface.py [--cli PATH]
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

import diagrid_cli_pin
from diagrid_cli_surface import Resolution, Surface, spell

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# `diagrid` as a bare word starting a command. The lookbehind matters: `\b` alone
# treats the tail of `state.diagrid` and `@diagrid` as a command, and the skills
# talk about both — `state.diagrid` is a component type and `@diagrid` is an npm
# scope. The lookahead keeps `diagridpy`, the Python console script, out.
_INVOCATION = re.compile(r"(?<![\w./@-])diagrid(?=\s|$)")

# An inline code span. Table cells are just prose with spans in them, so the same
# rule reads `| CLI | `diagrid workflow start ...` |` without needing to know
# anything about tables.
_CODE_SPAN = re.compile(r"`([^`\n]+)`")

_FENCE = re.compile(r"^\s*(```|~~~)")

# A token that could be a subcommand name, as opposed to a value or a placeholder.
_COMMAND_WORD = re.compile(r"^[a-z][a-z0-9-]*$")

# A code span holding nothing but a long flag: `--show-sensitive-values`. These
# are counted, not checked — see `unattributed_flags`.
_BARE_FLAG_SPAN = re.compile(r"`(--[a-z][a-z0-9-]*)`")

# A shell prompt or a comment marker at the head of a line inside a fenced block.
_PROMPT = re.compile(r"^\s*(?:[$>]\s+)?")

# Things this gate cannot see, stated in its own output so a green run is not
# read as more assurance than it is.
UNVERIFIABLE = [
    "MCP tool names (`catalyst_*`) — served by the MCP server, not the CLI. "
    "Cross-check them against the server's tools/list.",
    "Console routes and `diagrid web` deep links — the console is not introspectable "
    "from the binary.",
    "Package coordinates on npm, PyPI, NuGet and Maven — lint_skills.py bans the "
    "known-bad ones by substring; nothing here resolves a registry.",
    "Quota numbers and plan limits — these come from `diagrid org usage` against a "
    "live account, which a CI gate has no business holding credentials for.",
    "Positional argument arity and ordering — cobra's `Args` validators are not "
    "rendered into `--help`, so a wrong number of operands is invisible here.",
    "Flag names mentioned in prose without a command — `--show-sensitive-values` in "
    "a sentence cannot be attributed to a command path, so it is not checked.",
    "Command paths the CLI reveals only to some logins, declared in "
    "`[identity_gated]` in .diagrid-cli-version. CI has no `diagrid login`, so "
    "these are named as unverifiable rather than reported as absent.",
    "Whether a required flag is required for YOU. Some are applied from local "
    "config: `dev stop` requires `--project` with no default project configured "
    "and does not with one, from the same binary. CI is unconfigured and so sees "
    "the strictest set — a run on a logged-in machine can therefore be laxer than "
    "CI, never stricter. Treat CI as authoritative and write the flag in.",
]


@dataclass(frozen=True)
class Invocation:
    """One `diagrid ...` command as a skill writes it."""

    skill: str
    line: int
    raw: str
    fenced: bool
    tokens: list[str] = field(default_factory=list, compare=False)

    @property
    def where(self) -> str:
        return f"skills/{self.skill}/SKILL.md:{self.line}"


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def error(self, inv: Invocation, msg: str) -> None:
        self.errors.append(f"{inv.where}\n     `{inv.raw}`\n     {msg}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extract(text: str, skill: str) -> list[Invocation]:
    """Every documented invocation in one SKILL.md.

    Fenced blocks and inline spans are read separately because they mean
    different things: a fenced block is a command someone will copy, an inline
    span is often a bare reference to a command by name. Both are checked, but
    only the first is assumed to be complete (see `looks_executable`).
    """
    found: list[Invocation] = []
    in_fence = False
    pending: list[str] = []
    pending_line = 0

    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            pending = []
            continue

        if in_fence:
            body = _PROMPT.sub("", line, count=1).rstrip()
            if not pending and (not body or body.startswith("#")):
                continue
            if not pending:
                pending_line = number
            if body.endswith("\\"):
                pending.append(body[:-1].strip())
                continue
            joined = " ".join([*pending, body]).strip()
            pending = []
            inv = _as_invocation(joined, skill, pending_line or number, fenced=True)
            if inv:
                found.append(inv)
            continue

        for span in _CODE_SPAN.findall(line):
            inv = _as_invocation(span, skill, number, fenced=False)
            if inv:
                found.append(inv)

    return found


def _as_invocation(candidate: str, skill: str, line: int, fenced: bool) -> Invocation | None:
    """Turn a code span or fenced line into an Invocation, or None.

    The command is taken from the first whole-word `diagrid` to the end of the
    span rather than requiring the span to start with it, because the skills
    quote the CLI's own messages: "... stop it by running: diagrid dev stop
    --id <id>" is a real command inside a sentence inside a span.
    """
    match = _INVOCATION.search(candidate)
    if not match:
        return None
    raw = candidate[match.start():].strip().rstrip(".,;")
    tokens = _tokenize(raw)
    if len(tokens) < 2 or tokens[0] != "diagrid":
        # A span holding nothing but the word `diagrid` names the CLI rather than
        # invoking it — "fall back to the `diagrid` CLI" — and there is nothing in
        # it to verify.
        return None
    return Invocation(skill=skill, line=line, raw=raw, fenced=fenced, tokens=tokens[1:])


def _tokenize(raw: str) -> list[str]:
    """Split a command line, tolerating the quoting styles the skills use.

    shlex handles `--data '<json>'` and `-m "<prompt>"`; it raises on an
    unbalanced quote, which happens when a span ends mid-sentence, and a plain
    split is good enough to read the flags out of that.
    """
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


@dataclass
class Parsed:
    """The flags and operands of one invocation, as written."""

    long_flags: list[str]
    shorthands: list[str]
    operands: list[str]


def parse_tokens(tokens: list[str]) -> Parsed:
    """Split tokens into long flags, shorthands and operands.

    Everything after a bare `--` belongs to the user's own program — `diagrid dev
    run ... -- go run ./cmd/app` — and checking it against the CLI's flags would
    reject every correct example of that form.
    """
    long_flags: list[str] = []
    shorthands: list[str] = []
    operands: list[str] = []
    for index, token in enumerate(tokens):
        if token == "--":
            break
        if token.startswith("--"):
            long_flags.append(token.split("=", 1)[0])
        elif len(token) > 1 and token.startswith("-") and not token[1].isdigit():
            cluster = token.split("=", 1)[0].lstrip("-")
            shorthands.extend(f"-{c}" for c in cluster)
        elif index == 0 or not _is_value_of_previous(tokens, index):
            operands.append(token)
    return Parsed(long_flags, shorthands, operands)


def _is_value_of_previous(tokens: list[str], index: int) -> bool:
    """Whether tokens[index] is the value of the flag before it.

    Approximate on purpose: the flag's arity is knowable from `--help`, but a
    wrongly classified operand only affects `looks_executable`, never a flag
    check, so the cheap rule is enough.
    """
    previous = tokens[index - 1]
    return previous.startswith("-") and "=" not in previous and previous != "--"


def looks_executable(inv: Invocation, parsed: Parsed) -> bool:
    """Whether to hold this invocation to a complete, runnable command.

    A fenced block is something a reader copies. An inline span carrying flags or
    operands is too. A bare `diagrid project list` in a sentence is a reference to
    a command by name, and demanding its required flags there would flag prose
    like "check `diagrid workflow list`" as broken.
    """
    return inv.fenced or bool(parsed.long_flags or parsed.shorthands or parsed.operands)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def key(path: tuple[str, ...], token: str) -> str:
    """The acknowledgement key for one finding: the command path and the token."""
    return " ".join((*path, token)).strip()


def allows(text: str, marker: str) -> bool:
    """Whether a skill explicitly acknowledges a finding.

    Same shape as lint_skills.py's `lint-allow-banned`, and for the same reason:
    teaching "`--appids` is not a flag, never write it" contains the identical
    characters as instructing someone to use it, and no heuristic separates them.
    A marker cannot be tripped by prose.

    Scoped to the file rather than the line because these skills discuss a
    command in one paragraph and show it in another, and a per-line marker would
    have to sit inside the sentence it is about.
    """
    return f"cli-allow: {marker}" in text


def check_invocation(
    inv: Invocation, surface: Surface, source: str, f: Findings, resolution: Resolution
) -> tuple[str, ...] | None:
    """Check one resolved invocation. Returns the command path, if there is one.

    The command path is resolved *first* and the flags parsed out of what is left
    over. Parsing the whole token list instead makes every bare noun — `diagrid
    agent` in a table cell — look like a command with an operand, which was worth
    twenty-two false failures on the first real run.
    """
    if resolution.stopped_at_placeholder:
        return None

    if resolution.unknown_token is not None:
        _report_unknown_command(inv, surface, resolution.unknown_token, f)
        return None

    path = resolution.path
    parsed = parse_tokens(resolution.operands)
    if not inv.fenced and not (parsed.long_flags or parsed.shorthands or parsed.operands):
        # A bare `diagrid project list` in a sentence: the path is the whole
        # claim and resolving it already proved it. Returning here also skips a
        # `--help` launch, which costs about a second on this CLI.
        return path
    if _check_group(inv, surface, path, parsed, source, f):
        # Reported as a group problem, so the flags belong to a command that was
        # never reached. Reporting them too would name the symptom next to the
        # cause and make the reader pick.
        return path
    _check_long_flags(inv, surface, path, parsed, source, f)
    _check_shorthands(inv, surface, path, parsed, source, f)
    if looks_executable(inv, parsed):
        _check_required(inv, surface, path, parsed, source, f)
    return path


def _report_unknown_command(inv: Invocation, surface: Surface, token: str, f: Findings) -> None:
    near = surface.nearest_commands((), token)
    hint = f" Closest real command: {', '.join(near)}." if near else ""
    children = ", ".join(sorted(surface.children(())))
    f.error(
        inv,
        f"`diagrid {token}` is not a command on this CLI.{hint}\n"
        f"     Top-level commands: {children}",
    )


def _check_group(
    inv: Invocation, surface: Surface, path: tuple[str, ...], parsed: Parsed, source: str, f: Findings
) -> bool:
    """Fail work handed to a bare command group. Returns whether it did.

    Two shapes, and they deserve different sentences.

    A flag on a group is `diagrid managed-agent runs --thread <id>`, the fourth
    historical defect: `runs` groups `list|show|cancel|tail` and runs nothing
    itself, so the command parses as far as `runs`, ignores the rest and prints
    help. The flag check would also catch it, but naming the group is the
    difference between "unknown flag" and "you are missing a verb".

    A plain word after a group is `diagrid agent chat` — a verb that used to
    exist on this noun and moved. It is not an unknown *flag* and not an unknown
    top-level command, so nothing else here would see it.

    Note that having subcommands is not the same as being a group: `managed-agent
    chat` both takes `list|show|stop|watch|delete` and runs a chat itself, which
    cobra shows by rendering two usage lines instead of one.
    """
    if not path:
        # The root is a group too, but "diagrid is a command group" is not a
        # useful sentence about `diagrid --version`. The flag check says the
        # useful thing: the root command has no such flag.
        return False
    page = surface.help_page(path)
    if not page.is_group:
        return False
    verbs = ", ".join(sorted(page.children))
    stray = next((o for o in parsed.operands if _COMMAND_WORD.match(o)), None)
    if stray is not None:
        if allows(source, key(path, stray)):
            return True
        near = surface.nearest_commands(path, stray)
        hint = f" Closest: {', '.join(near)}." if near else ""
        f.error(inv, f"`{stray}` is not a subcommand of `{spell(path)}`.{hint}\n     It offers: {verbs}")
        return True
    first_flag = next(iter(parsed.long_flags + parsed.shorthands), None)
    if first_flag is None:
        return False
    if not allows(source, key(path, first_flag)):
        f.error(
            inv,
            f"`{spell(path)}` is a command group, not a runnable command — it takes a "
            f"subcommand, and the flags here are parsed by nothing.\n"
            f"     Runnable subcommands: {verbs}",
        )
    return True


def _check_long_flags(
    inv: Invocation, surface: Surface, path: tuple[str, ...], parsed: Parsed, source: str, f: Findings
) -> None:
    offered = surface.flags(path)
    for flag in parsed.long_flags:
        if flag.lstrip("-") in offered or allows(source, key(path, flag)):
            continue
        f.error(inv, surface.describe_missing_flag(path, flag))


def _check_shorthands(
    inv: Invocation, surface: Surface, path: tuple[str, ...], parsed: Parsed, source: str, f: Findings
) -> None:
    """Check every shorthand, and that it is not also spelled out in full.

    A shorthand is where this CLI is least guessable: `-a` is `--id`, and `-p` is
    `--app-port` on `dev run` but `--project` on every other `dev` subcommand and
    on `workflow start`. So a shorthand that does not exist is reported with the
    full mapping for that command rather than just rejected.
    """
    table = surface.shorthand_table(path)
    spelled_long = {flag.lstrip("-") for flag in parsed.long_flags}
    for short in parsed.shorthands:
        letter = short.lstrip("-")
        if letter not in table:
            if not allows(source, key(path, short)):
                f.error(inv, surface.describe_missing_flag(path, short))
            continue
        long = table[letter]
        if long in spelled_long:
            f.error(
                inv,
                f"`{short}` and `--{long}` are the same flag on `{spell(path)}`, "
                f"passed twice.",
            )


def _check_required(
    inv: Invocation, surface: Surface, path: tuple[str, ...], parsed: Parsed, source: str, f: Findings
) -> None:
    """Fail an invocation that omits a flag the CLI marks required.

    This is the check that would have caught the `--instance-id` defect, and it
    is deliberately expressed against the command rather than against the prose.
    A skill saying a required flag "lets you choose" the value is only wrong
    because the command it then shows does not parse; checking the command
    catches that without asking a linter to read English.
    """
    required = surface.required_flags(path)
    if not required:
        return
    table = surface.shorthand_table(path)
    present = {flag.lstrip("-") for flag in parsed.long_flags}
    present |= {table[s.lstrip("-")] for s in parsed.shorthands if s.lstrip("-") in table}
    for name in sorted(required - present):
        if allows(source, key(path, f"--{name}")):
            continue
        flag = surface.flags(path).get(name)
        rendered = flag.spelled() if flag else f"--{name}"
        source_note = (
            "cobra marks it required"
            if surface.required_flags_verifiable(path)
            else "the CLI's own help marks it `[Required]`"
        )
        f.error(
            inv,
            f"`{spell(path)}` requires `--{name}`, which this command omits — it "
            f"fails with `required flag(s) \"{name}\" not set` before anything "
            f"runs.\n     The flag is `{rendered}` and {source_note}. `--help` does "
            f"not render required-ness, which is why this is invisible on the page.",
        )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


@dataclass
class Coverage:
    """What the run actually looked at, so a green result can be read honestly."""

    extracted: int = 0
    checked: int = 0
    paths: set[tuple[str, ...]] = field(default_factory=set)
    unresolvable: list[Invocation] = field(default_factory=list)
    gated: list[tuple[Invocation, str]] = field(default_factory=list)


def unattributed_flags(source: str, invocations: list[Invocation]) -> set[str]:
    """Long flags named in prose that no invocation in the file attaches to a command.

    "`--show-sensitive-values` exists on `diagrid component get`" puts the flag and
    the command in two different code spans, and no amount of regex joins them
    without reading the sentence. Counting them is the honest alternative to
    either ignoring them silently or guessing a command to check them against.
    """
    attributed = {t for inv in invocations for t in inv.tokens if t.startswith("--")}
    return set(_BARE_FLAG_SPAN.findall(source)) - attributed


def collect(skills_dir: Path) -> list[tuple[Invocation, str]]:
    """Every invocation in every SKILL.md, paired with the file it came from."""
    jobs: list[tuple[Invocation, str]] = []
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        source = md.read_text(encoding="utf-8")
        jobs.extend((inv, source) for inv in extract(source, skill_dir.name))
    return jobs


def count_unattributed(jobs: list[tuple[Invocation, str]]) -> set[str]:
    """Every prose-only flag across all the files that were read."""
    by_source: dict[str, list[Invocation]] = {}
    for inv, source in jobs:
        by_source.setdefault(source, []).append(inv)
    found: set[str] = set()
    for source, invocations in by_source.items():
        found |= unattributed_flags(source, invocations)
    return found


def check_stale_gates(surface: Surface, gated: dict[str, str], f: Findings) -> None:
    """Fail a declared identity gate that the CLI no longer applies.

    This is what stops `[identity_gated]` becoming a place to put failures. An
    entry only earns its keep while the command is genuinely invisible; once it
    turns up in the completion script it is available to everyone, the
    declaration is suppressing real coverage, and that has to be noticed loudly
    rather than quietly enjoyed.
    """
    for name in sorted(gated):
        if surface.tree().resolve_child((), name) is not None:
            f.errors.append(
                f".diagrid-cli-version: `identity_gated.{name}` is stale — "
                f"`diagrid {name}` is in this CLI's completion script, so it is "
                f"available to everyone now.\n     Remove the entry so its "
                f"commands and flags get checked like any other."
            )


def check_skills(skills_dir: Path, surface: Surface, f: Findings, gated: dict[str, str]) -> Coverage:
    """Check every SKILL.md under a skills directory.

    Resolution comes first for everything, then the help pages for every path it
    landed on are fetched in one parallel batch, then the checks run against a
    warm cache. Interleaving them instead means one serial `--help` per command
    path, which measured at three and a half minutes on this set.
    """
    collected = collect(skills_dir)
    surface.tree()  # one completion-script launch, before anything runs in parallel
    resolutions = surface.resolve_all(inv.tokens for inv, _ in collected)
    jobs = [(inv, source, r) for (inv, source), r in zip(collected, resolutions)]
    surface.warm(resolution.path for _, _, resolution in jobs)

    unattributed = count_unattributed(collected)
    if unattributed:
        f.note(
            f"{len(unattributed)} long flag(s) are named in prose without a command "
            f"and are therefore NOT checked here. lint_skills.py covers the ones "
            f"already known to be wrong by substring; the rest are unverified:\n"
            f"      {', '.join(sorted(unattributed))}"
        )

    coverage = Coverage(extracted=len(jobs))
    for inv, source, resolution in jobs:
        if resolution.unknown_token in gated:
            # The CLI refuses to resolve this command for whoever is running the
            # gate. Calling that "does not exist" would be a false failure, and
            # the dangerous kind: the fix it invites is deleting correct content
            # from a skill. Recorded and reported by name instead.
            coverage.gated.append((inv, resolution.unknown_token))
            continue
        before = len(f.errors)
        path = check_invocation(inv, surface, source, f, resolution)
        if path is not None:
            coverage.checked += 1
            coverage.paths.add(path)
        elif len(f.errors) == before:
            coverage.unresolvable.append(inv)
    return coverage


def report(surface: Surface, coverage: Coverage, f: Findings, gated: dict[str, str]) -> int:
    # The summary prints each path's required flags, which needs its help page
    # for the `[Required]` annotations. Warmed in one batch rather than one at a
    # time inside the loop.
    surface.warm(coverage.paths)
    print(f"pinned CLI v{surface.version()} at {surface.binary}")
    print(
        f"{coverage.checked} invocation(s) checked across {len(coverage.paths)} "
        f"command path(s)\n"
    )
    for path in sorted(coverage.paths):
        required = sorted(surface.required_flags(path))
        suffix = f"   required: {', '.join('--' + r for r in required)}" if required else ""
        print(f"  {spell(path)}{suffix}")

    if coverage.unresolvable:
        print(
            f"\n{len(coverage.unresolvable)} invocation(s) not resolvable, because the "
            f"command itself is a placeholder:"
        )
        for inv in coverage.unresolvable:
            print(f"  {inv.where}  `{inv.raw}`")

    if coverage.gated:
        print(
            f"\n{len(coverage.gated)} invocation(s) NOT CHECKED — this CLI will not "
            f"resolve the command for the identity running the gate:"
        )
        for inv, name in coverage.gated:
            print(f"  {inv.where}  `{inv.raw}`")
        for name in sorted({name for _, name in coverage.gated}):
            said = surface.help_page((name,)).stderr.splitlines()
            detail = f"\n      the CLI said: {said[0]}" if said else ""
            print(f"  `diagrid {name}` — {gated[name]}{detail}")
        print(
            "  Run these on an account that can see them to have their flags "
            "checked; nothing is suppressed where the path resolves."
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
            "A finding here is a command a model would emit and a user would watch "
            "fail. Fix the skill, not this gate. If one is a deliberate "
            "counter-example, acknowledge it in the SKILL.md with a line reading:\n"
            "  <!-- cli-allow: <command path> <flag> — why this is safe here -->",
            file=sys.stderr,
        )
        return 1

    print("\nevery documented command and flag exists on the pinned CLI")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cli",
        type=Path,
        default=None,
        help="an already-downloaded pinned binary; fetched and checksum-verified if omitted",
    )
    parser.add_argument("--skills-dir", type=Path, default=None, help="defaults to skills/ beside this script")
    args = parser.parse_args(argv[1:])

    skills_dir = args.skills_dir or SKILLS_DIR
    if not skills_dir.is_dir():
        print(f"no skills directory at {skills_dir}", file=sys.stderr)
        return 1

    try:
        pin = diagrid_cli_pin.read_pin()
        binary = args.cli or diagrid_cli_pin.fetch()
    except diagrid_cli_pin.PinError as exc:
        print(f"cannot fetch the pinned Diagrid CLI: {exc}", file=sys.stderr)
        return 1

    surface = Surface(binary)
    if not surface.children(()):
        # Everything downstream reads the CLI's own output, so an empty command
        # list has to stop the run rather than turn into fifty "not a command"
        # failures. This is what a CLI that cannot start in this environment —
        # no writable config directory, a truncated download — looks like.
        print(
            f"{binary} listed no top-level commands. Run `{binary} --help` here and "
            f"fix that before trusting this gate.",
            file=sys.stderr,
        )
        return 1

    f = Findings()
    check_stale_gates(surface, pin.identity_gated, f)
    coverage = check_skills(skills_dir, surface, f, pin.identity_gated)
    if coverage.extracted == 0:
        # A gate that silently checks nothing is worse than no gate, and this is
        # the shape of that failure: the extraction regexes stopped matching.
        #
        # The condition is on what was EXTRACTED, not on what resolved. Counting
        # resolutions instead makes a skills tree whose commands are all
        # identity-gated look like a broken extractor, which is a real state — CI
        # has no login, and `managed-agent` is invisible there.
        print(
            "no diagrid invocations found — the extractor is broken, or the skills "
            "document no commands",
            file=sys.stderr,
        )
        return 1
    return report(surface, coverage, f, pin.identity_gated)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
