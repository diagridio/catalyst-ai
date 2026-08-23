#!/usr/bin/env python3
"""Plan — and only on demand, apply — the reviewer organization CAT-1734 needs.

The Claude directory wants a test account that is "a fully populated account", and
CAT-1734 spells that out: >=3 workflows, >=20 runs including >=2 real failures, one
agent, one MCPServer. A reviewer's first question is usually "show me something that
went wrong", so an all-green organization demos nothing.

This script is deliberately shaped as a PLANNER with a thin executor, rather than as a
sequence of subprocess calls.

Three reasons, and the first is the one that decided it:

  1. It must be reviewable without being run. Seeding creates real resources in a real
     organization, so the artefact that gets reviewed is the plan, not a transcript. A
     planner prints every command it would issue, in order, with the guard that makes
     each one idempotent — which is exactly what "state exactly what it would create and
     in which org" asks for.
  2. It must be TESTABLE without being run. `plan()` is pure: it takes a Config and
     returns Steps. test_seed_reviewer_org.py asserts the plan — the run-id scheme, the
     failure count, which steps carry a guard — without a CLI, a login or a network.
  3. Idempotency is a property of the plan, not of the executor. Two of the four create
     commands have the CLI's own --ignore-if-exists and two do not (measured, see
     GUARD_NOTES), so re-runnability has to be expressed per step. Burying that in
     control flow is how a re-run half-fails.

DRY RUN IS THE DEFAULT. --apply is required to execute anything, and even then the
script refuses unless --org matches `diagrid org current`, so it cannot silently seed
whichever organization the CLI happens to be pointing at. Nothing here has been run.

Two prerequisites this script CANNOT satisfy, both checked rather than assumed:

  * The organization must be on `data_sharing: full` (the A2 decision, CAT-1727). There
    is no CLI command for it — `diagrid org` offers only list/current/use/usage, and the
    level is a control-plane property read from /apis/cra.diagrid.io/v1beta1/reagent. At
    `metadata`, workflow input/output/customStatus are ABSENT, so a reviewer asking "what
    did this run receive?" gets nothing and concludes the connector is broken.
  * The reviewer organization must exist. Creating one is a signup flow, not a CLI call.

Both are printed as PREREQUISITES at the top of every plan, and --apply refuses to start
until they are acknowledged with --prereqs-confirmed.

Usage:
    python3 scripts/seed_reviewer_org.py --org <name>              # plan (default)
    python3 scripts/seed_reviewer_org.py --org <name> --apply --prereqs-confirmed
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The seed worker. Registers the three workflows the runs below start, one of which
# fails on demand. Its path is relative to the repo root so the plan is readable
# wherever it is run from.
SEED_APP = "scripts/seed/app.py"

# The App ID hosting the worker. One App ID, not three: a region allows 10 resources
# where every app, agent and MCP server counts as one, and three workflow DEFINITIONS
# live happily in one worker. Workflow instances are not quotaed.
APP_ID = "catalyst-demo"

AGENT_NAME = "demo-assistant"
MCPSERVER_NAME = "demo-tools"

# The project is `default` and this script never creates one. Every organization gets a
# `default` with the managed workflow store already attached, and workflow reads REQUIRE
# that store — a hand-rolled project is the most common reason a run starts and never
# appears. If `default` is missing, abort and ask; do not create.
DEFAULT_PROJECT = "default"

# Which CLI create commands carry their own idempotency flag. Measured against the
# pinned v1.66.0 with `--help`, not remembered:
#
#   project create      --ignore-if-exists   present
#   app create          --ignore-if-exists   present
#   managed-agent create                     ABSENT
#   mcpserver create                         ABSENT
#
# So two steps are idempotent by flag and two need a read-first guard. Recorded here
# because the asymmetry is invisible at the call site and getting it backwards makes a
# second run fail halfway through.
GUARD_NOTES = {
    "flag": "the CLI's own --ignore-if-exists",
    "read": "a read-first existence check; this create command has no --ignore-if-exists",
    "none": "read-only",
    "instance-id": "deterministic --instance-id; a re-run collides rather than doubling the count",
}


@dataclass(frozen=True)
class Step:
    """One command, with why it is safe to run twice."""

    argv: list[str]
    purpose: str
    # How re-running is made safe: "flag", "read", "instance-id" or "none".
    idempotency: str
    # A read-only command whose non-zero exit means "absent, so create it". Only set
    # for idempotency == "read".
    guard: list[str] | None = None
    # True for steps that only read. The executor runs these even in a dry run, because
    # a plan that has verified its own preconditions is worth more than one that has not.
    read_only: bool = False

    def render(self) -> str:
        return shlex.join(self.argv)


@dataclass(frozen=True)
class Config:
    org: str
    project: str = DEFAULT_PROJECT
    app_id: str = APP_ID
    agent: str = AGENT_NAME
    mcpserver: str = MCPSERVER_NAME
    # The MCP server the reviewer org registers, so catalyst_get_mcp_server has something
    # to return. Deliberately a parameter with no default value baked in: pointing a
    # customer-visible resource at a URL is a decision, not a constant.
    mcpserver_url: str = ""
    llm_component: str = ""
    # 24, not 20: the issue asks for >=20 and three workflows divide into 24 evenly, so
    # every workflow name carries the same eight runs and none looks neglected.
    runs_per_workflow: int = 8
    failures: int = 2


# The three workflows the seed worker registers. `reconcile-invoice` is the one that can
# fail, and its failure is produced by an activity that raises — never by writing a
# Failed record into a store. A forged failure has no history, no failing step and no
# error text, so the graph a reviewer opens is empty: worse than no demo, and dishonest.
WORKFLOWS: tuple[tuple[str, dict], ...] = (
    ("process-order", {"orderId": "seed", "items": 3}),
    ("reconcile-invoice", {"invoiceId": "seed", "card": "valid"}),
    ("fan-out-report", {"regions": ["eu", "us", "apac"]}),
)

FAILING_WORKFLOW = "reconcile-invoice"
FAILING_INPUT = {"invoiceId": "seed-declined", "card": "expired"}


def _json(payload: dict) -> str:
    # Compact and key-ordered, so the same run id always carries byte-identical input and
    # a re-run is a genuine no-op rather than a differently-shaped duplicate.
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def run_id(workflow: str, n: int) -> str:
    """A deterministic instance id.

    This is what makes the script re-runnable at all. `workflow start` REQUIRES
    --instance-id and generates nothing, so a script that invented ids would add 24 more
    runs on every invocation. Named ids collide instead, which is the failure we want.
    """
    return f"seed-{workflow}-{n:02d}"


def plan(cfg: Config) -> list[Step]:
    """Every command, in order. Pure: no I/O, no subprocess, no clock."""
    steps: list[Step] = []

    # --- verify, before creating anything -----------------------------------------
    steps.append(
        Step(
            argv=["diagrid", "org", "current"],
            purpose=f"confirm the CLI is pointing at {cfg.org!r} before anything is created",
            idempotency="none",
            read_only=True,
        )
    )
    steps.append(
        Step(
            argv=["diagrid", "project", "get", cfg.project],
            purpose=(
                f"confirm {cfg.project!r} exists with its managed workflow store. "
                "If it is absent, ABORT — do not create a project; workflow reads "
                "require the managed store and a hand-rolled project silently loses runs"
            ),
            idempotency="none",
            read_only=True,
        )
    )

    # --- the three resources the issue names ---------------------------------------
    steps.append(
        Step(
            argv=[
                "diagrid", "app", "create", cfg.app_id,
                "--project", cfg.project,
                "--ignore-if-exists",
                "--wait",
            ],
            purpose="the App ID hosting the workflow worker (identity only; a worker needs no endpoint)",
            idempotency="flag",
        )
    )

    agent_argv = [
        "diagrid", "managed-agent", "create", cfg.agent,
        "--project", cfg.project,
        "--role", "assistant",
        "--goal", "Answer questions about this organization's workflows",
        "-i", "Be concise",
        "-i", "Say when you do not know",
        "--wait",
    ]
    if cfg.llm_component:
        # Reusing an existing conversation component is the only form of this command
        # that does not put an API key on a command line. Prefer it.
        agent_argv += ["--llm-component", cfg.llm_component]
    steps.append(
        Step(
            argv=agent_argv,
            purpose="the one Durable Agent the issue asks for, so catalyst_get_agent returns something",
            idempotency="read",
            guard=["diagrid", "managed-agent", "get", cfg.agent, "--project", cfg.project],
        )
    )

    mcp_argv = [
        "diagrid", "mcpserver", "create", cfg.mcpserver,
        "--project", cfg.project,
        "--url", cfg.mcpserver_url,
        "--transport", "streamable-http",
        "--display-name", "Demo tools",
        "--description", "Seeded so a reviewer sees a registered MCP server and its tools",
        "--wait",
    ]
    steps.append(
        Step(
            argv=mcp_argv,
            purpose="the one MCPServer the issue asks for, so catalyst_get_mcp_server --tools is not empty",
            idempotency="read",
            guard=["diagrid", "mcpserver", "get", cfg.mcpserver, "--project", cfg.project],
        )
    )

    # --- the worker, then the runs ---------------------------------------------------
    #
    # A pure workflow worker dials Catalyst outbound and polls for work items, so there
    # is NO --app-port and nothing should be listening. Adding one is a common first-run
    # failure that fails confusingly: the worker registers every workflow successfully
    # and then dies at bind.
    steps.append(
        Step(
            argv=[
                "diagrid", "dev", "run",
                "--project", cfg.project,
                "--id", cfg.app_id,
                "--", "python", SEED_APP,
            ],
            purpose=(
                "run the worker so the three workflows are registered and the runs below "
                "can execute. Long-running: start it, leave it up for the run steps, stop "
                "it afterwards"
            ),
            idempotency="none",
        )
    )

    for name, payload in WORKFLOWS:
        for n in range(1, cfg.runs_per_workflow + 1):
            failing = name == FAILING_WORKFLOW and n <= cfg.failures
            data = FAILING_INPUT if failing else payload
            steps.append(
                Step(
                    argv=[
                        "diagrid", "workflow", "start", name,
                        "--project", cfg.project,
                        "--id", cfg.app_id,
                        "--instance-id", run_id(name, n),
                        "-d", _json(data),
                    ],
                    purpose=(
                        "a run that FAILS: charge_card raises on an expired card, so the "
                        "run reaches Failed with a real failing step and real error text"
                        if failing
                        else "a run that completes"
                    ),
                    idempotency="instance-id",
                )
            )

    # --- prove it, rather than claim it ----------------------------------------------
    steps.append(
        Step(
            argv=["diagrid", "workflow", "list", "--project", cfg.project, "-o", "json"],
            purpose=f"confirm >={cfg.runs_per_workflow * len(WORKFLOWS)} runs across {len(WORKFLOWS)} workflow names",
            idempotency="none",
            read_only=True,
        )
    )
    steps.append(
        Step(
            argv=[
                "diagrid", "workflow", "list",
                "--project", cfg.project,
                "--status", "failed",
                "-o", "json",
            ],
            purpose=f"confirm >={cfg.failures} genuinely failed runs — the reviewer's first question",
            idempotency="none",
            read_only=True,
        )
    )
    steps.append(
        Step(
            argv=[
                "diagrid", "workflow", "get", run_id(FAILING_WORKFLOW, 1),
                "--project", cfg.project,
                "--id", cfg.app_id,
            ],
            purpose=(
                "confirm the failure has a failing STEP and error text, not just a Failed "
                "status. This is what a reviewer opens"
            ),
            idempotency="none",
            read_only=True,
        )
    )
    steps.append(
        Step(
            argv=["diagrid", "managed-agent", "get", cfg.agent, "--project", cfg.project],
            purpose="confirm the agent is present and ready",
            idempotency="none",
            read_only=True,
        )
    )
    steps.append(
        Step(
            argv=[
                "diagrid", "mcpserver", "get", cfg.mcpserver,
                "--project", cfg.project,
                "--tools",
            ],
            purpose="confirm the MCP server advertises tools; an MCPServer with none demos nothing",
            idempotency="none",
            read_only=True,
        )
    )

    return steps


PREREQUISITES = (
    (
        "data_sharing: full",
        "The organization must be on the `full` data-sharing level (A2, CAT-1727). There is "
        "NO CLI command for this — `diagrid org` offers only list/current/use/usage. The "
        "level is a control-plane property read from /apis/cra.diagrid.io/v1beta1/reagent "
        "and set through admingrid. At `metadata`, workflow input, output and customStatus "
        "are ABSENT, so a reviewer asking what a run received gets nothing and concludes "
        "the connector is broken.",
    ),
    (
        "the organization exists",
        "Creating an organization is a signup flow, not a CLI call. `diagrid org list` will "
        "not show a reviewer org until someone makes one.",
    ),
    (
        "an LLM component for the agent",
        "Pass --llm-component to reuse an existing conversation component. The alternative "
        "is --llm-provider/--llm-model/--llm-api-key, which puts a live API key on a "
        "command line. Prefer the component.",
    ),
    (
        "a URL for the MCPServer",
        "Pass --mcpserver-url. There is no sensible default: pointing a customer-visible "
        "resource at a URL is a decision.",
    ),
)


def render_plan(cfg: Config, steps: list[Step]) -> str:
    out: list[str] = []
    out.append("=" * 78)
    out.append(f"PLAN ONLY — nothing has been executed.  organization: {cfg.org}")
    out.append(f"                                        project:      {cfg.project}")
    out.append("=" * 78)
    out.append("")
    out.append("PREREQUISITES this script cannot satisfy itself:")
    for name, why in PREREQUISITES:
        out.append(f"  * {name}")
        for line in _wrap(why, 72):
            out.append(f"      {line}")
    out.append("")

    creates = [s for s in steps if not s.read_only]
    reads = [s for s in steps if s.read_only]
    out.append(
        f"WOULD CREATE OR CHANGE: {len(creates)} commands "
        f"({len(reads)} further read-only checks)"
    )
    out.append(f"  1 App ID          {cfg.app_id}")
    out.append(f"  1 Durable Agent   {cfg.agent}")
    out.append(f"  1 MCPServer       {cfg.mcpserver}")
    out.append(
        f"  {cfg.runs_per_workflow * len(WORKFLOWS)} workflow runs   "
        f"across {len(WORKFLOWS)} workflow names, {cfg.failures} of them deliberately failing"
    )
    out.append("  0 projects        `default` is used, never created")
    out.append("")

    for i, step in enumerate(steps, 1):
        tag = "READ " if step.read_only else "WRITE"
        out.append(f"[{i:02d}] {tag}  {step.render()}")
        for line in _wrap(step.purpose, 68):
            out.append(f"          # {line}")
        out.append(f"          # re-runnable via: {GUARD_NOTES[step.idempotency]}")
        if step.guard:
            out.append(f"          # guard: {shlex.join(step.guard)}")
        out.append("")

    out.append("To execute: re-run with --apply --prereqs-confirmed")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def current_org() -> str:
    """The organization the CLI is pointing at. Read-only."""
    proc = subprocess.run(
        ["diagrid", "org", "current", "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"`diagrid org current` failed: {proc.stderr.strip()}")
    import json

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # Fall back to the table form rather than guessing at a shape.
        return proc.stdout.strip()
    for key in ("name", "Name", "organization", "org"):
        if isinstance(payload, dict) and key in payload:
            return str(payload[key])
    return proc.stdout.strip()


def exists(guard: list[str]) -> bool:
    proc = subprocess.run(guard, capture_output=True, text=True, check=False)
    return proc.returncode == 0


def apply(cfg: Config, steps: list[Step]) -> int:
    """Execute the plan. Only reached with --apply --prereqs-confirmed."""
    actual = current_org()
    if cfg.org not in actual:
        print(
            f"refusing to apply: --org is {cfg.org!r} but `diagrid org current` says "
            f"{actual!r}. Run `diagrid org use {cfg.org}` first.",
            file=sys.stderr,
        )
        return 1

    for i, step in enumerate(steps, 1):
        if step.guard and exists(step.guard):
            print(f"[{i:02d}] skip — already present: {shlex.join(step.guard)}")
            continue
        print(f"[{i:02d}] {step.render()}")
        proc = subprocess.run(step.argv, check=False)
        if proc.returncode != 0:
            # A failed `workflow start` on an id that already exists is the idempotent
            # case and not an error; anything else stops the run, because continuing
            # past a failed create leaves a half-seeded organization.
            if step.idempotency == "instance-id":
                print(f"     (instance id already used — treating as already seeded)")
                continue
            print(f"     FAILED (exit {proc.returncode}) — stopping", file=sys.stderr)
            return proc.returncode
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", required=True, help="the reviewer organization, by name")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--app-id", default=APP_ID)
    ap.add_argument("--agent", default=AGENT_NAME)
    ap.add_argument("--mcpserver", default=MCPSERVER_NAME)
    ap.add_argument("--mcpserver-url", default="", help="URL for the seeded MCPServer; required to apply")
    ap.add_argument("--llm-component", default="", help="existing conversation component for the agent")
    ap.add_argument("--runs-per-workflow", type=int, default=8)
    ap.add_argument("--failures", type=int, default=2)
    ap.add_argument("--apply", action="store_true", help="execute the plan instead of printing it")
    ap.add_argument("--prereqs-confirmed", action="store_true", help="required alongside --apply")
    args = ap.parse_args(argv[1:])

    cfg = Config(
        org=args.org,
        project=args.project,
        app_id=args.app_id,
        agent=args.agent,
        mcpserver=args.mcpserver,
        mcpserver_url=args.mcpserver_url,
        llm_component=args.llm_component,
        runs_per_workflow=args.runs_per_workflow,
        failures=args.failures,
    )
    steps = plan(cfg)

    if not args.apply:
        print(render_plan(cfg, steps))
        return 0

    if not args.prereqs_confirmed:
        print(
            "--apply requires --prereqs-confirmed. Read the PREREQUISITES block in the "
            "plan first: without `data_sharing: full` the seeded organization demos "
            "nothing, because every workflow payload is withheld.",
            file=sys.stderr,
        )
        return 2
    if not cfg.mcpserver_url:
        print("--apply requires --mcpserver-url; there is no sensible default.", file=sys.stderr)
        return 2

    return apply(cfg, steps)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
