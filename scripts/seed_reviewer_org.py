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
# live happily in one worker. Workflow instances are not quotaed — there is no
# run-count key in `diagrid org usage`.
#
# The agent below consumes a SECOND budget as well as that shared one:
# `number_of_durable_agents` is its own limit (5 on cra:free) and is counted
# separately. One agent is nowhere near it, but the shared App-ID cap is not the only
# thing a larger seed would run into.
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
    # UNVERIFIED, unlike the four rows above. Whether `workflow start` rejects a
    # duplicate --instance-id, and with what message, cannot be established from
    # `--help`; confirming it means starting the same run twice for real. So the
    # executor does not trust it: a failed start is only excused when stderr actually
    # says the instance exists (see ALREADY_EXISTS), and the verification pass counts
    # the runs that landed rather than assuming the starts worked.
    "instance-id": "deterministic --instance-id; a re-run is EXPECTED to collide rather than double the count, but this is not verified",
}

# Substrings in `workflow start` stderr that mean "this instance id is already taken",
# which is the one failure a re-run should shrug off. Anything else stops the run.
# Deliberately narrow: the previous version treated EVERY non-zero exit as this case,
# so an expired token on one of the two failing runs would have been reported as
# success while the organization ended up short of the >=2 real failures it exists to
# demonstrate.
ALREADY_EXISTS = (
    "already exists",
    "already in use",
    "duplicate",
    "instance id already",
    "workflow instance already",
)


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
    # True for steps that only read. This drives the READ/WRITE label in the printed
    # plan and the verification pass; it does NOT change how `apply` executes a step.
    # A dry run executes nothing at all — `render_plan` is string formatting with no
    # I/O — so the printed plan has verified none of its own preconditions.
    read_only: bool = False
    # A step that hosts the worker rather than returning. `apply` refuses to execute
    # one of these, because `diagrid dev run` blocks in the foreground and there is no
    # detach flag on v1.66.0: running it through `subprocess.run` hangs the script
    # before a single workflow run is started. Phase 1 stops at it; the operator runs
    # it themselves; phase 2 issues the runs.
    hosts_worker: bool = False

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
                "can execute. YOU run this, in its own terminal, and leave it up: it "
                "blocks in the foreground and v1.66.0 has no detach flag"
            ),
            idempotency="none",
            hosts_worker=True,
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


def start_failed_because_it_exists(stderr: str) -> bool:
    """Whether a failed `workflow start` failed only because the id was taken."""
    low = stderr.lower()
    return any(marker in low for marker in ALREADY_EXISTS)


def verify(cfg: Config) -> int:
    """Read the organization back and assert it meets CAT-1734's minimums.

    The previous version streamed these reads to the terminal for a human to eyeball
    and parsed nothing, so `apply` returned 0 whenever every CLI call exited 0 — which
    is not the same as the organization being fit to demo. The one number a reviewer
    will look for first is the count of runs that actually failed.
    """
    want_runs = cfg.runs_per_workflow * len(WORKFLOWS)
    problems: list[str] = []

    def read_json(argv: list[str]) -> object | None:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            problems.append(f"{shlex.join(argv)} exited {proc.returncode}: {proc.stderr.strip()[:200]}")
            return None
        try:
            return json.loads(proc.stdout or "null")
        except json.JSONDecodeError as exc:
            problems.append(f"{shlex.join(argv)} did not return JSON: {exc}")
            return None

    def records(doc: object) -> list[dict]:
        if isinstance(doc, list):
            return [r for r in doc if isinstance(r, dict)]
        if isinstance(doc, dict):
            for key in ("items", "results", "executions", "workflows"):
                inner = doc.get(key)
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
        return []

    print("\n--- verifying ---")

    all_runs = records(read_json(
        ["diagrid", "workflow", "list", "--project", cfg.project, "--limit", "250", "-o", "json"]
    ))
    print(f"    runs total: {len(all_runs)} (want >= {want_runs})")
    if len(all_runs) < want_runs:
        problems.append(f"{len(all_runs)} runs, want at least {want_runs}")

    failed = records(read_json(
        ["diagrid", "workflow", "list", "--project", cfg.project,
         "--status", "failed", "--limit", "250", "-o", "json"]
    ))
    print(f"    failed runs: {len(failed)} (want >= {cfg.failures})")
    if len(failed) < cfg.failures:
        problems.append(
            f"{len(failed)} failed runs, want at least {cfg.failures}. This is the one a "
            f"reviewer asks for first — an all-green organization demos nothing."
        )

    def name_of(rec: dict) -> str:
        for key in ("workflowName", "name", "workflow"):
            value = rec.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    names = {name_of(r) for r in all_runs} - {""}
    print(f"    distinct workflow names: {len(names)} (want >= {len(WORKFLOWS)}) {sorted(names)}")
    if len(names) < len(WORKFLOWS):
        problems.append(f"{len(names)} distinct workflow names, want {len(WORKFLOWS)}")

    for argv in (
        ["diagrid", "managed-agent", "get", cfg.agent, "--project", cfg.project, "-o", "json"],
        ["diagrid", "mcpserver", "get", cfg.mcpserver, "--project", cfg.project, "-o", "json"],
    ):
        if read_json(argv) is None:
            problems.append(f"{shlex.join(argv[:3])} did not return a record")

    if problems:
        print("\nNOT fit to demo:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("    all minimums met")
    return 0


def apply(cfg: Config, steps: list[Step], phase: str) -> int:
    """Execute one phase of the plan. Only reached with --apply --prereqs-confirmed.

    Two phases, because the worker step blocks. `diagrid dev run` runs in the
    foreground and v1.66.0 has no detach flag, so executing it through
    `subprocess.run` hangs before a single run is started — the resources get created
    and then nothing else ever happens. Rather than supervise a long-lived subprocess
    the script cannot reliably poll for readiness, the plan stops there and hands the
    command to the operator.

    Each phase is independently re-runnable, which also means a failure part-way
    through is recoverable by re-running that phase rather than being wedged.
    """
    actual = current_org()
    if cfg.org not in actual:
        print(
            f"refusing to apply: --org is {cfg.org!r} but `diagrid org current` says "
            f"{actual!r}. Run `diagrid org use {cfg.org}` first.",
            file=sys.stderr,
        )
        return 1

    worker_index = next((i for i, s in enumerate(steps) if s.hosts_worker), None)
    if worker_index is None:
        print("plan has no worker step — refusing to guess where the phases split.", file=sys.stderr)
        return 1

    if phase == "resources":
        selected, following = steps[:worker_index], steps[worker_index]
    else:
        selected, following = steps[worker_index + 1:], None

    for i, step in enumerate(selected, 1):
        if step.hosts_worker:  # belt and braces; the slices above exclude it
            print("refusing to execute the worker step; it blocks.", file=sys.stderr)
            return 1
        if step.guard and exists(step.guard):
            print(f"[{i:02d}] skip — already present: {shlex.join(step.guard)}")
            continue
        print(f"[{i:02d}] {step.render()}")
        proc = subprocess.run(step.argv, capture_output=step.idempotency == "instance-id", text=True, check=False)
        if proc.returncode == 0:
            continue
        stderr = proc.stderr or ""
        if step.idempotency == "instance-id" and start_failed_because_it_exists(stderr):
            print("     (instance id already taken — already seeded)")
            continue
        if stderr:
            print(f"     {stderr.strip()[:300]}", file=sys.stderr)
        print(f"     FAILED (exit {proc.returncode}) — stopping", file=sys.stderr)
        return proc.returncode

    if phase == "resources":
        print(
            "\n--- phase 1 done. Now start the worker, in its own terminal: ---\n"
            f"    {following.render()}\n"
            "It blocks; leave it running. Then, here:\n"
            f"    {sys.argv[0]} --org {cfg.org} --apply --prereqs-confirmed "
            f"--mcpserver-url {cfg.mcpserver_url} --phase runs\n"
        )
        return 0

    return verify(cfg)


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
    ap.add_argument(
        "--phase",
        choices=("resources", "runs"),
        default="resources",
        help="resources: create the App ID, agent and MCP server, then stop and hand you "
             "the worker command. runs: start the workflow runs and verify. Two phases "
             "because `diagrid dev run` blocks and has no detach flag.",
    )
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

    return apply(cfg, steps, args.phase)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
