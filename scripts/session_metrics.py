#!/usr/bin/env python3
"""Measure one finished Claude Code session.

Wall-clock minutes are a poor measure of a skill: they depend on the task, the
network and whether anyone is watching. So a run is described by what the
coding agent actually spent, read back from the session log Claude Code already
writes. Nothing runs during the session and nothing ships in the plugin: this
reads a finished log and prints one Markdown table row.

    python3 scripts/session_metrics.py --latest          # newest session for this directory
    python3 scripts/session_metrics.py --session <id>    # one session by id
    python3 scripts/session_metrics.py path/to/session.jsonl
    python3 scripts/session_metrics.py --latest --json   # full breakdown, per tool and per skill

What it counts, and the shape of the log that decides how:

- Tokens and model requests. One model response is written as several
  `assistant` lines, one per content block, each repeating the same
  `message.id` and `usage`. Counting lines would multiply every number, so
  usage is taken once per id. Input is everything the model read: fresh input
  plus cache reads plus cache writes, which is what the other clients report as
  input too.
- Tool calls, from `tool_use` blocks on `assistant` lines only. The
  `api-request-blob` lines replay earlier calls as request history, so reading
  them would count a call once per later request. Catalyst calls are matched on
  both tool name sets, `catalyst_*` and `diagrid_*`, because the tools are being
  renamed. A call is repeated when the same tool got the same arguments earlier
  in the session, and failed when its result has `is_error`.
- User turns, from the main log only: typed prompts after the first, plus
  `AskUserQuestion` calls. Each is a wait on the person.
- Skill text, from the hidden message that carries a loaded skill (it starts
  with "Base directory for this skill:") plus `Read` calls on files under a
  `skills/` directory. Bytes, not tokens: the tokenizer differs by model.
- Subagent work lives in `<session>/subagents/*.jsonl` and is added to every
  count except user turns, because a skill that spawns a subagent still spent it.

It prints counts, names and sizes only, never prompts, arguments or results,
because a session log can hold connection values. Codex and Copilot keep their
own logs in other shapes; readers for them come once there is a real file from
each to test against.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SKILL_PREAMBLE = "Base directory for this skill:"
CATALYST_TOOL = re.compile(r"(?:^|__)(?:catalyst|diagrid)_[a-z0-9_]+$")
PLUGIN_VERSION = re.compile(r"/catalyst-ai/(\d+\.\d+\.\d+[^/]*)/skills/")
SKILL_PATH = re.compile(r"/skills/([^/]+)/")
NOT_TYPED = (
    "<system-reminder>", "<task-notification>", "<local-command-", "<bash-stdout>", "<bash-stderr>",
    "[Request interrupted",
)

COLUMNS = [
    "client", "model", "plugin", "tokens in", "tokens out", "model requests",
    "tool calls (all / catalyst / failed / repeated)", "user turns", "skills (bytes)", "wall time",
]
HEADER = "| " + " | ".join(COLUMNS) + " |"
DIVIDER = "|" + "---|" * len(COLUMNS)


def projects_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"


def project_dir_for(cwd: Path) -> Path:
    """Claude Code files a session under its working directory, with every
    character that is not a letter or digit replaced by `-`."""
    return projects_dir() / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def find_session(args: argparse.Namespace, cwd: Path | None = None) -> Path:
    if args.path:
        return Path(args.path)
    if args.session:
        matches = sorted(projects_dir().glob(f"*/{args.session}.jsonl"))
        if not matches:
            sys.exit(f"no session {args.session} under {projects_dir()}")
        return matches[0]
    folder = project_dir_for(cwd or Path.cwd())
    sessions = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        sys.exit(f"no Claude Code sessions for this directory in {folder}")
    return sessions[-1]


def read_lines(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # a session still being written can end mid-line


def blocks(entry: dict) -> list:
    content = (entry.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def text_of(entry: dict) -> str:
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in blocks(entry) if b.get("type") == "text")


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


def measure(session: Path) -> dict:
    files = [session, *sorted((session.parent / session.stem / "subagents").glob("*.jsonl"))]
    usage: dict[str, dict] = {}
    tools: Counter = Counter()
    seen_calls: set[str] = set()
    repeated = failed = typed = questions = 0
    skills: Counter = Counter()
    versions: set[str] = set()
    models: set[str] = set()
    plugin: set[str] = set()
    times: list[datetime] = []

    for path in files:
        main = path == session
        for entry in read_lines(path):
            kind = entry.get("type")
            if kind not in ("user", "assistant"):
                continue
            if entry.get("version"):
                versions.add(entry["version"])
            if entry.get("timestamp"):
                times.append(datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")))

            if kind == "assistant":
                message = entry.get("message") or {}
                synthetic = message.get("model") == "<synthetic>"  # written by the client, no request made
                if message.get("model") and not synthetic:
                    models.add(message["model"])
                if message.get("id") and message.get("usage") and not synthetic:
                    usage[message["id"]] = message["usage"]
                for b in blocks(entry):
                    if b.get("type") != "tool_use":
                        continue
                    name, args = b.get("name", "?"), b.get("input") or {}
                    tools[name] += 1
                    if main and name == "AskUserQuestion":
                        questions += 1
                    call = name + json.dumps(args, sort_keys=True)
                    if call in seen_calls:
                        repeated += 1
                    seen_calls.add(call)
                    if name == "Read" and (found := SKILL_PATH.search(str(args.get("file_path", "")))):
                        try:
                            size = Path(args["file_path"]).stat().st_size
                        except OSError:
                            size = 0
                        skills[found.group(1)] += size
                continue

            failed += sum(1 for b in blocks(entry) if b.get("type") == "tool_result" and b.get("is_error"))
            text = text_of(entry)
            if entry.get("isMeta") and text.startswith(SKILL_PREAMBLE):
                base = text[len(SKILL_PREAMBLE):].splitlines()[0].strip()
                name = Path(base).name
                skills[name] += len(text.encode("utf-8"))
                plugin.update(PLUGIN_VERSION.findall(base + "/"))
            elif main and is_typed_prompt(entry):
                typed += 1

    tokens_in = sum(
        u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        for u in usage.values()
    )
    catalyst = {n: c for n, c in tools.items() if CATALYST_TOOL.search(n)}
    return {
        "session": session.stem,
        "subagent_files": len(files) - 1,
        "client": f"claude-code {','.join(sorted(versions))}".rstrip(),
        "model": ",".join(sorted(models)) or "-",
        "plugin": ",".join(sorted(plugin)) or "-",
        "tokens_in": tokens_in,
        "tokens_out": sum(u.get("output_tokens", 0) for u in usage.values()),
        "model_requests": len(usage),
        "tool_calls": sum(tools.values()),
        "catalyst_calls": sum(catalyst.values()),
        "failed_calls": failed,
        "repeated_calls": repeated,
        "user_turns": max(typed - 1, 0) + questions,
        "skill_bytes": sum(skills.values()),
        "wall_seconds": int((max(times) - min(times)).total_seconds()) if times else 0,
        "tools": dict(tools.most_common()),
        "catalyst_tools": catalyst,
        "skills": dict(skills),
    }


def row(m: dict) -> str:
    skills = ", ".join(sorted(m["skills"])) or "none"
    minutes, seconds = divmod(m["wall_seconds"], 60)
    cells = [
        m["client"], m["model"], m["plugin"], f"{m['tokens_in']:,}", f"{m['tokens_out']:,}",
        str(m["model_requests"]),
        f"{m['tool_calls']} / {m['catalyst_calls']} / {m['failed_calls']} / {m['repeated_calls']}",
        str(m["user_turns"]), f"{skills} ({m['skill_bytes']:,})", f"{minutes}m {seconds:02d}s",
    ]
    return "| " + " | ".join(cells) + " |"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument("path", nargs="?", help="a session .jsonl file")
    pick.add_argument("--latest", action="store_true", help="the newest session for the current directory")
    pick.add_argument("--session", help="a session id")
    parser.add_argument("--json", action="store_true", help="print the full breakdown as JSON")
    args = parser.parse_args(argv)

    metrics = measure(find_session(args))
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(HEADER)
        print(DIVIDER)
        print(row(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
