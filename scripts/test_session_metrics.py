#!/usr/bin/env python3
"""Tests for the session metrics reader.

Each client gets a small session built line by line in the shapes its real log
has. The Claude Code fixture includes the three shapes that would quietly
inflate the numbers if the reader got them wrong: one response written as
several lines with the same id, an `api-request-blob` line replaying an earlier
tool call, and a subagent log beside the main one. The Codex and Copilot
fixtures are built from those clients' source and schema (each one says where),
because nobody on the team has a real log from them yet. For every client a
case checks that nothing the person typed and no tool argument reaches the
output, because a log can hold connection values.

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
import time
from datetime import datetime, timezone
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


def latest(client: str) -> argparse.Namespace:
    return argparse.Namespace(path=None, session=None, latest=True, client=client)


def by_id(client: str, session: str) -> argparse.Namespace:
    return argparse.Namespace(path=None, session=session, latest=False, client=client)


def write_jsonl(path: Path, lines: list, tail: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n" + tail)
    return path


def make_old(path: Path, seconds_ago: int = 3600) -> None:
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


def reference_file(root: Path) -> Path:
    reference = root / "plugin" / "skills" / "catalyst-develop" / "reference" / "tunnels.md"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text("# Tunnels\n\nHow to open one.\n")
    return reference


# Claude Code ---------------------------------------------------------------


def assistant(msg_id: str, usage: dict, second: int, *content: dict) -> dict:
    return {
        "type": "assistant", "version": "2.1.325", "timestamp": at(second),
        "message": {"id": msg_id, "model": "claude-opus-5-5", "usage": usage, "content": list(content)},
    }


def tool_use(name: str, **args) -> dict:
    return {"type": "tool_use", "id": f"t-{name}", "name": name, "input": args}


def user(content, second: int, **extra) -> dict:
    return {"type": "user", "version": "2.1.325", "timestamp": at(second), "message": {"role": "user", "content": content}, **extra}


def build_claude(root: Path) -> tuple[Path, int, int]:
    """Write the Claude Code fixture session. Returns its path, the skill
    preamble's size in bytes and the size of the reference files it reads."""
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
    lines = [
        {"type": "permission-mode", "permissionMode": "default"},
        user(f"connect my agent, token {SECRET}", 0, origin={"kind": "human"}),
        # One response, two lines, same id and usage: counted once.
        assistant("m1", USAGE_1, 1, {"type": "text", "text": "Looking."}),
        assistant("m1", USAGE_1, 2, tool_use("mcp__plugin_catalyst-ai_catalyst__catalyst_list_apps", project=SECRET)),
        # SKILL.md read before the skill is loaded: the load puts it in again, so both count.
        assistant("m1", USAGE_1, 2, tool_use("Read", file_path=str(skill_dir / "SKILL.md"), offset=1)),
        # Request history replaying m1's call: never counted.
        {"type": "api-request-blob", "message": {"role": "assistant", "content": [tool_use("catalyst_list_apps", project=SECRET)]}},
        user([{"type": "tool_result", "tool_use_id": "t-1", "is_error": True, "content": "denied"}], 3),
        # A timestamp with no zone is read as UTC instead of crashing the comparison.
        {**user(preamble, 4, isMeta=True), "timestamp": "2026-11-17T10:00:04"},
        assistant(
            "m2", USAGE_2, 5,
            tool_use("mcp__plugin_catalyst-ai_catalyst__catalyst_list_apps", project=SECRET),  # repeated
            tool_use("mcp__plugin_diagrid_diagrid__diagrid_get_app", app="a"),  # the current tool set
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
    write_jsonl(session, lines, tail='{"type": "assist')

    write_jsonl(session.parent / "s1" / "subagents" / "agent-1.jsonl", [
        user("subagent prompt", 9, origin={"kind": "human"}),  # not a user turn
        # A subagent's question is not a wait on the person: not a user turn.
        assistant("m3", USAGE_SUB, 10, tool_use("Bash", command="ls"), tool_use("AskUserQuestion", question="sub?"),
                  # The subagent never loaded the skill, so its read of SKILL.md counts.
                  tool_use("Read", file_path=str(skill_dir / "SKILL.md"), limit=2000)),
    ])
    skill_md = (skill_dir / "SKILL.md").stat().st_size
    return session, len(preamble.encode("utf-8")), reference.stat().st_size + paged.stat().st_size + 2 * skill_md


# Codex ---------------------------------------------------------------------
# Shapes from https://github.com/openai/codex/tree/rust-v0.169.0/codex-rs:
# the line envelope and `token_usage_record` in protocol/src/protocol.rs and
# history/src/rollout_payload.rs, response items in protocol/src/models.rs,
# `item_completed` items in protocol/src/items.rs, which lines are written in
# rollout/src/policy.rs, MCP names (`namespace` "mcp__<server>__") in
# codex-mcp/src/tools.rs, exit-code text in core/src/tools/mod.rs and
# core/src/tools/context.rs, and the `<skill>` message in ext/skills/src/fragments.rs.

CODEX_MAIN = "019a7e10-0000-7000-8000-00000000c0de"
CODEX_SUB = "019a7e10-0000-7000-8000-0000000005ab"


def codex_line(second: int, kind: str, payload: dict) -> dict:
    return {"timestamp": at(second), "type": kind, "payload": payload}


def codex_call(second: int, call_id: str, name: str, args: dict, namespace: str | None = None) -> dict:
    payload = {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": call_id}
    if namespace:
        payload["namespace"] = namespace
    return codex_line(second, "response_item", payload)


def codex_usage(input_tokens: int, cached: int, output: int, reasoning: int = 0) -> dict:
    return {"input_tokens": input_tokens, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
            "output_tokens": output, "reasoning_output_tokens": reasoning, "total_tokens": input_tokens + output}


def codex_record(second: int, response_id: str, usage: dict) -> dict:
    return codex_line(second, "token_usage_record", {
        "thread_id": CODEX_MAIN, "turn_id": "turn-1", "session_id": CODEX_MAIN, "root_turn_id": "turn-1",
        "response_id": response_id, "usage": usage, "turn_token_usage": usage, "thread_token_usage": usage})


def codex_typed(second: int, text: str) -> dict:
    return codex_line(second, "event_msg", {"type": "item_completed", "thread_id": CODEX_MAIN, "turn_id": "turn-1",
                                            "item": {"type": "UserMessage", "id": "u", "content": [{"type": "text", "text": text}]}})


def codex_meta(thread: str, cwd: str, **extra) -> dict:
    return {"id": thread, "session_id": thread, "timestamp": at(0), "cwd": cwd, "originator": "codex_cli_rs",
            "cli_version": "0.169.0", "source": "cli", "model_provider": "openai", "history_mode": "paginated", **extra}


def working_tree_skill(root: Path) -> Path:
    """A file under a `skills/` folder in the working tree, which no skill load names."""
    path = root / "work" / "skills" / "myapp" / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Not a loaded skill\n")
    return path


def build_codex(root: Path) -> tuple[Path, int]:
    """A paginated-history session (the default for new threads in 0.169.0),
    with one subagent in its own rollout file. Returns the main file and the
    expected skill bytes."""
    reference = reference_file(root)
    not_a_skill = working_tree_skill(root)
    skill_md = reference.parent.parent / "SKILL.md"
    skill_text = (f"<skill>\n<name>catalyst-develop</name>\n<path>{skill_md}</path>\n"
                  "# Develop\n</skill>")
    day = root / "codex" / "sessions" / "2026" / "11" / "17"
    main = write_jsonl(day / f"rollout-2026-11-17T10-00-00-{CODEX_MAIN}.jsonl", [
        codex_line(0, "session_meta", codex_meta(CODEX_MAIN, "/work")),
        codex_line(0, "turn_context", {"turn_id": "turn-1", "cwd": "/work", "model": "gpt-5.5-codex", "effort": "medium"}),
        # Injected context is a user-role message too, but not a typed prompt.
        codex_line(0, "response_item", {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>\n<cwd>/work</cwd>\n</environment_context>"}]}),
        codex_typed(1, f"connect my agent, token {SECRET}"),
        codex_call(2, "c1", "catalyst_list_apps", {"project": SECRET, "region": "r1"}, namespace="mcp__catalyst__"),
        codex_line(3, "event_msg", {"type": "item_completed", "item": {
            "type": "McpToolCall", "id": "c1", "server": "catalyst", "tool": "catalyst_list_apps",
            "arguments": {"project": SECRET}, "status": "failed", "error": {"message": "denied"}}}),
        codex_record(3, "resp_1", codex_usage(1000, 800, 50, 20)),
        # Re-sent with rate-limit updates: ignored once records exist.
        codex_line(3, "event_msg", {"type": "token_count", "info": {"total_token_usage": codex_usage(1000, 800, 50)}}),
        # The same call again, keys in another order: repeated.
        codex_call(4, "c2", "catalyst_list_apps", {"region": "r1", "project": SECRET}, namespace="mcp__catalyst__"),
        codex_call(4, "c3", "diagrid_get_app", {"app": "a"}, namespace="mcp__catalyst__"),
        codex_call(5, "c4", "exec_command", {"cmd": f"sed -n 1,200p {reference}"}),
        codex_call(5, "c4b", "exec_command", {"cmd": f"cat {not_a_skill}"}),  # not a loaded skill's file
        codex_line(5, "response_item", {"type": "function_call_output", "call_id": "c4",
                                        "output": "Wall time: 0.0100 seconds\nProcess exited with code 0\nOutput:\n# Tunnels"}),
        codex_call(6, "c5", "shell", {"command": ["bash", "-lc", "false"]}),
        codex_line(6, "response_item", {"type": "function_call_output", "call_id": "c5",
                                        "output": "Exit code: 1\nWall time: 0.1 seconds\nOutput:\n"}),
        # The same failure reported again as a completed item: counted once.
        codex_line(6, "event_msg", {"type": "item_completed", "item": {
            "type": "CommandExecution", "id": "c5", "command": ["bash", "-lc", "false"], "status": "failed", "exit_code": 1}}),
        codex_call(7, "c6", "request_user_input", {"questions": [{"id": "q", "header": "Project", "question": "which?"}]}),
        codex_line(8, "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": skill_text}]}),
        codex_line(9, "response_item", {"type": "custom_tool_call", "call_id": "c7", "name": "apply_patch", "input": "*** Begin Patch"}),
        codex_record(10, "resp_2", codex_usage(2000, 1500, 80)),
        codex_record(10, "resp_2", codex_usage(2000, 1500, 80)),  # the same response twice: counted once
        codex_typed(11, "yes, project a"),
    ])
    write_jsonl(day / f"rollout-2026-11-17T10-00-12-{CODEX_SUB}.jsonl", [
        codex_line(12, "session_meta", codex_meta(
            CODEX_SUB, "/work", session_id=CODEX_MAIN, parent_thread_id=CODEX_MAIN, thread_source="subagent",
            source={"subagent": {"thread_spawn": {"parent_thread_id": CODEX_MAIN, "depth": 1}}})),
        codex_line(12, "turn_context", {"turn_id": "turn-s", "cwd": "/work", "model": "gpt-5.5-codex"}),
        codex_typed(13, "subagent prompt"),  # not a user turn
        codex_call(14, "s1", "request_user_input", {"questions": [{"id": "s", "question": "sub?"}]}),  # not a user turn
        codex_call(15, "s2", "shell", {"command": ["ls"]}),
        codex_record(30, "resp_3", codex_usage(300, 0, 10)),
    ])
    return main, len(skill_text.encode("utf-8")) + reference.stat().st_size


def build_codex_legacy(root: Path) -> Path:
    """A legacy-history session, as older Codex writes: typed prompts as
    `user_message` events, MCP results as `mcp_tool_call_end`, no
    `token_usage_record`, so tokens come from the `token_count` running total.
    Shapes from protocol/src/protocol.rs (TokenCountEvent, McpToolCallEndEvent,
    UserMessageEvent) and core/src/session/mod.rs (which re-sends a total with
    rate limits and overwrites it with only `total_tokens` set)."""
    def count(usage):
        return codex_line(2, "event_msg", {"type": "token_count", "info": None if usage is None else {
            "total_token_usage": usage, "last_token_usage": usage, "model_context_window": 272000}, "rate_limits": {}})

    return write_jsonl(root / "legacy" / "rollout-2026-01-02T03-04-05-legacy.jsonl", [
        codex_line(0, "session_meta", {"id": "legacy", "cwd": "/work", "cli_version": "0.130.0", "source": "cli"}),
        codex_line(0, "turn_context", {"cwd": "/work", "model": "gpt-5-codex"}),
        codex_line(1, "event_msg", {"type": "user_message", "message": "list my apps"}),
        codex_call(1, "x", "mcp__catalyst__catalyst_whoami", {}),
        codex_line(2, "event_msg", {"type": "mcp_tool_call_end", "call_id": "x", "invocation": {
            "server": "catalyst", "tool": "catalyst_whoami", "arguments": {}}, "result": {"Err": "boom"}}),
        count(codex_usage(100, 50, 10)),
        count(codex_usage(100, 50, 10)),  # re-sent with a rate-limit update
        count(None),  # rate limits only
        count({"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 272000}),  # an estimate
        count(codex_usage(250, 120, 30)),
    ])


# Copilot CLI ---------------------------------------------------------------
# Shapes from the session-events schema in @github/copilot-sdk 1.0.34
# (dist/generated/session-events.d.ts, Copilot CLI 1.0.112) and from real lines
# pasted in https://github.com/github/copilot-cli/issues/4733 (session.start,
# session.shutdown, 1.0.83), /issues/2000 (user.message, 1.0.4), /issues/4202
# (tool.execution_start and _complete, 1.0.73) and /issues/4320 (MCP names).

COPILOT_ID = "8f9a2c4e-5b1d-4e6f-9a3b-2c7d8e9f0a1b"


def event(second: int, kind: str, data: dict, **extra) -> dict:
    return {"type": kind, "data": data, "id": f"e-{kind}-{second}", "timestamp": at(second), "parentId": None, **extra}


def tool_start(second: int, call_id: str, name: str, args: dict, server: str | None = None, **extra) -> dict:
    data = {"toolCallId": call_id, "toolName": f"{server}-{name}" if server else name, "arguments": args}
    if server:
        data |= {"mcpServerName": server, "mcpToolName": name}
    return event(second, "tool.execution_start", data, **extra)


def build_copilot(root: Path, shutdown: bool = True, session_id: str = COPILOT_ID) -> tuple[Path, int]:
    """Returns the events.jsonl path and the expected skill bytes."""
    reference = reference_file(root)
    not_a_skill = working_tree_skill(root)
    skill_md = reference.parent.parent / "SKILL.md"
    skill_body = "# Develop\n\nUse catalyst_get_connection.\n"
    lines = [
        event(0, "session.start", {"sessionId": session_id, "version": 1, "producer": "copilot-agent",
                                   "copilotVersion": "1.0.112", "startTime": at(0), "selectedModel": "claude-sonnet-4.6",
                                   "context": {"cwd": "/work"}}),
        event(1, "user.message", {"content": f"connect my agent, token {SECRET}", "transformedContent": SECRET,
                                  "source": "user", "attachments": []}),
        event(2, "assistant.turn_start", {"turnId": "0", "model": "claude-sonnet-4.6"}),
        tool_start(3, "t1", "catalyst_list_apps", {"project": SECRET}, server="catalyst"),
        event(4, "tool.execution_complete", {"toolCallId": "t1", "success": False,
                                             "error": {"message": "denied", "code": "failure"}}),
        event(5, "skill.invoked", {"name": "catalyst-develop", "path": str(skill_md),
                                   "content": skill_body, "source": "personal-copilot", "trigger": "agent-invoked"}),
        # The skill's hidden injection is a user.message too, but not typed.
        event(5, "user.message", {"content": skill_body, "source": "skill-catalyst-develop"}),
        event(6, "assistant.turn_start", {"turnId": "1", "model": "claude-sonnet-4.6"}),
        tool_start(7, "t2", "catalyst_list_apps", {"project": SECRET}, server="catalyst"),  # repeated
        event(7, "tool.execution_complete", {"toolCallId": "t2", "success": True, "result": {"content": SECRET}}),
        tool_start(8, "t3", "diagrid_get_app", {"app": "a"}, server="catalyst"),
        tool_start(9, "t4", "ask_user", {"question": "which project?"}),
        tool_start(10, "t5", "view", {"path": str(reference)}),
        tool_start(10, "t5b", "view", {"path": str(reference.parent)}),  # a directory: 0 bytes
        tool_start(10, "t5c", "view", {"path": str(not_a_skill)}),  # not a loaded skill's file
        event(11, "user.message", {"content": "yes, project a", "source": "user"}),
        event(12, "assistant.turn_start", {"turnId": "2"}),
        tool_start(13, "t6", "task", {"prompt": "look around"}),
        event(13, "subagent.started", {"toolCallId": "t6", "agentName": "explore", "agentDisplayName": "Explore",
                                       "agentDescription": "Explore the code"}),
        # Subagent events sit in the same file, marked with the agent's id.
        event(14, "user.message", {"content": "look around", "source": "agent-t6"}, agentId="t6"),
        tool_start(15, "t7", "bash", {"command": "ls"}, agentId="t6"),
        tool_start(16, "t8", "ask_user", {"question": "sub?"}, agentId="t6"),  # not a wait on the person
        event(17, "user.message", {"content": "continue", "isAutopilotContinuation": True}),  # not typed
        event(18, "assistant.message", {"content": "Done.", "model": "claude-sonnet-4.6"}),
    ]
    if shutdown:
        lines.append(event(20, "session.shutdown", {
            "shutdownType": "routine", "totalApiDurationMs": 9000, "sessionStartTime": 1795000000000,
            "codeChanges": {"linesAdded": 0, "linesRemoved": 0, "filesModified": []},
            "modelMetrics": {"claude-sonnet-4.6": {
                "requests": {"count": 4, "cost": 1},
                "usage": {"inputTokens": 5000, "outputTokens": 300, "cacheReadTokens": 4000,
                          "cacheWriteTokens": 0, "reasoningTokens": 40}}},
            "currentModel": "claude-sonnet-4.6"}))
    path = write_jsonl(root / "copilot" / "session-state" / session_id / "events.jsonl", lines)
    return path, len(skill_body.encode("utf-8")) + reference.stat().st_size


# Running -------------------------------------------------------------------


def run(argv: list[str]) -> str:
    return run_both(argv)[0]


def run_both(argv: list[str]) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        session_metrics.main(argv)
    return out.getvalue(), err.getvalue()


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, got, want) -> None:
        checks.append((name, got == want, f"wanted {want!r}, got {got!r}"))

    def no_secret(name: str, argv: list[str]) -> None:
        # Compared as a bool so a failure never prints the output holding the secret.
        check(name, SECRET in run(argv) + run([*argv, "--json"]), False)

    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
        "CLAUDE_CONFIG_DIR": tmp, "CODEX_HOME": str(Path(tmp) / "codex"), "COPILOT_HOME": str(Path(tmp) / "copilot"),
    }):
        root = Path(tmp)

        # Claude Code
        session, preamble_bytes, reference_bytes = build_claude(root)
        m = session_metrics.measure(session)
        check("claude: tokens in once per response id, cache reads and writes included, subagent added",
              m["tokens_in"], 115 + 203 + 21)
        check("claude: tokens out", m["tokens_out"], 7 + 11 + 2)
        check("claude: model requests are response ids, not lines, and not synthetic", m["model_requests"], 3)
        check("claude: tool calls, replayed request history ignored", m["tool_calls"], 15)
        check("claude: diagrid calls match both name sets and nothing else", m["diagrid_calls"], 3)
        check("claude: failed calls come from is_error", m["failed_calls"], 1)
        check("claude: a call with the same tool and arguments is repeated", m["repeated_calls"], 1)
        check("claude: user turns are typed prompts after the first plus questions; not reminders, "
              "command output, interrupts or subagents", m["user_turns"], 2)
        check("claude: skills loaded, with bytes: not a working tree's skills/ folder, not SKILL.md read after "
              "its load in the same log, 0 for a file now gone", m["skills"],
              {"catalyst-develop": preamble_bytes + reference_bytes, "catalyst-operate": 0})
        check("claude: plugin version from the loaded skill's path", m["plugin"], "0.8.1")

        # A session that only Reads a skill's file from the plugin cache, with no load.
        read_only = root / "projects" / "-other" / "s2.jsonl"
        read_only.parent.mkdir(parents=True)
        cached = root / "cache" / "diagrid" / "catalyst-ai" / "0.9.0" / "skills" / "catalyst-operate" / "SKILL.md"
        read_only.write_text(json.dumps(assistant("m9", USAGE_1, 0, tool_use("Read", file_path=str(cached)))) + "\n")
        r = session_metrics.measure(read_only)
        check("plugin version from a Read under the plugin cache, with no skill loaded",
              (r["plugin"], r["skills"]), ("0.9.0", {"catalyst-operate": 0}))
        # The same under the renamed plugin's cache directory.
        renamed = root / "projects" / "-renamed" / "s5.jsonl"
        renamed.parent.mkdir(parents=True)
        cached = root / "cache" / "diagrid" / "diagrid" / "0.10.0" / "skills" / "diagrid-operate" / "SKILL.md"
        renamed.write_text(json.dumps(assistant("m10", USAGE_1, 0, tool_use("Read", file_path=str(cached)))) + "\n")
        r = session_metrics.measure(renamed)
        check("plugin version and skill from the diagrid plugin's cache",
              (r["plugin"], r["skills"]), ("0.10.0", {"diagrid-operate": 0}))
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
        check("claude: client and model", (m["client"], m["model"]), ("claude-code 2.1.325", "claude-opus-5-5"))
        check("claude: wall time from first to last line, subagent included; bad and naive timestamps "
              "do not stop the run", m["wall_seconds"], 10)
        check("claude: subagent logs are found", m["subagents"], 1)
        check("claude: nothing is unavailable", m["unavailable"], [])

        make_old(session)
        text = run([str(session)])
        table = text.splitlines()
        check("prints a header, a divider and one row", len(table), 3)
        check("every line of the table has the same number of columns", len({line.count("|") for line in table}), 1)
        no_secret("claude: nothing typed and no tool argument reaches the output", [str(session)])

        older = session.parent / "s0.jsonl"
        older.write_text("")
        make_old(older, 7200)
        check("a project folder is the directory with every other character as -",
              session_metrics.project_dir_for(Path("/work")), root / "projects" / "-work")
        check("--session finds a session by id", run(["--session", "s1"]), text)
        check("claude --latest picks the newest session for this directory",
              session_metrics.find_session(latest("claude"), cwd=Path("/work")), session)

        # Edge case 1: the folder named after this directory has no session (a
        # long path is shortened, or the directory was reached through a
        # symlink), so the newest log that recorded this cwd is used.
        real = root / "real"
        real.mkdir()
        link = root / "link"
        link.symlink_to(real)
        shortened = write_jsonl(root / "projects" / "-shortened-name-1a2b3c" / "s9.jsonl", [
            {**user("hi", 0, origin={"kind": "human"}), "cwd": str(real.resolve())}])
        check("claude --latest falls back to the recorded cwd when the project folder is empty",
              session_metrics.find_session(latest("claude"), cwd=link), shortened)
        previous = os.getcwd()
        try:
            os.chdir(link)
            with mock.patch.dict(os.environ, {"PWD": str(link)}):
                check("this directory is its resolved path and the symlinked $PWD",
                      session_metrics.here(), {str(real.resolve()), str(link)})
        finally:
            os.chdir(previous)

        # Edge case 2: a timestamp with no zone is UTC (the fixture above has one too).
        check("a timestamp with no zone is read as UTC", session_metrics.parse_time("2026-11-17T10:00:04"),
              datetime(2026, 11, 17, 10, 0, 4, tzinfo=timezone.utc))

        # Edge case 3: a log written in the last minute may still be running.
        os.utime(session)
        out, err = run_both([str(session)])
        check("a log written in the last minute warns on stderr", "may still be running" in err, True)
        check("and still prints the row", out, text)
        make_old(session)
        check("an older log does not warn", run_both([str(session)])[1], "")

        # Codex
        codex, codex_skill_bytes = build_codex(root)
        m = session_metrics.measure(codex, "codex")
        check("codex: tokens in are input_tokens (cached already inside), once per response, subagent added",
              m["tokens_in"], 1000 + 2000 + 300)
        check("codex: tokens out are output_tokens (reasoning already inside)", m["tokens_out"], 50 + 80 + 10)
        check("codex: model requests are token_usage_record lines by response id", m["model_requests"], 3)
        check("codex: tool calls, subagent included", m["tool_calls"], 10)
        check("codex: diagrid calls from namespace plus name", m["diagrid_tools"],
              {"mcp__catalyst__catalyst_list_apps": 2, "mcp__catalyst__diagrid_get_app": 1})
        check("codex: failed from a failed MCP item and a non-zero exit code, each call once", m["failed_calls"], 2)
        check("codex: repeated ignores argument order", m["repeated_calls"], 1)
        check("codex: user turns are typed prompts after the first plus request_user_input, "
              "not injected context or subagents", m["user_turns"], 2)
        check("codex: skills from a <skill> message and a shell read under its directory, "
              "not a working tree's skills/ folder",
              m["skills"], {"catalyst-develop": codex_skill_bytes})
        check("codex: client, model and wall time", (m["client"], m["model"], m["wall_seconds"]),
              ("codex 0.169.0", "gpt-5.5-codex", 30))
        check("codex: the subagent's rollout file is found", m["subagents"], 1)
        check("codex: a plugin version the log does not hold is unavailable, not guessed", m["unavailable"], ["plugin"])
        make_old(codex)
        no_secret("codex: nothing typed and no tool argument reaches the output", ["--client", "codex", str(codex)])

        legacy = session_metrics.measure(build_codex_legacy(root), "codex")
        check("codex legacy: tokens from the last real running total, requests from its changes",
              (legacy["tokens_in"], legacy["tokens_out"], legacy["model_requests"]), (250, 30, 2))
        check("codex legacy: a flat MCP name and an Err result", (legacy["diagrid_calls"], legacy["failed_calls"]), (1, 1))

        elsewhere = write_jsonl(codex.parent / "rollout-2026-11-17T11-00-00-other.jsonl",
                                [codex_line(0, "session_meta", codex_meta("other", "/elsewhere"))])
        check("codex --latest skips a newer session in another directory and every subagent file",
              session_metrics.find_session(latest("codex"), cwd=Path("/work")), codex)
        check("codex --latest finds the other directory's session",
              session_metrics.find_session(latest("codex"), cwd=Path("/elsewhere")), elsewhere)
        check("codex --session finds a rollout by thread id", session_metrics.find_session(by_id("codex", CODEX_MAIN)), codex)

        # Copilot CLI
        copilot, copilot_skill_bytes = build_copilot(root)
        m = session_metrics.measure(copilot, "copilot")
        check("copilot: tokens from session.shutdown, input holding cache reads",
              (m["tokens_in"], m["tokens_out"]), (5000, 300))
        check("copilot: model requests from requests.count", m["model_requests"], 4)
        check("copilot: tool calls, subagent included", m["tool_calls"], 10)
        check("copilot: diagrid calls from the MCP server and tool names", m["diagrid_tools"],
              {"mcp__catalyst__catalyst_list_apps": 2, "mcp__catalyst__diagrid_get_app": 1})
        check("copilot: failed from success false", m["failed_calls"], 1)
        check("copilot: repeated", m["repeated_calls"], 1)
        check("copilot: user turns are typed prompts after the first plus ask_user; not skill, "
              "subagent or autopilot messages", m["user_turns"], 2)
        check("copilot: skills from skill.invoked and a view under its directory; a directory view is 0 bytes, "
              "a working tree's skills/ folder is not a skill",
              m["skills"], {"catalyst-develop": copilot_skill_bytes})
        check("copilot: client, model, wall time and subagents",
              (m["client"], m["model"], m["wall_seconds"], m["subagents"]),
              ("copilot 1.0.112", "claude-sonnet-4.6", 20, 1))
        make_old(copilot)
        no_secret("copilot: nothing typed and no tool argument reaches the output", ["--client", "copilot", str(copilot)])

        killed, _ = build_copilot(root, shutdown=False, session_id="killed")
        make_old(killed, 7200)
        m = session_metrics.measure(killed, "copilot")
        check("copilot killed: no shutdown means no tokens, and requests fall back to turns",
              (m["tokens_in"], m["tokens_out"], m["model_requests"]), (None, None, 3))
        check("copilot killed: the missing fields are listed", m["unavailable"], ["plugin", "tokens_in", "tokens_out"])
        cells = run(["--client", "copilot", str(killed)]).splitlines()[2].split(" | ")
        check("copilot killed: the row shows - for the missing tokens", cells[3:5], ["-", "-"])

        # A session whose start event has no context: workspace.yaml has the cwd.
        bare = write_jsonl(root / "copilot" / "session-state" / "bare" / "events.jsonl",
                           [event(0, "session.start", {"sessionId": "bare", "copilotVersion": "1.0.112"})])
        (bare.parent / "workspace.yaml").write_text("id: bare\ncwd: /yaml-only\nbranch: main\n")
        check("copilot --latest picks the newest session recorded for this directory",
              session_metrics.find_session(latest("copilot"), cwd=Path("/work")), copilot)
        check("copilot --latest reads the cwd from workspace.yaml when the start event lacks it",
              session_metrics.find_session(latest("copilot"), cwd=Path("/yaml-only")), bare)
        check("copilot --session finds a session by id", session_metrics.find_session(by_id("copilot", "killed")), killed)

        # Values of the wrong type where the Codex and Copilot logs should have
        # strings or objects: skipped, never a crash.
        odd_codex = write_jsonl(root / "odd-codex" / "rollout-odd.jsonl", [
            codex_line(0, "session_meta", ["not", "an", "object"]),
            codex_line(1, "turn_context", {"model": ["gpt"]}),
            codex_line(2, "token_usage_record", {"response_id": ["r"], "usage": ["x"]}),
            codex_line(3, "token_usage_record", {"response_id": "r2", "usage": {"input_tokens": "7", "output_tokens": None}}),
            codex_line(4, "response_item", {"type": "function_call", "name": ["x"], "namespace": {"n": 1}, "arguments": "{}"}),
            codex_line(5, "event_msg", {"type": "item_completed", "item": ["x"]}),
            codex_line(6, "event_msg", {"type": "item_completed", "item": {
                "type": "UserMessage", "content": [{"type": "text", "text": ["x"]}]}}),
            codex_line(7, "event_msg", {"type": "mcp_tool_call_end", "call_id": ["c"], "result": {"Ok": ["x"]}}),
            codex_line(8, "event_msg", {"type": "token_count", "info": {"total_token_usage": ["x"]}}),
        ])
        o = session_metrics.measure(odd_codex, "codex")
        check("codex: non-object payloads and non-string names, models and ids are skipped",
              (o["model"], o["tools"], o["tokens_in"], o["tokens_out"], o["model_requests"], o["failed_calls"]),
              (None, {"?": 1}, 7, 0, 2, 0))
        odd_copilot = write_jsonl(root / "odd-copilot" / "events.jsonl", [
            event(0, "session.start", {"copilotVersion": ["1"], "selectedModel": {"m": 1}, "context": "x"}),
            event(1, "assistant.turn_start", {"model": ["m"]}),
            tool_start(2, ["t"], ["view"], {"path": ["x"]}),
            event(3, "skill.invoked", {"name": ["s"], "content": "abc", "pluginVersion": ["1"]}),
            event(4, "session.shutdown", {"modelMetrics": {"m": {"usage": ["x"], "requests": {"count": "2"}}}}),
        ])
        o = session_metrics.measure(odd_copilot, "copilot")
        check("copilot: non-object data and non-string names, models and versions are skipped",
              (o["client"], o["model"], o["tools"], o["skills"], o["tokens_in"], o["model_requests"]),
              ("copilot", "m", {"?": 1}, {"?": 3}, 0, 1))

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
