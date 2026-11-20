#!/usr/bin/env python3
"""Measure one finished coding-agent session: Claude Code, Codex or Copilot CLI.

Wall-clock minutes are a poor measure of a skill: they depend on the task, the
network and whether anyone is watching. So a run is described by what the
coding agent actually spent, read back from the session log the client already
writes. Nothing runs during the session and nothing ships in the plugin: this
reads a finished log and prints one Markdown table row, the same columns for
every client so a week of runs across all three can sit in one table.

    python3 scripts/session_metrics.py --latest                   # newest Claude Code session here
    python3 scripts/session_metrics.py --client codex --latest    # newest Codex session here
    python3 scripts/session_metrics.py --client copilot --latest  # newest Copilot CLI session here
    python3 scripts/session_metrics.py --session <id>             # one session by id
    python3 scripts/session_metrics.py --client codex path/to/rollout.jsonl
    python3 scripts/session_metrics.py --latest --json            # full breakdown, per tool and per skill

`--latest` picks the newest session whose recorded working directory is this
one (the resolved path, or `$PWD` when that leads to the same place). A log
written to in the last minute gets a warning on stderr: the session may still
be running, and its numbers are not final. A cell the log cannot fill prints
`-` and is listed under `unavailable` in `--json`; no number is ever guessed.

What the columns mean, the same way for every client:

- tokens in: everything the model read, cached input included. tokens out:
  everything it wrote. model requests: one per model response, never one per
  log line.
- tool calls (all / diagrid / failed / repeated). Diagrid calls match
  `diagrid_*` after any MCP prefix, or `catalyst_*` from before the plugin was
  renamed. A call is repeated when the same tool got the same arguments
  earlier in the session.
- user turns: typed prompts after the first, plus questions the agent asked the
  person. Each is a wait on the person.
- skills (bytes): skill text the model read. Bytes, not tokens: the tokenizer
  differs by model.
- Subagent work is added to every count except user turns, because a skill
  that spawns a subagent still spent it.

How each client's log gives those numbers:

- Claude Code (`~/.claude/projects/<dir>/<id>.jsonl`, subagents in
  `<id>/subagents/`). One response is written as several `assistant` lines,
  one per content block, each repeating the same `message.id` and `usage`, so
  usage is taken once per id. Input is fresh input plus cache reads plus cache
  writes; output includes thinking. Tool calls come from `tool_use` blocks on
  `assistant` lines only: `api-request-blob` lines replay earlier calls as
  request history. Failed is `is_error` on the result. Questions are
  `AskUserQuestion` calls. Skill text is the hidden message that carries a
  loaded skill (it starts with "Base directory for this skill:") plus `Read`
  calls on a skill's files. A Read counts only when its path is under a skill
  base directory one of those messages named, or under the plugin cache
  (`diagrid/<version>/skills/`, or `catalyst-ai/<version>/skills/` before
  0.10.0), so a `skills/` folder in the working tree is not taken for a skill.
  A Read of `SKILL.md` after that skill was loaded in the same log (main or
  subagent) is not counted again, and a file that no longer exists names its
  skill with 0 bytes. A Read counts only the lines it loaded: from `offset`
  for `limit` lines, or for the 2000 lines Claude Code's Read stops at when it
  is given no limit, so a file read in pages is counted once. A Read under the plugin cache also gives the plugin
  version.
- Codex (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, one file per
  subagent, tied to the session by `session_meta.session_id` or
  `parent_thread_id`). Tokens and requests come from `token_usage_record`
  lines, one per completed response; logs from before those lines existed fall
  back to the running total in `token_count` events. OpenAI counts cached
  input inside `input_tokens` and reasoning inside `output_tokens`, so both are
  already in. Tool calls are `function_call`, `custom_tool_call`,
  `local_shell_call` and `web_search_call` items; an MCP call's name is its
  `namespace` plus `name`. Failed is a non-zero exit code in the output text, a
  failed or declined `item_completed` item, or an `Err` or `isError` MCP
  result. Questions are `request_user_input` calls. Typed prompts are
  `user_message` events or `UserMessage` items, without the context Codex
  injects (AGENTS.md, environment, skills). Skill text is a `<skill>` message
  plus shell commands that read a `.md` file under the directory of a skill a
  `<skill>` message loaded (its `<path>`) or under the plugin cache, as for
  Claude Code. The plugin version is not in a Codex log unless a skill path carries it.
- Copilot CLI (`~/.copilot/session-state/<id>/events.jsonl`, subagents in the
  same file). Tokens exist only in the `session.shutdown` event, as totals per
  model, so a session that was killed has none: those cells print `-`. Input
  is `inputTokens`, which holds cache reads in the real logs we found; output
  is `outputTokens`, whose `reasoningTokens` look to be part of it. Neither is
  documented. Requests are `requests.count` from that event, or one per
  `assistant.turn_start` when it is missing. Tool calls are
  `tool.execution_start`, named `mcp__<server>__<tool>` for MCP tools, and
  failed is `success: false` on `tool.execution_complete`. Questions are
  `ask_user` calls. Typed prompts are `user.message` events whose `source` is
  the user. Skill text is `skill.invoked` content plus `view` calls on files
  under the directory of a skill `skill.invoked` loaded (its `path`) or under
  the plugin cache, so a `skills/` folder in the working tree is not taken for
  a skill. A `view` of a directory counts 0 bytes.

The Codex reader is built from the openai/codex source at tag rust-v0.169.0
(codex-rs/protocol, codex-rs/rollout), and the Copilot reader from the
session-events schema in @github/copilot-sdk 1.0.34 (Copilot CLI 1.0.112) plus
event lines pasted in github/copilot-cli issues. Neither has been checked
against a real log from this team yet; the Claude Code reader has.

It prints counts, names and sizes only, never prompts, arguments or results,
because a session log can hold connection values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SKILL_PREAMBLE = "Base directory for this skill:"
PLUGIN_TOOL = re.compile(r"(?:^|__)(?:catalyst|diagrid)_[a-z0-9_]+$")
PLUGIN_VERSION = re.compile(r"/(?:diagrid|catalyst-ai)/(\d+\.\d+\.\d+[^/]*)/skills/")
READ_DEFAULT_LIMIT = 2000  # lines Claude Code's Read returns when it is given no limit
PLUGIN_SKILL = re.compile(r"/(?:diagrid|catalyst-ai)/\d+\.\d+\.\d+[^/]*/skills/([^/]+)/")
SKILL_FILE_IN_COMMAND = re.compile(r"""[^\s'"]*/skills/[^/\s'"]+/[^\s'"]*\.md""")
NOT_TYPED = (
    "<system-reminder>", "<task-notification>", "<local-command-", "<bash-stdout>", "<bash-stderr>",
    "[Request interrupted",
)
CODEX_INJECTED = (
    "<environment_context>", "<user_instructions>", "# AGENTS.md instructions", "<skill>", "<turn_aborted>",
)
CODEX_SHELL_TOOLS = {"shell", "shell_command", "exec_command", "container.exec"}
EXIT_CODE = re.compile(r"(?:Exit code:|Process exited with code) (-?\d+)")
STILL_RUNNING_SECONDS = 60

COLUMNS = [
    "client", "model", "plugin", "tokens in", "tokens out", "model requests",
    "tool calls (all / diagrid / failed / repeated)", "user turns", "skills (bytes)", "wall time",
]
HEADER = "| " + " | ".join(COLUMNS) + " |"
DIVIDER = "|" + "---|" * len(COLUMNS)
# Fields a log may be unable to fill. Each is None then, never a guess.
MAYBE_UNAVAILABLE = ("model", "plugin", "tokens_in", "tokens_out", "model_requests", "wall_seconds")


@dataclass
class Tally:
    """What one client reader found. The shared code below turns it into the row."""

    client: str
    session: str = ""
    versions: set = field(default_factory=set)
    models: set = field(default_factory=set)
    plugin: set = field(default_factory=set)
    tokens_in: int | None = None
    tokens_out: int | None = None
    requests: int | None = None
    calls: list = field(default_factory=list)  # (name, canonical arguments), in order
    failed: int = 0
    typed: int = 0
    questions: int = 0
    skills: Counter = field(default_factory=Counter)
    times: list = field(default_factory=list)
    subagents: int = 0
    bases: dict = field(default_factory=dict)  # skill base directory -> skill name, from the loaded skills
    viewed: list = field(default_factory=list)  # whole files read, attributed once every loaded skill is known

    def call(self, name: str, args) -> None:
        self.calls.append((name, canonical(args)))

    def time(self, value) -> None:
        if (when := parse_time(value)) is not None:
            self.times.append(when)

    def skill_loaded(self, name: str, path: str | None) -> None:
        """A skill the client loaded from `path`, its SKILL.md or its directory.
        Files under that directory count toward it."""
        if not path:
            return
        base = Path(path).expanduser()
        if base.name == "SKILL.md":
            base = base.parent
        self.bases[str(base)] = name

    def skill_file(self, path: str, base: str | None = None) -> None:
        """A whole file the model read. It counts toward a skill only when it is
        under a loaded skill's directory or under the plugin cache; see
        `count_skill_files`."""
        target = Path(path).expanduser()
        if base and not target.is_absolute():
            target = Path(base) / target
        self.viewed.append(str(target))

    def count_skill_files(self) -> None:
        """Add the size of every read file that belongs to a skill, the same
        way `skill_of` decides it for Claude Code, so a `skills/` folder in the
        working tree is not taken for a skill. A directory counts 0 bytes."""
        for path in self.viewed:
            if (name := skill_of(path, self.bases)) is None:
                continue
            target = Path(path)
            try:
                size = target.stat().st_size if target.is_file() else 0
            except OSError:
                size = 0
            self.skills[name] += size
            self.plugin.update(PLUGIN_VERSION.findall(path))


def canonical(args) -> str:
    """Arguments as one comparable string, so key order or a JSON-encoded
    string does not hide a repeat. Never printed."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args
    return json.dumps(args, sort_keys=True)


def parse_time(value) -> datetime | None:
    """ISO 8601. A timestamp with no zone is taken as UTC, so it can be
    compared with the ones that have one."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def read_lines(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a session still being written can end mid-line
            if isinstance(entry, dict):  # not a bare array, string or number
                yield entry


# Claude Code ---------------------------------------------------------------


def projects_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"


def project_dir_for(cwd: Path) -> Path:
    """Claude Code files a session under its working directory, with every
    character that is not a letter or digit replaced by `-`. A very long path
    is shortened, which is why `--latest` falls back to the recorded `cwd`."""
    return projects_dir() / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def claude_logs() -> list[Path]:
    return list(projects_dir().glob("*/*.jsonl"))


def claude_cwd(path: Path) -> str | None:
    for entry in read_lines(path):
        if isinstance(entry.get("cwd"), str):
            return entry["cwd"]
    return None


def message_of(entry: dict) -> dict:
    return obj(entry.get("message"))


def obj(value) -> dict:
    """A logged value that should be an object, or {} when it is not one."""
    return value if isinstance(value, dict) else {}


def text_or_none(value) -> str | None:
    """A logged value that should be a string, or None when it is not one, so
    an odd log shape is skipped rather than put in a set or joined to text."""
    return value if isinstance(value, str) and value else None


def blocks(entry: dict) -> list:
    content = message_of(entry).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def text_of(entry: dict) -> str:
    content = message_of(entry).get("content")
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in blocks(entry) if b.get("type") == "text" and isinstance(b.get("text"), str))


def is_typed_prompt(entry: dict) -> bool:
    """A prompt the person typed, not a tool result, a reminder or a skill load."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    if any(b.get("type") == "tool_result" for b in blocks(entry)):
        return False
    origin = entry.get("origin")
    if isinstance(origin, dict):  # newer clients say who sent it
        return origin.get("kind") == "human"
    # Lines with no origin, which current clients still write for command
    # output, `!` shell output and an interrupt: none of those is a prompt.
    return not text_of(entry).lstrip().startswith(NOT_TYPED)


def skill_of(path: str, bases: dict[str, str]) -> str | None:
    """The skill a read file belongs to: under a base directory a loaded skill
    named, or under the plugin cache. None for any other file."""
    for base, name in bases.items():
        if path.startswith(base.rstrip("/") + "/"):
            return name
    found = PLUGIN_SKILL.search(path)
    return found.group(1) if found else None


def read_bytes(path: str, args: dict) -> int:
    """The bytes a Read loaded: the lines from `offset` (1-based, default 1)
    for `limit` lines, or for the client's default when no limit was given.
    An offset or limit that is not a number falls back to those defaults, and a
    negative limit counts nothing (the client rejects such a Read).
    0 for a file that no longer exists."""
    try:
        lines = Path(path).read_bytes().splitlines(keepends=True)
    except OSError:
        return 0  # read then, gone now: the skill was still used
    start = max(as_int(args.get("offset"), 1) - 1, 0)
    end = start + max(as_int(args.get("limit"), READ_DEFAULT_LIMIT), 0)
    return sum(len(line) for line in lines[start:end])


def as_int(value, default: int) -> int:
    """A logged Read argument as a number, or `default` when it is absent or
    not one (the model can write any value; the client rejects it later)."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON's Infinity
        return default


def read_claude(session: Path) -> Tally:
    t = Tally("claude-code", session=session.stem)
    files = [session, *sorted((session.parent / session.stem / "subagents").glob("*.jsonl"))]
    t.subagents = len(files) - 1
    usage: dict[str, dict] = {}
    reads: list[tuple[Path, int, str, dict]] = []  # (log file, line number, path read, Read arguments)
    bases: dict[str, str] = {}  # skill base directory -> skill name, from the loaded skills
    loads: dict[tuple[Path, str], int] = {}  # (log file, skill name) -> line number of its first load

    for path in files:
        main = path == session
        for line_no, entry in enumerate(read_lines(path)):
            kind = entry.get("type")
            if kind not in ("user", "assistant"):
                continue
            if version := text_or_none(entry.get("version")):
                t.versions.add(version)
            t.time(entry.get("timestamp"))

            if kind == "assistant":
                message = message_of(entry)
                model, msg_id = text_or_none(message.get("model")), text_or_none(message.get("id"))
                synthetic = model == "<synthetic>"  # written by the client, no request made
                if model and not synthetic:
                    t.models.add(model)
                if msg_id and isinstance(message.get("usage"), dict) and message["usage"] and not synthetic:
                    usage[msg_id] = message["usage"]
                for b in blocks(entry):
                    if b.get("type") != "tool_use":
                        continue
                    name, args = text_or_none(b.get("name")) or "?", b.get("input")
                    args = args if isinstance(args, dict) else {}  # a malformed call can log any value
                    t.call(name, args)
                    if main and name == "AskUserQuestion":
                        t.questions += 1
                    if name == "Read" and (file_path := text_or_none(args.get("file_path"))):
                        reads.append((path, line_no, file_path, args))  # attributed once every load is known
                continue

            t.failed += sum(1 for b in blocks(entry) if b.get("type") == "tool_result" and b.get("is_error"))
            text = text_of(entry)
            if entry.get("isMeta") and text.startswith(SKILL_PREAMBLE):
                first = text[len(SKILL_PREAMBLE):].strip().splitlines()
                if not first:
                    continue  # names no directory: nothing to attribute
                base = first[0].strip()
                name = Path(base).name
                t.skills[name] += len(text.encode("utf-8"))
                bases[base] = name
                loads.setdefault((path, name), line_no)
                t.plugin.update(PLUGIN_VERSION.findall(base + "/"))
            elif main and is_typed_prompt(entry):
                t.typed += 1

    for log, line_no, path, args in reads:
        name = skill_of(path, bases)
        if name is None:
            continue  # not a skill's file
        t.plugin.update(PLUGIN_VERSION.findall(path))
        loaded_at = loads.get((log, name))
        if loaded_at is not None and loaded_at < line_no and Path(path).name == "SKILL.md":
            continue  # the text the load already put in this context
        t.skills[name] += read_bytes(path, args)

    t.tokens_in = sum(
        as_int(u.get("input_tokens"), 0) + as_int(u.get("cache_read_input_tokens"), 0)
        + as_int(u.get("cache_creation_input_tokens"), 0)
        for u in usage.values()
    )
    t.tokens_out = sum(as_int(u.get("output_tokens"), 0) for u in usage.values())
    t.requests = len(usage)
    return t


# Codex ---------------------------------------------------------------------


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def codex_logs() -> list[Path]:
    home = codex_home()
    return [*home.glob("sessions/*/*/*/rollout-*.jsonl"), *home.glob("archived_sessions/rollout-*.jsonl")]


def codex_meta(path: Path) -> dict:
    """The `session_meta` payload, which Codex writes as the first line."""
    for line in read_lines(path):
        if line.get("type") == "session_meta":
            return obj(line.get("payload"))
    return {}


def codex_parent(meta: dict) -> str | None:
    """The thread that spawned this one, if it is a subagent."""
    spawn = obj(obj(obj(meta.get("source")).get("subagent")).get("thread_spawn"))
    return text_or_none(meta.get("parent_thread_id")) or text_or_none(spawn.get("parent_thread_id"))


def codex_is_subagent(meta: dict) -> bool:
    source = meta.get("source")
    return bool(
        codex_parent(meta) or meta.get("thread_source") == "subagent"
        or (isinstance(source, dict) and "subagent" in source)
    )


def codex_cwd(path: Path) -> str | None:
    meta = codex_meta(path)
    return None if codex_is_subagent(meta) else text_or_none(meta.get("cwd"))


def codex_subagents(session: Path, root: str | None) -> list[Path]:
    """Every subagent gets its own rollout file. Its `session_id` is the root
    thread's id, and its `parent_thread_id` names the thread that spawned it."""
    if not root:
        return []
    found = set()
    for path in {*session.parent.glob("rollout-*.jsonl"), *codex_logs()}:
        meta = codex_meta(path)
        if path != session and codex_is_subagent(meta) and root in (meta.get("session_id"), codex_parent(meta)):
            found.add(path)
    return sorted(found)


def output_text(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "".join(text for item in output if (text := text_or_none(obj(item).get("text"))))
    return ""


def codex_typed(text: str) -> bool:
    return bool(text.strip()) and not text.lstrip().startswith(CODEX_INJECTED)


def read_codex(session: Path) -> Tally:
    meta = codex_meta(session)
    t = Tally("codex", session=meta.get("id") or session.stem)
    files = [session, *codex_subagents(session, meta.get("id"))]
    t.subagents = len(files) - 1
    records: dict[str, dict] = {}  # one per completed response
    totals: dict[Path, list] = {}  # older logs: the running total, per file
    failed: set[str] = set()

    for path in files:
        main = path == session
        cwd = None
        for line in read_lines(path):
            t.time(line.get("timestamp"))
            kind, p = line.get("type"), obj(line.get("payload"))
            if kind == "session_meta":
                cwd = text_or_none(p.get("cwd"))
                if version := text_or_none(p.get("cli_version")):
                    t.versions.add(version)
            elif kind == "turn_context" and (model := text_or_none(p.get("model"))):
                t.models.add(model)
            elif kind == "token_usage_record":
                records[text_or_none(p.get("response_id")) or f"{path}:{len(records)}"] = obj(p.get("usage"))
            elif kind == "response_item":
                codex_item(t, p, main, failed, cwd)
            elif kind == "event_msg":
                codex_event(t, p, main, failed, totals.setdefault(path, []))

    if records:
        t.tokens_in = sum(as_int(u.get("input_tokens"), 0) for u in records.values())
        t.tokens_out = sum(as_int(u.get("output_tokens"), 0) for u in records.values())
        t.requests = len(records)
    else:
        codex_totals(t, totals)
    t.count_skill_files()
    t.failed = len(failed - {None})
    return t


def codex_item(t: Tally, p: dict, main: bool, failed: set, cwd: str | None) -> None:
    kind = p.get("type")
    if kind == "message" and p.get("role") == "user":
        text = output_text([c for c in p.get("content") or [] if isinstance(c, dict) and c.get("type") == "input_text"])
        if text.lstrip().startswith("<skill>"):
            name = re.search(r"<name>(.*?)</name>", text)
            where = re.search(r"<path>(.*?)</path>", text)
            t.skills[name.group(1) if name else "?"] += len(text.encode("utf-8"))
            t.plugin.update(PLUGIN_VERSION.findall(where.group(1) if where else ""))
            if name and where:
                t.skill_loaded(name.group(1), where.group(1).strip())
    elif kind == "function_call":
        name = (text_or_none(p.get("namespace")) or "") + (text_or_none(p.get("name")) or "?")
        t.call(name, p.get("arguments"))
        if main and name == "request_user_input":
            t.questions += 1
        if name in CODEX_SHELL_TOOLS:
            for found in SKILL_FILE_IN_COMMAND.finditer(str(p.get("arguments"))):
                t.skill_file(found.group(0), cwd)
    elif kind == "custom_tool_call":
        t.call(text_or_none(p.get("name")) or "?", p.get("input"))
    elif kind == "local_shell_call":
        t.call("local_shell", p.get("action"))
        for found in SKILL_FILE_IN_COMMAND.finditer(json.dumps(p.get("action"))):
            t.skill_file(found.group(0), cwd)
    elif kind == "web_search_call":
        t.call("web_search", p.get("action"))
    elif kind in ("function_call_output", "custom_tool_call_output"):
        code = EXIT_CODE.search(output_text(p.get("output")))
        if code and int(code.group(1)) != 0:
            failed.add(text_or_none(p.get("call_id")))


def codex_event(t: Tally, p: dict, main: bool, failed: set, totals: list) -> None:
    kind = p.get("type")
    if kind == "user_message":  # legacy history mode
        if main and codex_typed(str(p.get("message", ""))):
            t.typed += 1
    elif kind == "item_completed":  # paginated history mode
        item = obj(p.get("item"))
        what = item.get("type")
        if what == "UserMessage":
            if main and codex_typed(output_text(item.get("content"))):
                t.typed += 1
        elif what == "McpToolCall" and (
            item.get("status") == "failed" or item.get("error") or obj(item.get("result")).get("isError")
        ):
            failed.add(text_or_none(item.get("id")))
        elif what == "CommandExecution" and (
            item.get("status") in ("failed", "declined") or item.get("exit_code") not in (None, 0)
        ):
            failed.add(text_or_none(item.get("id")))
    elif kind == "mcp_tool_call_end":  # legacy history mode
        result = obj(p.get("result"))
        if "Err" in result or obj(result.get("Ok")).get("isError"):
            failed.add(text_or_none(p.get("call_id")))
    elif kind == "token_count":
        if usage := obj(obj(p.get("info")).get("total_token_usage")):
            totals.append(usage)


def codex_totals(t: Tally, totals: dict) -> None:
    """Logs written before `token_usage_record` existed. `token_count` carries
    a running total and is re-sent unchanged with rate-limit updates, so a
    request is a change in that total. An entry with only `total_tokens` set is
    a local estimate, not a response, and is skipped."""
    tokens_in = tokens_out = requests = 0
    found = False
    for seq in totals.values():
        last = None
        for usage in seq:
            point = tuple(as_int(usage.get(k), 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
            if point[0] or point[2]:
                requests += point != last
                last = point
        if last:
            found = True
            tokens_in += last[0]
            tokens_out += last[2]
    if found:
        t.tokens_in, t.tokens_out, t.requests = tokens_in, tokens_out, requests


# Copilot CLI ---------------------------------------------------------------


def copilot_home() -> Path:
    return Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))


def copilot_logs() -> list[Path]:
    return list(copilot_home().glob("session-state/*/events.jsonl"))


def copilot_cwd(path: Path) -> str | None:
    """`session.start` records the working directory, and `workspace.yaml`
    beside the log repeats it for sessions whose start event lacks it."""
    for event in read_lines(path):
        if event.get("type") in ("session.start", "session.resume"):
            if cwd := text_or_none(obj(obj(event.get("data")).get("context")).get("cwd")):
                return cwd
    try:
        for line in (path.parent / "workspace.yaml").read_text(encoding="utf-8").splitlines():
            if line.startswith("cwd:"):
                return line[4:].strip().strip("'\"")
    except OSError:
        pass
    return None


def read_copilot(session: Path) -> Tally:
    t = Tally("copilot", session=session.parent.name)
    failed: set[str] = set()
    fallback_models: set[str] = set()
    shutdown = None
    turns = 0

    for event in read_lines(session):
        t.time(event.get("timestamp"))
        kind, d = event.get("type"), obj(event.get("data"))
        # Subagent events sit in the same file, marked with the agent's id.
        sub = event.get("agentId") not in (None, "", "main") or bool(d.get("parentToolCallId"))
        model = text_or_none(d.get("model"))
        if model and kind in ("assistant.message", "assistant.turn_start", "tool.execution_start"):
            t.models.add(model)

        if kind in ("session.start", "session.resume"):
            if version := text_or_none(d.get("copilotVersion")):
                t.versions.add(version)
            if selected := text_or_none(d.get("selectedModel")):
                fallback_models.add(selected)
        elif kind == "session.model_change" and (changed := text_or_none(d.get("newModel"))):
            fallback_models.add(changed)
        elif kind == "assistant.turn_start":
            turns += 1
        elif kind == "tool.execution_start":
            name = text_or_none(d.get("toolName")) or "?"
            server, tool = text_or_none(d.get("mcpServerName")), text_or_none(d.get("mcpToolName"))
            if server and tool:
                name = f"mcp__{server}__{tool}"
            args = d.get("arguments") or {}
            t.call(name, args)
            if not sub and name == "ask_user":
                t.questions += 1
            if name == "view" and (path := text_or_none(obj(args).get("path"))):
                t.skill_file(path)
        elif kind == "tool.execution_complete" and d.get("success") is False:
            failed.add(text_or_none(d.get("toolCallId")))
        elif kind == "user.message":
            if not sub and d.get("source") in (None, "user") and not d.get("isAutopilotContinuation"):
                t.typed += 1
        elif kind == "skill.invoked":
            skill = text_or_none(d.get("name")) or "?"
            t.skills[skill] += len(str(d.get("content", "")).encode("utf-8"))
            t.skill_loaded(skill, text_or_none(d.get("path")))
            t.plugin.update(PLUGIN_VERSION.findall(str(d.get("path", ""))))
            version = text_or_none(d.get("pluginVersion"))
            if d.get("pluginName") in ("diagrid", "catalyst-ai") and version:
                t.plugin.add(version)
        elif kind == "subagent.started":
            t.subagents += 1
        elif kind == "session.shutdown":
            shutdown = d  # a resumed session appends another, with running totals

    t.count_skill_files()
    t.failed = len(failed - {None})
    t.requests = turns
    if shutdown is not None:
        metrics = {k: v for k, v in obj(shutdown.get("modelMetrics")).items() if isinstance(v, dict)}
        t.models.update(metrics)
        t.tokens_in = sum(as_int(obj(m.get("usage")).get("inputTokens"), 0) for m in metrics.values())
        t.tokens_out = sum(as_int(obj(m.get("usage")).get("outputTokens"), 0) for m in metrics.values())
        counts = [obj(m.get("requests")).get("count") for m in metrics.values()]
        if counts and all(isinstance(c, int) for c in counts):
            t.requests = sum(counts)
    if not t.models:
        t.models = fallback_models
    return t


# Shared --------------------------------------------------------------------

# client: (reader, every main session log, the cwd a log records, its session id)
CLIENTS = {
    "claude": (read_claude, claude_logs, claude_cwd, lambda path: path.stem),
    "codex": (read_codex, codex_logs, codex_cwd, lambda path: path.stem),
    "copilot": (read_copilot, copilot_logs, copilot_cwd, lambda path: path.parent.name),
}


def here(cwd: Path | None = None) -> set[str]:
    """The ways this directory can be written in a log: its resolved path, and
    `$PWD` when that is a symlinked path to the same place."""
    if cwd is not None:
        return {str(cwd), str(Path(cwd).resolve())}
    real = Path.cwd().resolve()
    places = {str(real)}
    pwd = os.environ.get("PWD")
    if pwd and Path(pwd).resolve() == real:
        places.add(pwd)
    return places


def find_session(args: argparse.Namespace, cwd: Path | None = None) -> Path:
    if args.path:
        return Path(args.path)
    client = args.client
    _, logs, recorded_cwd, log_id = CLIENTS[client]
    if args.session:
        # A Codex file name ends in the thread id, so a substring match finds it.
        matches = sorted(
            p for p in logs() if log_id(p) == args.session or (client == "codex" and args.session in p.stem)
        )
        if not matches:
            sys.exit(f"no {client} session {args.session}")
        return matches[0]

    places = here(cwd)
    if client == "claude":  # the fast path: the folder named after this directory
        sessions = [p for place in places for p in project_dir_for(Path(place)).glob("*.jsonl")]
        if sessions:
            return max(sessions, key=lambda p: p.stat().st_mtime)
    for path in sorted(logs(), key=lambda p: p.stat().st_mtime, reverse=True):
        recorded = recorded_cwd(path)
        if recorded and (recorded in places or str(Path(recorded).resolve()) in places):
            return path
    sys.exit(f"no {client} session recorded for {' or '.join(sorted(places))}")


def summarize(t: Tally) -> dict:
    tools = Counter(name for name, _ in t.calls)
    repeated = len(t.calls) - len(set(t.calls))  # each call after the first with the same tool and arguments
    ours = {n: c for n, c in tools.items() if PLUGIN_TOOL.search(n)}
    metrics = {
        "session": t.session,
        "subagents": t.subagents,
        "client": f"{t.client} {','.join(sorted(t.versions))}".rstrip(),
        "model": ",".join(sorted(t.models)) or None,
        "plugin": ",".join(sorted(t.plugin)) or None,
        "tokens_in": t.tokens_in,
        "tokens_out": t.tokens_out,
        "model_requests": t.requests,
        "tool_calls": len(t.calls),
        "diagrid_calls": sum(ours.values()),
        "failed_calls": t.failed,
        "repeated_calls": repeated,
        "user_turns": max(t.typed - 1, 0) + t.questions,
        "skill_bytes": sum(t.skills.values()),
        "wall_seconds": int((max(t.times) - min(t.times)).total_seconds()) if t.times else None,
        "tools": dict(tools.most_common()),
        "diagrid_tools": ours,
        "skills": dict(t.skills),
    }
    metrics["unavailable"] = [k for k in MAYBE_UNAVAILABLE if metrics[k] is None]
    return metrics


def measure(session: Path, client: str = "claude") -> dict:
    return summarize(CLIENTS[client][0](session))


def row(m: dict) -> str:
    def cell(value, fmt=str) -> str:
        return "-" if value is None else fmt(value)

    skills = ", ".join(sorted(m["skills"])) or "none"
    wall = "-" if m["wall_seconds"] is None else "{}m {:02d}s".format(*divmod(m["wall_seconds"], 60))
    cells = [
        m["client"], cell(m["model"]), cell(m["plugin"]), cell(m["tokens_in"], "{:,}".format),
        cell(m["tokens_out"], "{:,}".format), cell(m["model_requests"]),
        f"{m['tool_calls']} / {m['diagrid_calls']} / {m['failed_calls']} / {m['repeated_calls']}",
        str(m["user_turns"]), f"{skills} ({m['skill_bytes']:,})", wall,
    ]
    return "| " + " | ".join(cells) + " |"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument("path", nargs="?", help="a session log file")
    pick.add_argument("--latest", action="store_true", help="the newest session for the current directory")
    pick.add_argument("--session", help="a session id")
    parser.add_argument("--client", choices=sorted(CLIENTS), default="claude", help="which client wrote the log")
    parser.add_argument("--json", action="store_true", help="print the full breakdown as JSON")
    args = parser.parse_args(argv)

    session = find_session(args)
    age = time.time() - session.stat().st_mtime
    if age < STILL_RUNNING_SECONDS:
        print(f"warning: {session} was written {int(age)}s ago; the session may still be running, "
              "so these numbers may not be final", file=sys.stderr)
    metrics = measure(session, args.client)
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(HEADER)
        print(DIVIDER)
        print(row(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
