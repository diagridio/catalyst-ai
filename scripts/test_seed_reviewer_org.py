#!/usr/bin/env python3
"""Tests for the reviewer-org seeding plan.

The script must not be run, so the plan is the artefact that gets checked. These tests
check it: that it creates exactly what CAT-1734 asks for, that every mutating step says
how a re-run is made safe, and — the two that matter most — that it never creates a
project and that its failing runs come from a deliberately-failing activity rather than
from a forged state.

Pure: no CLI, no login, no network. `plan()` takes a Config and returns Steps.

Run: python3 scripts/test_seed_reviewer_org.py
"""

from __future__ import annotations

import json
import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_reviewer_org import (  # noqa: E402
    FAILING_INPUT,
    FAILING_WORKFLOW,
    GUARD_NOTES,
    WORKFLOWS,
    Config,
    plan,
    render_plan,
    run_id,
)

REPO = Path(__file__).resolve().parent.parent
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def cfg() -> Config:
    return Config(org="reviewer-org", mcpserver_url="https://mcp.example.com/mcp",
                  llm_component="demo-llm")


def writes(steps) -> list:
    return [s for s in steps if not s.read_only]


# ---------------------------------------------------------------------------------------
# What the issue asks for, counted
# ---------------------------------------------------------------------------------------
def test_meets_the_issues_minimums() -> None:
    steps = plan(cfg())
    starts = [s for s in steps if s.argv[:3] == ["diagrid", "workflow", "start"]]

    check(len(starts) >= 20, f"issue asks for >=20 runs; plan has {len(starts)}")

    names = {s.argv[3] for s in starts}
    check(len(names) >= 3, f"issue asks for >=3 workflows; plan starts {len(names)}: {names}")

    agents = [s for s in steps if s.argv[:3] == ["diagrid", "managed-agent", "create"]]
    check(len(agents) == 1, f"issue asks for exactly 1 agent; plan has {len(agents)}")

    mcps = [s for s in steps if s.argv[:3] == ["diagrid", "mcpserver", "create"]]
    check(len(mcps) == 1, f"issue asks for exactly 1 MCPServer; plan has {len(mcps)}")


def test_at_least_two_runs_carry_the_failing_input() -> None:
    """The failures must be produced by input the failing activity reacts to.

    Counting `Failed` records would pass on a forged failure. Counting runs that carry
    the input the activity raises on is the property that cannot be faked.
    """
    steps = plan(cfg())
    failing = [
        s
        for s in steps
        if s.argv[:3] == ["diagrid", "workflow", "start", ][:3]
        and s.argv[3] == FAILING_WORKFLOW
        and json.loads(s.argv[s.argv.index("-d") + 1]) == FAILING_INPUT
    ]
    check(len(failing) >= 2, f"issue asks for >=2 real failures; plan has {len(failing)}")

    for s in failing:
        check("FAILS" in s.purpose, f"a failing run does not say so in its purpose: {s.purpose!r}")


FAILING_ACTIVITY = "charge_card"


def test_the_failure_comes_from_an_activity_that_raises() -> None:
    """The seed app must actually raise, reachably, on the input the plan sends.

    This is the test that stops the plan and the worker drifting apart: if someone
    changes FAILING_INPUT and not the activity, or removes the raise, the plan would go
    on claiming failures that never happen.

    It reads the syntax tree rather than the text, because the text is too easy to
    satisfy. A review of this file mutated the guard to

        if False and invoice.get("card") == "expired":

    which makes the raise permanently unreachable while leaving both `raise
    RuntimeError` and `"expired"` present in the file — and the previous, grep-based
    version of this test passed. The whole reviewer-org demo rests on those two runs
    genuinely failing, so this is the one property here worth testing properly.
    """
    tree = ast.parse((REPO / "scripts" / "seed" / "app.py").read_text())
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == FAILING_ACTIVITY),
        None,
    )
    check(func is not None, f"scripts/seed/app.py has no {FAILING_ACTIVITY}() to fail in")
    if func is None:
        return

    raises = [n for n in ast.walk(func) if isinstance(n, ast.Raise)]
    check(bool(raises), f"{FAILING_ACTIVITY}() raises nothing, so no run can fail")

    conditions = [n.test for n in ast.walk(func) if isinstance(n, ast.If)]
    check(
        bool(conditions),
        f"{FAILING_ACTIVITY}() raises unconditionally — every run would fail, not two",
    )

    # A guard that cannot be true makes the raise dead code. Catches `if False:` and
    # `if False and ...`, which is the mutation that defeated the text-matching version.
    for test in conditions:
        for node in ast.walk(test):
            if isinstance(node, ast.Constant) and node.value in (False, None, 0):
                check(
                    False,
                    f"{FAILING_ACTIVITY}()'s guard contains a constant {node.value!r}, "
                    f"so the raise is unreachable and the plan's failing runs would complete",
                )

    # And the reachable guard has to be about the value the plan actually sends.
    guard_src = " ".join(ast.unparse(test) for test in conditions)
    check(
        FAILING_INPUT["card"] in guard_src,
        f"{FAILING_ACTIVITY}() does not branch on card={FAILING_INPUT['card']!r} "
        f"(guards: {guard_src!r}), so the plan's failing runs would complete",
    )


# ---------------------------------------------------------------------------------------
# Idempotency, which is the whole point of a re-runnable seeder
# ---------------------------------------------------------------------------------------
def test_every_mutating_step_declares_how_a_rerun_is_safe() -> None:
    for step in writes(plan(cfg())):
        check(
            step.idempotency in GUARD_NOTES,
            f"unknown idempotency {step.idempotency!r} on: {step.render()}",
        )


def test_creates_without_the_cli_flag_carry_a_read_guard() -> None:
    """managed-agent create and mcpserver create have no --ignore-if-exists.

    Measured against v1.66.0, and the asymmetry is invisible at the call site — which is
    why it is asserted here rather than trusted.
    """
    for step in writes(plan(cfg())):
        if step.argv[2:3] != ["create"]:
            continue
        has_flag = "--ignore-if-exists" in step.argv
        if has_flag:
            check(
                step.idempotency == "flag",
                f"{step.render()} passes --ignore-if-exists but is not marked 'flag'",
            )
        else:
            check(
                step.idempotency == "read" and step.guard is not None,
                f"{step.render()} has no --ignore-if-exists and no read guard, so a "
                "second run of this script would fail here",
            )


def test_run_ids_are_deterministic_and_unique() -> None:
    steps = plan(cfg())
    ids = [
        s.argv[s.argv.index("--instance-id") + 1]
        for s in steps
        if "--instance-id" in s.argv
    ]
    check(len(ids) == len(set(ids)), "duplicate instance ids in one plan")
    # Two plans built from the same Config must name the same runs, or a re-run doubles
    # the run count instead of colliding.
    again = [
        s.argv[s.argv.index("--instance-id") + 1]
        for s in plan(cfg())
        if "--instance-id" in s.argv
    ]
    check(ids == again, "instance ids are not stable across two plans of the same Config")
    check(run_id("x", 3) == "seed-x-03", f"unexpected run-id shape: {run_id('x', 3)}")


def test_every_workflow_start_names_an_instance_id() -> None:
    """`workflow start` requires --instance-id and generates nothing."""
    for step in plan(cfg()):
        if step.argv[:3] == ["diagrid", "workflow", "start"]:
            check("--instance-id" in step.argv, f"start without --instance-id: {step.render()}")


# ---------------------------------------------------------------------------------------
# The two things that would quietly ruin the seeded org
# ---------------------------------------------------------------------------------------
def test_never_creates_a_project() -> None:
    """Workflow reads require `default`'s managed store; a hand-rolled project loses runs."""
    for step in plan(cfg()):
        check(
            step.argv[:3] != ["diagrid", "project", "create"],
            f"plan creates a project: {step.render()}",
        )


def test_the_worker_is_run_without_an_app_port() -> None:
    """A pure workflow worker has no inbound endpoint; --app-port makes it die at bind."""
    runs = [s for s in plan(cfg()) if s.argv[:3] == ["diagrid", "dev", "run"]]
    check(len(runs) == 1, f"expected one dev run step, got {len(runs)}")
    for s in runs:
        check("--app-port" not in s.argv, f"dev run passes --app-port: {s.render()}")
        check("-p" not in s.argv, "on dev run the short -p means --app-port, not --project")


def test_verification_steps_are_read_only_and_present() -> None:
    """A seeder that does not read its own result back has not proved anything."""
    reads = [s for s in plan(cfg()) if s.read_only]
    check(len(reads) >= 5, f"only {len(reads)} verification reads")
    joined = " ".join(s.render() for s in reads)
    for expected in ("workflow list", "--status failed", "workflow get",
                     "managed-agent get", "mcpserver get"):
        check(expected in joined, f"no verification step covers {expected!r}")


# ---------------------------------------------------------------------------------------
# Safety: the script must not be runnable by accident
# ---------------------------------------------------------------------------------------
def test_dry_run_is_the_default_and_executes_nothing() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "seed_reviewer_org.py"), "--org", "reviewer-org"],
        capture_output=True,
        text=True,
        check=False,
    )
    check(proc.returncode == 0, f"a plain plan run exited {proc.returncode}: {proc.stderr}")
    check("PLAN ONLY" in proc.stdout, "the default run does not announce itself as a plan")
    check("nothing has been executed" in proc.stdout, "the plan does not say it executed nothing")


def test_apply_refuses_without_confirmation() -> None:
    proc = subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "seed_reviewer_org.py"),
            "--org", "reviewer-org", "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    check(proc.returncode == 2, f"--apply without --prereqs-confirmed exited {proc.returncode}")
    check("prereqs-confirmed" in proc.stderr, "the refusal does not name the missing flag")


def test_apply_refuses_without_an_mcpserver_url() -> None:
    proc = subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "seed_reviewer_org.py"),
            "--org", "reviewer-org", "--apply", "--prereqs-confirmed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    check(proc.returncode == 2, f"--apply with no --mcpserver-url exited {proc.returncode}")
    check("mcpserver-url" in proc.stderr, "the refusal does not name the missing URL")


def test_the_plan_states_what_it_cannot_do_itself() -> None:
    text = render_plan(cfg(), plan(cfg()))
    check("PREREQUISITES" in text, "the plan does not list its prerequisites")
    check("data_sharing: full" in text, "the plan does not state the data-sharing prerequisite")
    check(
        "NO CLI command" in text,
        "the plan does not say the data-sharing level cannot be set from the CLI",
    )


def test_no_credential_is_ever_put_on_a_command_line() -> None:
    """--llm-api-key and --oauth2-client-secret take live secrets as argv."""
    banned = ("--llm-api-key", "--oauth2-client-secret", "--endpoint-token", "--api-key")
    for step in plan(cfg()):
        for flag in banned:
            check(flag not in step.argv, f"{flag} appears in a planned command: {step.render()}")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):\n", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
