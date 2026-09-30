#!/usr/bin/env python3
"""Tests for the CLI-surface gate.

Every case builds a throwaway skills tree with one known defect and requires the
gate to reject it — against the real pinned binary, not a stub. A stub would let
a parser bug through: the gate's whole claim is that it reads what this CLI
actually says, and a fixture written from the same assumptions as the parser
proves only that the assumptions are self-consistent.

Two things are load-bearing here and both are borrowed from
scripts/test_lint_skills.py, whose own first version was vacuous:

The control cases must PASS. Twelve rejections prove nothing if the gate rejects
everything, and the specific way that happens is a fixture the checker cannot
even read — in the sibling suite every case failed with "no skills/ directory"
and reported eleven passes. So the checker is copied into a `scripts/`
subdirectory of the fixture root, exactly where it derives its repo root from,
and a valid skill has to come out green.

`must_say` is asserted, not just the exit code. "Invalid flag" and "`--appids`
does not exist; closest real flag: `--ids`" are the same exit code and very
different gates. The two historical defects assert on the text that names the
right answer, because that text is the deliverable.

Run: python3 scripts/test_check_cli_surface.py [--cli PATH]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diagrid_cli_pin

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
MODULES = ("check_cli_surface.py", "diagrid_cli_surface.py", "diagrid_cli_pin.py")
PIN = REPO / ".diagrid-cli-version"

HEADER = "---\nname: {name}\ndescription: A valid description, well inside the cap.\n---\n\n"

# Each worker starts a checker that itself runs a few CLI processes, and the
# binary is 110MB. Six keeps a two-core CI runner honest.
_WORKERS = 6


@dataclass(frozen=True)
class Spec:
    """One fixture: a SKILL.md body and the verdict it must produce.

    `must_not_say` exists for the cases whose *depth* of checking depends on the
    login running them. `managed-agent` does not resolve without a login, so
    it does not resolve in CI, so "is this rejected" is not a question with one answer —
    but "is it ever reported as a nonexistent command" is, and that is the
    property worth pinning, because a false "does not exist" is the failure that
    gets a correct skill edited.
    """

    name: str
    body: str
    expect: str = "reject"
    must_say: str | None = None
    must_not_say: str | None = None
    # Extra TOML appended to the pin file for this fixture, for testing the
    # `[login_required]` declaration itself.
    pin_extra: str | None = None


@dataclass(frozen=True)
class Result:
    spec: Spec
    rejected: bool
    output: str

    @property
    def ok(self) -> bool:
        if not self.output.strip():
            # A case asserting only `must_not_say` would otherwise be satisfied by
            # a gate that crashed and printed nothing, which is the same vacuity
            # the control cases exist to catch. An `either` case has no verdict to
            # check, so it has to prove the gate ran at all.
            return False
        if self.spec.expect == "either":
            if "pinned CLI v" not in self.output:
                return False
        elif self.rejected != (self.spec.expect == "reject"):
            return False
        if self.spec.must_say is not None and self.spec.must_say not in self.output:
            return False
        return self.spec.must_not_say is None or self.spec.must_not_say not in self.output


def run_checker(root: Path, cli: Path, pin_extra: str | None = None) -> subprocess.CompletedProcess:
    """Run the gate against a throwaway repo root.

    The three modules are copied into `<root>/scripts/` because the gate resolves
    `skills/` as `__file__/../../skills` and imports its two siblings by name.
    Run it from anywhere else and every case below fails on "no skills directory"
    instead of on its own defect — which is the exact trap that made the first
    version of the sibling suite report passes it had not earned.

    The real pin file is copied in for the same reason: the gate reads
    `[login_required]` from it, and a fixture without one fails on a missing pin
    rather than on its own defect. `pin_extra` appends to it, which is how the
    stale-declaration guard gets tested.
    """
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    for module in MODULES:
        shutil.copy(SCRIPTS / module, scripts / module)
    pin = PIN.read_text(encoding="utf-8")
    (root / PIN.name).write_text(pin + (pin_extra or ""), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(scripts / "check_cli_surface.py"), "--cli", str(cli)],
        cwd=root,
        capture_output=True,
        text=True,
    )


def run_case(spec: Spec, cli: Path) -> Result:
    """Build a one-skill fixture from a SKILL.md body, run the gate, record it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        skill = root / "skills" / "fixture"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(HEADER.format(name="fixture") + spec.body, encoding="utf-8")
        proc = run_checker(root, cli, spec.pin_extra)
        return Result(spec, proc.returncode != 0, proc.stdout + proc.stderr)


# Every fixture, in the order they are worth reading.
SPECS: list[Spec] = [
    # ---- controls. If any of these fails, nothing below means anything ----
    Spec(
        "a correct command with its required flag passes",
        "```\ndiagrid workflow start my-workflow --id my-app --instance-id run-1\n```\n",
        expect="pass",
    ),
    Spec(
        "a bare command named in prose passes",
        "Starting a run is `diagrid workflow start`, which is a write.\n",
        expect="pass",
    ),
    Spec(
        "a hidden-but-real command passes",
        "Tail the platform's view with `diagrid appid logs <id> -f -t 50`.\n",
        expect="pass",
    ),
    Spec(
        "a command group named as a noun passes",
        "| | `diagrid agent` | `diagrid app` |\n",
        expect="pass",
    ),
    # `managed-agent chat` groups list|show|stop|watch|delete AND runs a chat
    # itself. A gate that treats "has subcommands" as "is a group" rejects this.
    Spec(
        "a command that both groups and runs passes",
        '```\ndiagrid managed-agent chat --agent my-agent --project default -m "<prompt>"\n```\n',
        expect="pass",
    ),
    # `--appids` after `--` belongs to the user's program, not to diagrid.
    Spec(
        "the user's own command after `--` is not read as diagrid flags",
        "```\ndiagrid dev run --project default --id app --app-port 8080 -- go run . --appids x\n```\n",
        expect="pass",
    ),
    Spec(
        "an acknowledged counter-example passes",
        "Never write `diagrid project logs --appids <id>`; the flag is `--ids`.\n\n"
        "<!-- cli-allow: project logs --appids — taught as a flag that does not exist -->\n",
        expect="pass",
    ),
    # The anti-vacuity control. If the extractor stops matching, every other case
    # here would pass for the wrong reason, so a fixture with no commands in it
    # must fail rather than quietly check nothing.
    Spec(
        "a skills tree with no commands at all is rejected, not silently green",
        "Prose about workflows with no commands in it.\n",
        must_say="no diagrid invocations found",
    ),
    # ---- the two defects that shipped ----
    Spec(
        "HISTORICAL: `--appids`, a flag that exists on no command",
        "Read the sidecar with `diagrid project logs --appids <id> --type dapr`.\n",
        must_say="Closest real flag: --ids",
    ),
    Spec(
        "HISTORICAL: `workflow start` without the required `--instance-id`",
        "| CLI | `diagrid workflow start <workflow-name> --id <app-id> -p <project>` |\n",
        must_say='requires `--instance-id`',
    ),
    # `--help` bypasses cobra's required-flag validation, so a documented
    # `<cmd> --help` cannot fail on a missing required flag and must not be
    # reported as if it could. Verified against the pinned CLI: `diagrid workflow
    # start --help` exits 0 while `diagrid workflow start` exits 1. Without the
    # exemption in _check_required this case fails, because `workflow start`
    # carries a required `--instance-id` and `dev run` a required `--project`
    # whenever no default project is configured — which is exactly CI.
    Spec(
        "a `--help` invocation is exempt from the required-flag rule",
        "The full surface is in `diagrid workflow start --help`, and "
        "`diagrid dev run --help` lists the rest.\n",
        expect="pass",
    ),
    Spec(
        "HISTORICAL: prose that presents a required flag as a choice",
        "The CLI lets you choose the instance id with `--instance-id`.\n\n"
        "```\ndiagrid workflow start my-workflow --id my-app\n```\n",
        must_say='required flag(s) "instance-id" not set',
    ),
    # This one and the next assert `must_not_say` rather than a verdict, because
    # `managed-agent` is login-required: it does not resolve without a
    # login, so not at all in CI. What must hold in BOTH is that a command
    # a skill might document, and which works where it resolves, is never called nonexistent.
    # The group rule itself is asserted below on `call invoke`, which everyone
    # can see.
    Spec(
        "HISTORICAL: `managed-agent runs --thread` is never called nonexistent",
        "Then the run history, `diagrid managed-agent runs --thread <id>`.\n",
        expect="either",
        must_not_say="is not a command on this CLI",
    ),
    Spec(
        "a command group takes a subcommand, not flags",
        "```\ndiagrid call invoke --verbose\n```\n",
        must_say="is a command group",
    ),
    Spec(
        "HISTORICAL: `diagrid --version`, which the root command has no flag for",
        "Check the version with `diagrid --version` first.\n",
        must_say="does not exist on `diagrid`",
    ),
    Spec(
        "HISTORICAL: `-o json` on `workflow get`, whose output is hardcoded",
        "Read it with `diagrid workflow get <run-id> --id <app-id> -o json`.\n",
        must_say="does not exist on `diagrid workflow get`",
    ),
    # ---- the classes a substring linter cannot express ----
    Spec(
        "a hidden deprecated alias is not the same finding as a missing flag",
        "```\ndiagrid workflow start my-wf --app-id my-app --instance-id run-1\n```\n",
        must_say="absent from `--help`",
    ),
    # An login-required invocation. It works after a login, and CI cannot see it.
    # Where it resolves the missing `--agent` is reported; where it does not, the
    # gate must say so rather than call it nonexistent. Detection of the
    # `[Required]` annotation this relies on is pinned by test_parsers() below,
    # which needs no binary and so runs the same everywhere.
    Spec(
        "a required flag on an login-required command is never called nonexistent",
        "Read the runs with `diagrid managed-agent runs list --thread <id>`.\n",
        expect="either",
        must_not_say="is not a command on this CLI",
    ),
    # The gate must not suppress by resemblance. `managed-agentz` is not the
    # declared prefix, so it is still a nonexistent command.
    Spec(
        "a near-miss on an login-required name is still rejected",
        "Try `diagrid managed-agentz list`.\n",
        must_say="is not a command on this CLI",
    ),
    # And a hidden parent that IS visible to everyone still gets its subcommands
    # checked, so the gate has not gone soft on hidden things generally.
    Spec(
        "a bad verb under a hidden but ungated command is still rejected",
        "Try `diagrid appid tail my-app`.\n",
        must_say="is not a subcommand of `diagrid appid`",
    ),
    # The anti-rot guard on the declaration itself: `project` is in the completion
    # script, so declaring it login-required is stale by construction and must
    # fail rather than silently suppress every `project` finding.
    Spec(
        "a stale login_required entry is rejected",
        "```\ndiagrid project list\n```\n",
        must_say="is stale",
        pin_extra='\nproject = "not actually gated; this entry should be refused"\n',
    ),
    Spec(
        "a verb that moved off its noun between releases",
        "Talk to it with `diagrid agent chat`.\n",
        must_say="is not a subcommand of `diagrid agent`",
    ),
    # `diagrid quota list` is the command someone reaches for after reading the
    # quota section; there is no such noun, and `org usage` is the real answer.
    # Note that `tokenbudgets` and `appids` would NOT do here: both are genuine
    # plural aliases of hidden commands, while `agents` is not an alias of
    # `agent`. Guessing which plurals exist is precisely what this gate replaces.
    Spec(
        "a noun that does not exist at all",
        "List them with `diagrid quota list`.\n",
        must_say="is not a command on this CLI",
    ),
    Spec(
        "a plausible flag that is spelled wrong, answered with the real one",
        "```\ndiagrid dev run --project default --id app --port 8080\n```\n",
        must_say="Closest real flag: --app-port",
    ),
    Spec(
        "an unknown shorthand, answered with the whole shorthand table",
        "```\ndiagrid workflow start my-wf --id app -q run-1\n```\n",
        must_say="Shorthands on this command:",
    ),
    # ---- the shorthand asymmetry, pinned from both sides ----
    Spec(
        "`-p` is `--app-port` on `dev run`",
        "```\ndiagrid dev run --id app -p 8080 --app-port 8080\n```\n",
        must_say="`-p` and `--app-port` are the same flag",
    ),
    Spec(
        "`-p` is `--project` on `workflow start`",
        "```\ndiagrid workflow start my-wf --instance-id r -p proj --project proj\n```\n",
        must_say="`-p` and `--project` are the same flag",
    ),
    Spec(
        "`-a` is `--all` on `appid logs`, not `--id`",
        "```\ndiagrid appid logs my-app -a --all\n```\n",
        must_say="`-a` and `--all` are the same flag",
    ),
]


# Captured verbatim from `diagrid managed-agent runs list --help` at v1.66.0. The
# `[Required]:` prefix is this CLI's own convention, applied to some commands and
# not others, and it is the ONLY signal of required-ness for a command cobra
# leaves out of the completion script.
_RUNS_LIST_HELP = """List runs on a thread

Usage:
  diagrid managed-agent runs list [flags]

Flags:
      --agent string     [Required]: Durable Agent name
  -p, --project string   Name of existing project
      --thread string    [Required]: Thread id the run belongs to
  -h, --help             help for list

Global Flags:
      --api-key string   Diagrid Cloud API key
"""

# Captured verbatim from `diagrid completion bash`, the block for `workflow start`.
# Its `--instance-id` carries NO `[Required]` in help; only this says so.
_START_COMPLETION = """_diagrid_workflow_start()
{
    last_command="diagrid_workflow_start"
    flags+=("--instance-id=")
    two_word_flags+=("--instance-id")
    two_word_flags+=("-i")
    must_have_one_flag=()
    must_have_one_flag+=("--instance-id=")
    must_have_one_flag+=("-i")
}
"""


def test_parsers() -> list[tuple[str, bool, str]]:
    """Pin the two sources of required-ness against captured CLI output.

    These need no binary and no login, which is the point: the `[Required]`
    branch is only reachable through `managed-agent` on a live CLI, and CI cannot
    see `managed-agent`. Without these the annotation parser would be untested
    on every pull request.
    """
    from diagrid_cli_surface import parse_help, parse_required_flags, parse_tree

    checks: list[tuple[str, bool, str]] = []

    page = parse_help(_RUNS_LIST_HELP, ("managed-agent", "runs", "list"))
    annotated = {name for name, flag in page.flags.items() if flag.annotated_required}
    checks.append((
        "help `[Required]:` is read as required",
        annotated == {"agent", "thread"},
        f"got {sorted(annotated)}, wanted ['agent', 'thread']",
    ))
    checks.append((
        "`[Required]` does not leak onto its neighbours",
        not page.flags["project"].annotated_required,
        "--project was read as required",
    ))
    checks.append((
        "a flag's type survives the annotation",
        page.flags["agent"].argtype == "string",
        f"got {page.flags['agent'].argtype!r}",
    ))

    required = parse_required_flags(_START_COMPLETION)
    checks.append((
        "completion `must_have_one_flag` is read as required",
        required.get(("workflow", "start")) == {"instance-id"},
        f"got {required}",
    ))
    checks.append((
        "the shorthand entry is not read as a second flag",
        "i" not in required.get(("workflow", "start"), set()),
        "the `-i` entry became a flag named `i`",
    ))

    tree = parse_tree(_START_COMPLETION)
    checks.append((
        "a leaf command is recorded with no children",
        tree.knows(("workflow", "start")) and not tree.children[("workflow", "start")],
        f"got {tree.children}",
    ))

    # Captured from CI, where the CLI has no login and no default project. The
    # SAME binary emits `must_have_one_flag=()` empty for `dev stop` on a
    # configured machine — MarkFlagRequired("project") is applied from local
    # config, not from the command definition. So a maintainer's local run is the
    # LAX one and CI is authoritative, which is only safe if the parser is known
    # to read the annotation when it is there.
    unconfigured = parse_required_flags(
        '_diagrid_dev_stop()\n{\n    last_command="diagrid_dev_stop"\n'
        '    must_have_one_flag=()\n    must_have_one_flag+=("--project=")\n'
        '    must_have_one_flag+=("-p")\n}\n'
    )
    checks.append((
        "a config-dependent required flag is read when the CLI declares it",
        unconfigured.get(("dev", "stop")) == {"project"},
        f"got {unconfigured}",
    ))
    return checks


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cli", type=Path, default=None)
    args = parser.parse_args(argv[1:])

    try:
        cli = args.cli or diagrid_cli_pin.fetch()
    except diagrid_cli_pin.PinError as exc:
        print(f"cannot fetch the pinned Diagrid CLI: {exc}", file=sys.stderr)
        return 1

    started = time.monotonic()

    failures = 0
    for name, ok, detail in test_parsers():
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  parser: {name}")
        if not ok:
            print(f"           {detail}")

    # Every case is an independent subprocess waiting on the CLI, which spends a
    # few seconds per invocation checking for a newer release. Run serially this
    # suite took minutes; `map` keeps the report in the written order.
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda spec: run_case(spec, cli), SPECS))

    for r in results:
        failures += not r.ok
        got = "rejected" if r.rejected else "passed"
        print(f"  {'ok  ' if r.ok else 'FAIL'}  {r.spec.name}\n           wanted {r.spec.expect}, got {got}")
        if not r.ok:
            if r.spec.must_say and r.spec.must_say not in r.output:
                print(f"           expected the message to contain: {r.spec.must_say!r}")
            print(f"           gate said:\n{r.output.strip()}\n")

    total = len(results) + len(test_parsers())
    print(f"\n{total} checks in {time.monotonic() - started:.0f}s")
    if failures:
        print(
            f"{failures} of {total} CLI-surface tests failed — the gate does not "
            f"catch what it claims",
            file=sys.stderr,
        )
        return 1
    print(f"all {total} CLI-surface tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
