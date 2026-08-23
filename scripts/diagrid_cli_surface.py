#!/usr/bin/env python3
"""Ask a pinned `diagrid` binary what commands and flags actually exist.

This is the half of the CLI gate that talks to the CLI. It never runs a command
that does anything: every probe is a `--help` invocation, and cobra short-circuits
on the help flag *after* parsing flags but *before* any pre-run hook, so a probe
needs no login, no project and no network beyond the CLI's own update check.

Four things about this CLI made the gate harder to build than it looks, and each
one is why a piece of this file exists.

`--help` does not say which flags are required. `MarkFlagRequired` sets a cobra
annotation that the help renderer ignores entirely, so `workflow start` prints
`-i, --instance-id string   Instance ID of the workflow` and looks optional. That
is the whole of the second historical defect: nothing a reader can see says
otherwise. The annotation *is* emitted into the generated bash completion
script, as `must_have_one_flag`, so that script — one invocation, 9458 lines — is
the only machine-readable source for required-ness. This CLI *also* hand-writes
`[Required]:` into some descriptions, inconsistently: `managed-agent runs list`
has it, `workflow start` does not. Both sources are read and unioned; neither
alone is complete.

An unknown subcommand is not an error. `diagrid project bogus --help` prints
`project`'s help and exits 0, because cobra falls back to the nearest command and
treats the rest as arguments. So exit status cannot tell a real command path from
a typo, and the `Usage:` line — which is rendered from the command cobra actually
resolved — is what has to be compared instead.

Required-ness is not always a property of the command. `dev stop` carries
`MarkFlagRequired("project")` when no default project is configured and does not
when one is — same binary, same version, different `must_have_one_flag` in the
completion script. An unconfigured environment therefore sees the strictest set,
which is also the set a brand-new user meets, so CI is the authority and a
logged-in machine is the lax one. It never goes the other way.

Hidden commands and flags are absent from `--help` but still parse. `appid`,
`tokenbudget` and `managed-agent` are hidden commands; `--app-id` is a hidden
deprecated alias of `--id`. They are missing from the completion script too, since
cobra only emits available commands. Only a direct probe separates "does not
exist" from "exists but you cannot confirm it" — and those two deserve very
different failure messages.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# A `--help` invocation of this binary takes one to three seconds, almost all of
# it the CLI's own release check, so every result here is cached for the life of
# the process and `warm` fetches batches in parallel.
_TIMEOUT = 120
_WARM_WORKERS = 8

# Cobra renders a flag line as two spaces, an optional `-x, `, the long name, an
# optional value type, then the description aligned with two or more spaces.
_FLAG_LINE = re.compile(
    r"^\s{2,}(?:-(?P<short>[a-zA-Z0-9]),\s)?\s*--(?P<long>[a-z0-9][a-zA-Z0-9-]*)(?P<rest>.*)$"
)
_FLAG_REST = re.compile(r"^(?: (?P<type>\S+))?(?:\s{2,}(?P<desc>.*))?$")

# Headings that are definitely NOT a list of subcommands. Everything else at
# column zero ending in a colon is treated as one.
#
# A deny-list rather than a pattern for `... Commands:`, because this CLI groups
# the root command's children under free-text headings — "Project Commands:" and
# "Local Development Commands:" do end in "Commands:", but "AI Assistant:" does
# not, and matching on the word silently dropped `chat` from the root's child
# list. Anything mistakenly treated as a command section still has to survive
# _COMMAND_LINE, which wants a lone lowercase word followed by a summary.
_NON_COMMAND_HEADINGS = frozenset(
    {"Usage:", "Aliases:", "Examples:", "Example:", "Flags:", "Global Flags:", "Additional help topics:"}
)
_HEADING = re.compile(r"^\S.*:\s*$")
_COMMAND_LINE = re.compile(r"^\s{2,}(?P<name>[a-z0-9][a-z0-9-]*)(?:\s{2,}(?P<summary>.*))?$")

# A plain command word in a usage line. Anything with a bracket or angle bracket
# is an operand, and ends the command path.
_WORD = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_HIDDEN_HINT = (
    "it exists but is hidden from `--help`, so it is a deprecated alias or an "
    "unpublished surface. A reader cannot confirm it and a future release can "
    "drop it without notice"
)


@dataclass(frozen=True)
class Flag:
    """One long flag on one command, as `--help` renders it."""

    long: str
    short: str | None
    argtype: str | None
    description: str

    @property
    def annotated_required(self) -> bool:
        """Whether this CLI hand-wrote `[Required]` into the description."""
        return "[Required]" in self.description

    def spelled(self) -> str:
        short = f"-{self.short}, " if self.short else ""
        argtype = f" {self.argtype}" if self.argtype else ""
        return f"{short}--{self.long}{argtype}"


@dataclass
class HelpPage:
    """The parts of one `--help` page this gate reads."""

    path: tuple[str, ...]
    usage_lines: list[str] = field(default_factory=list)
    usage_paths: list[tuple[str, ...]] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    children: dict[str, str] = field(default_factory=dict)
    flags: dict[str, Flag] = field(default_factory=dict)
    # What the CLI printed on stderr, kept so a path that will not resolve can be
    # reported in the CLI's own words rather than in the gate's guess about why.
    stderr: str = ""

    @property
    def resolved_path(self) -> tuple[str, ...] | None:
        """The command cobra actually resolved, per its own usage line."""
        return self.usage_paths[0] if self.usage_paths else None

    @property
    def runnable(self) -> bool:
        """Whether this command does anything without a subcommand.

        Cobra renders `diagrid agent [command]` for a command that only groups,
        and adds a second line — `diagrid managed-agent chat [ID] [flags]` — for
        one that both groups and runs. `managed-agent chat` really is both, so
        "has children" is not the same question as "is a group".
        """
        return any(not line.rstrip().endswith("[command]") for line in self.usage_lines)

    @property
    def is_group(self) -> bool:
        return bool(self.children) and not self.runnable

    def shorthands(self) -> dict[str, str]:
        return {f.short: f.long for f in self.flags.values() if f.short}


def _usage_path(line: str) -> tuple[str, ...] | None:
    """The command path in one usage line, or None if it is not one."""
    tokens = line.split()
    if not tokens or tokens[0] != "diagrid":
        return None
    path: list[str] = []
    for token in tokens[1:]:
        if not _WORD.match(token):
            break
        path.append(token)
    return tuple(path)


def parse_help(text: str, path: tuple[str, ...], stderr: str = "") -> HelpPage:
    """Parse one rendered help page.

    Sections are found by heading rather than by position: this CLI prints a
    banner and a "Current product is ..." line above the root command's usage,
    and orders Examples before or after Available Commands depending on the
    command.
    """
    page = HelpPage(path=path, stderr=stderr.strip())
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Usage:":
            section = "usage"
            continue
        if stripped == "Aliases:":
            section = "aliases"
            continue
        if stripped.endswith("Flags:") and not line.startswith(" "):
            section = "flags"
            continue
        if _HEADING.match(line):
            section = None if stripped in _NON_COMMAND_HEADINGS else "commands"
            continue

        if section == "usage":
            found = _usage_path(stripped)
            if found is not None:
                page.usage_lines.append(stripped)
                page.usage_paths.append(found)
        elif section == "aliases":
            page.aliases.update(a.strip() for a in stripped.split(",") if a.strip())
        elif section == "commands":
            match = _COMMAND_LINE.match(line)
            if match:
                page.children[match.group("name")] = (match.group("summary") or "").strip()
        elif section == "flags":
            flag = _parse_flag_line(line)
            if flag:
                page.flags[flag.long] = flag
    return page


def _parse_flag_line(line: str) -> Flag | None:
    match = _FLAG_LINE.match(line)
    if not match:
        return None
    rest = _FLAG_REST.match(match.group("rest"))
    if not rest:
        return None
    return Flag(
        long=match.group("long"),
        short=match.group("short"),
        argtype=rest.group("type"),
        description=(rest.group("desc") or "").strip(),
    )


def _last_command_path(line: str) -> tuple[str, ...] | None:
    """The command path in a `last_command="diagrid_workflow_start"` line."""
    words = line.split('"')[1].split("_")
    return tuple(words[1:]) if words and words[0] == "diagrid" else None


def completion_paths(completion: str) -> frozenset[tuple[str, ...]]:
    """Every command path the completion script covers — the visible tree."""
    paths = set()
    for line in completion.splitlines():
        stripped = line.strip()
        if stripped.startswith('last_command="'):
            found = _last_command_path(stripped)
            if found is not None:
                paths.add(found)
    return frozenset(paths)


@dataclass
class Tree:
    """The visible command tree, read from the generated completion script.

    Built from the completion script rather than by walking `--help` pages
    because a walk costs one process launch per node — this CLI takes about a
    second to answer any invocation, most of it its own release check, and
    resolving a single unknown token by checking 34 top-level children's aliases
    took 34 of them. The script carries the same information in one launch, and
    carries the alias map explicitly as `aliashash["wfs"]="workflow"` rather than
    by adjacency.

    Hidden commands are absent — cobra emits only available ones — so a token
    this tree does not know still has to be probed.
    """

    children: dict[tuple[str, ...], set[str]] = field(default_factory=dict)
    aliases: dict[tuple[str, ...], dict[str, str]] = field(default_factory=dict)

    def knows(self, path: tuple[str, ...]) -> bool:
        return path in self.children

    def resolve_child(self, parent: tuple[str, ...], token: str) -> str | None:
        """The canonical child name for a token, following aliases."""
        if token in self.children.get(parent, ()):
            return token
        return self.aliases.get(parent, {}).get(token)


def parse_tree(completion: str) -> Tree:
    """Read the visible command tree and its aliases out of a completion script."""
    tree = Tree()
    current: tuple[str, ...] | None = None
    for line in completion.splitlines():
        stripped = line.strip()
        if stripped.startswith('last_command="'):
            current = _last_command_path(stripped)
            if current is not None:
                tree.children.setdefault(current, set())
        elif current is None:
            continue
        elif stripped.startswith('commands+=("'):
            tree.children.setdefault(current, set()).add(stripped.split('"')[1])
        elif stripped.startswith("aliashash["):
            alias, canonical = stripped.split('"')[1], stripped.split('"')[3]
            tree.aliases.setdefault(current, {})[alias] = canonical
    return tree


def parse_required_flags(completion: str) -> dict[tuple[str, ...], set[str]]:
    """Map command path -> required long flags, from a bash completion script.

    Cobra writes `must_have_one_flag+=("--instance-id=")` for every flag passed
    to `MarkFlagRequired`, inside the function for that command, alongside
    `last_command="diagrid_workflow_start"`. Command words keep their hyphens and
    only the separating spaces become underscores, so splitting on `_` recovers
    the path. Shorthand entries (`must_have_one_flag+=("-i")`) are dropped —
    they duplicate the long name.
    """
    required: dict[tuple[str, ...], set[str]] = {}
    current: tuple[str, ...] | None = None
    for line in completion.splitlines():
        stripped = line.strip()
        if stripped.startswith('last_command="'):
            current = _last_command_path(stripped)
        elif stripped.startswith('must_have_one_flag+=("--') and current is not None:
            name = stripped.split('"')[1].lstrip("-").rstrip("=")
            required.setdefault(current, set()).add(name)
    return required


@dataclass
class Resolution:
    """What a documented `diagrid ...` invocation resolves to on the real CLI."""

    path: tuple[str, ...]
    operands: list[str]
    unknown_token: str | None = None
    stopped_at_placeholder: bool = False


class Surface:
    """The command and flag surface of one pinned `diagrid` binary."""

    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self._help: dict[tuple[str, ...], HelpPage] = {}
        self._completion: str | None = None
        self._tree: Tree | None = None

    # -- raw invocations ----------------------------------------------------

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.binary), *args], capture_output=True, text=True, timeout=_TIMEOUT
        )

    def version(self) -> str:
        for line in self._run(["version"]).stdout.splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
        return "unknown"

    def help_page(self, path: tuple[str, ...]) -> HelpPage:
        if path not in self._help:
            proc = self._run([*path, "--help"])
            self._help[path] = parse_help(proc.stdout, path, proc.stderr)
        return self._help[path]

    def warm(self, paths: Iterable[tuple[str, ...]]) -> None:
        """Fetch several help pages at once.

        Each `--help` on this CLI takes one to three seconds and almost none of
        it is CPU — it does a release check before printing. Sequentially that
        put the gate over three minutes for fifty command paths, which is long
        enough that someone would eventually take it out of CI. The work is pure
        IO, so a small pool of processes collapses it.
        """
        todo = sorted({p for p in paths if p not in self._help})
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=_WARM_WORKERS) as pool:
            for path, proc in zip(todo, pool.map(lambda p: self._run([*p, "--help"]), todo)):
                self._help[path] = parse_help(proc.stdout, path, proc.stderr)

    def completion_script(self) -> str:
        if self._completion is None:
            self._completion = self._run(["completion", "bash"]).stdout
        return self._completion

    def tree(self) -> Tree:
        if self._tree is None:
            self._tree = parse_tree(self.completion_script())
        return self._tree

    def required_flags(self, path: tuple[str, ...]) -> set[str]:
        """Required long flags on a command, from both sources that carry it."""
        from_cobra = parse_required_flags(self.completion_script()).get(path, set())
        annotated = {f.long for f in self.help_page(path).flags.values() if f.annotated_required}
        return from_cobra | annotated

    def required_flags_verifiable(self, path: tuple[str, ...]) -> bool:
        """Whether cobra's required-flag annotations are readable for this path.

        False for a hidden command: cobra omits unavailable commands from the
        completion script, so the only signal left is whatever the flag
        description happens to say — and this CLI writes `[Required]` into some
        and not others.
        """
        return path in completion_paths(self.completion_script())

    # -- command paths ------------------------------------------------------

    def canonical_child(self, parent: tuple[str, ...], token: str) -> str | None:
        """The canonical subcommand name for a token, or None if it is not one.

        Aliases are canonicalised (`wf` -> `workflow`) so that required-flag
        lookups, which are keyed on the path cobra writes into the completion
        script, hit.
        """
        found = self.tree().resolve_child(parent, token)
        if found is not None:
            return found
        if token in self.children(parent):
            return token
        if not self._may_hide_children(parent):
            return None
        # It may still be a hidden command, so ask cobra directly: an unknown
        # subcommand makes it fall back to the parent and print the parent's
        # usage, so a usage line one level deeper is the proof.
        resolved = self.help_page((*parent, token)).resolved_path
        if resolved is not None and len(resolved) == len(parent) + 1:
            return resolved[-1]
        return None

    def _may_hide_children(self, parent: tuple[str, ...]) -> bool:
        """Whether it is worth spending a launch probing for a hidden subcommand.

        A command with no *available* children is treated as a leaf, so its
        operands — `project logs my-project`, `workflow start my-workflow` — cost
        nothing. The root is always probed because that is where this CLI hides
        `appid`, `tokenbudget` and `managed-agent`.

        The tradeoff: a command whose children are ALL hidden looks like a leaf
        from both the completion script and `--help`, so its subcommand would be
        read as an operand. That direction is a false failure — the flags then
        get checked against the parent and are reported as unknown — not a
        missed defect, which is the right way round for a gate.
        """
        return not parent or bool(self.children(parent))

    def resolve(self, tokens: list[str]) -> Resolution:
        """Split documented tokens into the longest real command path and operands.

        Greedy, because that is how cobra itself resolves: it walks arguments
        while they name subcommands and treats the first one that does not as a
        positional. So `project logs my-project` is `project logs` with an
        operand, and `managed-agent runs` is a path in its own right whose
        runnable work lives one level deeper.
        """
        path: list[str] = []
        for index, token in enumerate(tokens):
            if token.startswith("-"):
                return Resolution(tuple(path), tokens[index:])
            if is_placeholder(token):
                return Resolution(tuple(path), tokens[index:], stopped_at_placeholder=not path)
            canonical = self.canonical_child(tuple(path), token)
            if canonical is not None:
                path.append(canonical)
                continue
            if not path:
                return Resolution((), tokens[index:], unknown_token=token)
            return Resolution(tuple(path), tokens[index:])
        return Resolution(tuple(path), [])

    def children(self, parent: tuple[str, ...]) -> set[str]:
        """The available subcommands of a path, from the tree or from `--help`.

        The help fallback checks that the page it got back is actually the page it
        asked for. Ask an unresolvable path for its help and cobra answers with
        the ROOT command's help, whose children would otherwise be handed back as
        if they belonged to that path — enough to make `managed-agent chat` look
        real for the wrong reason on a CLI that cannot see `managed-agent` at all.
        Resolution never reaches that state, because a token is only accepted
        after its usage line is confirmed one level deeper, but a helper that
        lies when called directly is a trap for the next caller.
        """
        tree = self.tree()
        if tree.knows(parent):
            return tree.children[parent]
        page = self.help_page(parent)
        if page.resolved_path != parent:
            return set()
        return set(page.children)

    def resolve_all(self, token_lists: Iterable[list[str]]) -> list[Resolution]:
        """Resolve many invocations, overlapping the probes they need.

        Resolution is where the hidden commands are discovered, and each
        discovery costs a launch. Run serially those launches are the largest
        part of the gate's wall time; run through a pool they overlap, and the
        help cache means the second invocation to mention `appid` pays nothing.
        Call `tree()` before this so the pool does not race to build it.
        """
        with ThreadPoolExecutor(max_workers=_WARM_WORKERS) as pool:
            return list(pool.map(self.resolve, token_lists))

    def nearest_commands(self, parent: tuple[str, ...], token: str) -> list[str]:
        return difflib.get_close_matches(token, sorted(self.children(parent)), n=3, cutoff=0.5)

    # -- flags --------------------------------------------------------------

    def flags(self, path: tuple[str, ...]) -> dict[str, Flag]:
        return self.help_page(path).flags

    def probe_flag(self, path: tuple[str, ...], spelling: str) -> bool:
        """Whether the CLI accepts `spelling` on `path`, hidden flags included.

        `--help` is passed first so that cobra parses flags, hits the help flag
        and returns before any pre-run hook — nothing runs, nothing is written.
        A flag that exists but wants a value reports "flag needs an argument",
        which is a different error from "unknown flag", and that difference is
        the whole answer.
        """
        proc = self._run([*path, "--help", spelling])
        stderr = proc.stderr.lower()
        if "unknown flag" in stderr or "unknown shorthand flag" in stderr:
            return False
        return proc.returncode == 0 or "needs an argument" in stderr

    def describe_missing_flag(self, path: tuple[str, ...], spelling: str) -> str:
        """A failure message that names what the CLI does offer instead."""
        if self.probe_flag(path, spelling):
            return f"`{spelling}` is absent from `--help` on `{spell(path)}` — {_HIDDEN_HINT}"
        offered = self.flags(path)
        if spelling.startswith("--"):
            near = difflib.get_close_matches(spelling.lstrip("-"), sorted(offered), n=3, cutoff=0.4)
            suggestion = f" Closest real flag: {', '.join('--' + n for n in near)}." if near else ""
        else:
            shorthands = self.shorthand_table(path)
            listed = ", ".join(f"-{s} ({'--' + long})" for s, long in sorted(shorthands.items()))
            suggestion = f" Shorthands on this command: {listed}." if listed else ""
        return f"`{spelling}` does not exist on `{spell(path)}` at any visibility.{suggestion}"

    def shorthand_table(self, path: tuple[str, ...]) -> dict[str, str]:
        return self.help_page(path).shorthands()


def spell(path: tuple[str, ...]) -> str:
    """A command path as a reader would type it."""
    return " ".join(("diagrid", *path))


def is_placeholder(token: str) -> bool:
    """Whether a token stands in for a value the reader supplies.

    Angle brackets are the convention throughout these skills (`<id>`,
    `<workflow-name>`), and a token in braces or square brackets is the same
    thing in other houses' style.
    """
    return bool(re.search(r"[<>{}\[\]]", token))
