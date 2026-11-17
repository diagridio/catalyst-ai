#!/usr/bin/env python3
"""Tests for the session metrics reader.

The fixture is a small Claude Code session built line by line in the shapes a
real log has, including the three that would quietly inflate the numbers if the
reader got them wrong: one response written as several lines with the same id,
an `api-request-blob` line replaying an earlier tool call, and a subagent log
beside the main one. Another case checks that nothing the person typed and no
tool argument reaches the output, because a log can hold connection values.

Run: python3 scripts/test_session_metrics.py
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_metrics  # noqa: E402

SECRET = "sk-do-not-print-me"
USAGE_1 = {"input_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5, "output_tokens": 7}
USAGE_2 = {"input_tokens": 3, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0, "output_tokens": 11}
USAGE_SUB = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 20, "output_tokens": 2}


def at(second: int) -> str:
    return f"2026-11-17T10:00:{second:02d}.000Z"


def assistant(msg_id: str, usage: dict, second: int, *content: dict) -> dict:
    return {
        "type": "assistant", "version": "2.1.325", "timestamp": at(second),
        "message": {"id": msg_id, "model": "claude-opus-5-5", "usage": usage, "content": list(content)},
    }


def tool_use(name: str, **args) -> dict:
    return {"type": "tool_use", "id": f"t-{name}", "name": name, "input": args}


def user(content, second: int, **extra) -> dict:
    return {"type": "user", "version": "2.1.325", "timestamp": at(second), "message": {"role": "user", "content": content}, **extra}


def build(root: Path) -> tuple[Path, int, int]:
    """Write the fixture session. Returns its path, the skill preamble's size in
    bytes and the size of the reference files it reads."""
    skill_dir = root / "cache" / "diagrid" / "catalyst-ai" / "0.8.1" / "skills" / "catalyst-develop"
    reference = skill_dir / "reference" / "tunnels.md"
    reference.parent.mkdir(parents=True)
    reference.write_text("# Tunnels\n\nHow to open one.\n")
    (skill_dir / "SKILL.md").write_text("# Develop\n")
    # Read in two pages: counted once, page by page.
    paged = skill_dir / "reference" / "paged.md"
    paged.write_text("one\ntwo\nthree\nfour\n")
    preamble = f"Base directory for this skill: {skill_dir}\n\n# Develop\n"
    # A working tree with its own skills/ folder: not a loaded skill.
    not_a_skill = root / "src" / "skills" / "myapp" / "main.py"
    not_a_skill.parent.mkdir(parents=True)
    not_a_skill.write_text("print('hi')\n")
    # In the plugin cache but gone since: the skill is named, with 0 bytes.
    gone = skill_dir.parent / "catalyst-operate" / "reference" / "gone.md"

    session = root / "projects" / "-work" / "s1.jsonl"
    session.parent.mkdir(parents=True)
    lines = [
        {"type": "permission-mode", "permissionMode": "default"},
        user(f"connect my agent, token {SECRET}", 0, origin={"kind": "human"}),
        # One response, two lines, same id and usage: counted once.
        assistant("m1", USAGE_1, 1, {"type": "text", "text": "Looking."}),
        assistant("m1", USAGE_1, 2, tool_use("mcp__plugin_catalyst-ai_catalyst__catalyst_list_apps", project=SECRET)),
        # Request history replaying m1's call: never counted.
        {"type": "api-request-blob", "message": {"role": "assistant", "content": [tool_use("catalyst_list_apps", project=SECRET)]}},
        user([{"type": "tool_result", "tool_use_id": "t-1", "is_error": True, "content": "denied"}], 3),
        user(preamble, 4, isMeta=True),
        assistant(
            "m2", USAGE_2, 5,
            tool_use("mcp__plugin_catalyst-ai_catalyst__catalyst_list_apps", project=SECRET),  # repeated
            tool_use("mcp__catalyst__diagrid_get_app", app="a"),  # renamed tool set
            tool_use("mcp__diagrid-admin-prod__get_user", id="u"),  # not a Catalyst tool
            tool_use("AskUserQuestion", question="which project?"),
            tool_use("Read", file_path=str(reference)),
            tool_use("Read", file_path=str(skill_dir / "SKILL.md")),  # counted with the load already
            tool_use("Read", file_path=str(not_a_skill)),
            tool_use("Read", file_path=str(gone)),
            tool_use("Read", file_path=str(paged), offset=1, limit=2),
            tool_use("Read", file_path=str(paged), offset=3, limit=2),
        ),
        # Timestamps a log should not hold: one unreadable, one with no offset.
        user("<system-reminder>a</system-reminder>", 0) | {"timestamp": "not-a-time"},
        user("<system-reminder>b</system-reminder>", 0) | {"timestamp": "2026-11-17T10:00:06"},
        user("<system-reminder>remember</system-reminder>", 6),  # older client, no origin
        user("yes, project a", 7),  # older client, typed
        # Written with no origin by current clients too, and not typed prompts.
        user("<local-command-stdout>Set model</local-command-stdout>", 7),
        user("<bash-stdout>ok</bash-stdout><bash-stderr></bash-stderr>", 7),
        user([{"type": "text", "text": "[Request interrupted by user]"}], 7),
        # Written by the client, not a model request.
        {"type": "assistant", "timestamp": at(7), "message": {
            "id": "syn", "model": "<synthetic>", "content": [{"type": "text", "text": "API Error"}],
            "usage": {"input_tokens": 0, "output_tokens": 0}}},
        user("<task-notification>done</task-notification>", 8, origin={"kind": "task-notification"}),
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + '\n{"type": "assist')

    sub = session.parent / "s1" / "subagents" / "agent-1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text("\n".join(json.dumps(line) for line in [
        user("subagent prompt", 9, origin={"kind": "human"}),  # not a user turn
        # A subagent's question is not a wait on the person: not a user turn.
        assistant("m3", USAGE_SUB, 10, tool_use("Bash", command="ls"), tool_use("AskUserQuestion", question="sub?")),
    ]) + "\n")
    return session, len(preamble.encode("utf-8")), reference.stat().st_size + paged.stat().st_size


def run(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        session_metrics.main(argv)
    return out.getvalue()


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, got, want) -> None:
        checks.append((name, got == want, f"wanted {want!r}, got {got!r}"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session, preamble_bytes, reference_bytes = build(root)
        m = session_metrics.measure(session)

        check("tokens in: once per response id, cache reads and writes included, subagent added",
              m["tokens_in"], 115 + 203 + 21)
        check("tokens out", m["tokens_out"], 7 + 11 + 2)
        check("model requests are response ids, not lines, and not synthetic", m["model_requests"], 3)
        check("tool calls: replayed request history is ignored", m["tool_calls"], 13)
        check("catalyst calls match both name sets and nothing else", m["catalyst_calls"], 3)
        check("failed calls come from is_error", m["failed_calls"], 1)
        check("a call with the same tool and arguments is repeated", m["repeated_calls"], 1)
        check("user turns: typed prompts after the first, plus questions; not reminders, "
              "command output, interrupts or subagents", m["user_turns"], 2)
        check("skills loaded, with bytes: not a working tree's skills/ folder, not SKILL.md twice, "
              "0 for a file now gone", m["skills"],
              {"catalyst-develop": preamble_bytes + reference_bytes, "catalyst-operate": 0})
        check("plugin version from the loaded skill's path", m["plugin"], "0.8.1")

        # A session that only Reads a skill's file from the plugin cache, with no load.
        read_only = root / "projects" / "-other" / "s2.jsonl"
        read_only.parent.mkdir(parents=True)
        cached = root / "cache" / "diagrid" / "catalyst-ai" / "0.9.0" / "skills" / "catalyst-operate" / "SKILL.md"
        read_only.write_text(json.dumps(assistant("m9", USAGE_1, 0, tool_use("Read", file_path=str(cached)))) + "\n")
        r = session_metrics.measure(read_only)
        check("plugin version from a Read under the plugin cache, with no skill loaded",
              (r["plugin"], r["skills"]), ("0.9.0", {"catalyst-operate": 0}))
        # Lines a log should not hold, which must not stop the run.
        odd = root / "projects" / "-odd" / "s3.jsonl"
        odd.parent.mkdir(parents=True)
        odd.write_text("\n".join(json.dumps(line) for line in [
            user(session_metrics.SKILL_PREAMBLE + "  \n", 0, isMeta=True),  # names no directory
            assistant("m4", {"input_tokens": 4, "cache_read_input_tokens": None,
                             "cache_creation_input_tokens": None, "output_tokens": None}, 1,
                      {"type": "tool_use", "id": "t-x", "name": "Read", "input": ["not", "an", "object"]},
                      {"type": "tool_use", "id": "t-y", "name": "Read", "input": "a string"}),
        ]) + "\n")
        o = session_metrics.measure(odd)
        check("an empty skill preamble, a non-object tool input and null token counts are skipped",
              (o["skills"], o["tool_calls"], o["tokens_in"], o["tokens_out"]), ({}, 2, 4, 0))
        # Values of the wrong type where a log has strings, objects or numbers.
        shapes = root / "projects" / "-shapes" / "s4.jsonl"
        shapes.parent.mkdir(parents=True)
        shapes.write_text("\n".join(json.dumps(line) for line in [
            ["a", "bare", "array"], "a bare string", 7,
            {"type": "assistant", "version": ["2.1"], "timestamp": at(0), "message": ["not", "an", "object"]},
            {"type": "user", "version": "2.1.325", "timestamp": at(1), "message": {"content": [{"type": "text", "text": ["x"]}]}},
            {"type": "assistant", "version": {"v": 1}, "timestamp": at(2), "message": {
                "id": ["m5"], "model": ["claude"], "usage": USAGE_1, "content": []}},
            {"type": "assistant", "timestamp": at(3), "message": {"id": "m6", "model": "claude-opus-5-5", "usage": ["x"], "content": []}},
            {"type": "assistant", "timestamp": at(4), "message": {
                "id": "m7", "model": "claude-opus-5-5", "content": [
                    {"type": "tool_use", "id": "t-a", "name": None, "input": {}},
                    {"type": "tool_use", "id": "t-b", "name": ["Read"], "input": {}},
                    {"type": "tool_use", "id": "t-c", "name": "Read", "input": {"file_path": ["x"]}},
                ],
                "usage": {"input_tokens": "5", "cache_read_input_tokens": [1], "output_tokens": {"n": 1}}}},
        ]) + "\n")
        w = session_metrics.measure(shapes)
        check("non-object lines, non-string names, versions, models and ids, and non-number tokens are skipped",
              (w["client"], w["model"], w["tool_calls"], w["tools"], w["model_requests"], w["tokens_in"], w["tokens_out"]),
              ("claude-code 2.1.325", "claude-opus-5-5", 3, {"?": 2, "Read": 1}, 1, 5, 0))
        # Reads with no limit stop at the client's default line count.
        long_file = root / "long.md"
        long_file.write_text("".join(f"{i}\n" for i in range(1, 6)))  # 2 bytes a line
        with mock.patch.object(session_metrics, "READ_DEFAULT_LIMIT", 3):
            check("a Read with neither offset nor limit counts the default number of lines",
                  session_metrics.read_bytes(str(long_file), {}), 6)
            check("a Read with offset and no limit counts the default number of lines from offset",
                  session_metrics.read_bytes(str(long_file), {"offset": 4}), 4)
            check("a Read with a limit is not capped by the default",
                  session_metrics.read_bytes(str(long_file), {"offset": 1, "limit": 5}), 10)
            check("a Read whose offset or limit is not a number falls back to the defaults",
                  (session_metrics.read_bytes(str(long_file), {"offset": "abc", "limit": [2]}),
                   session_metrics.read_bytes(str(long_file), {"offset": "4", "limit": None})), (6, 4))
            check("a Read with a negative limit counts nothing",
                  session_metrics.read_bytes(str(long_file), {"limit": -1}), 0)
            check("a Read whose offset or limit is Infinity falls back to the defaults",
                  session_metrics.read_bytes(str(long_file), json.loads('{"offset": Infinity, "limit": Infinity}')), 6)
        check("client and model", (m["client"], m["model"]), ("claude-code 2.1.325", "claude-opus-5-5"))
        check("wall time from first to last line, subagent included; bad and naive timestamps "
              "do not stop the run", m["wall_seconds"], 10)
        check("subagent logs are found", m["subagent_files"], 1)

        text = run([str(session)])
        table = text.splitlines()
        check("prints a header, a divider and one row", len(table), 3)
        check("every line of the table has the same number of columns", len({line.count("|") for line in table}), 1)
        # Compared as a bool so a failure never prints the output holding the secret.
        check("nothing typed and no tool argument reaches the output",
              SECRET in text + run([str(session), "--json"]), False)

        older = session.parent / "s0.jsonl"
        older.write_text("")
        os.utime(older, (0, 0))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(root)}):
            check("a project folder is the directory with every other character as -",
                  session_metrics.project_dir_for(Path("/work")), root / "projects" / "-work")
            check("--session finds a session by id", run(["--session", "s1"]), text)
            latest = argparse.Namespace(path=None, session=None, latest=True)
            check("--latest picks the newest session for this directory",
                  session_metrics.find_session(latest, cwd=Path("/work")), session)

    failures = 0
    for name, ok, detail in checks:
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"           {detail}")

    print()
    if failures:
        print(f"{failures} of {len(checks)} session-metrics tests failed", file=sys.stderr)
        return 1
    print(f"all {len(checks)} session-metrics tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
