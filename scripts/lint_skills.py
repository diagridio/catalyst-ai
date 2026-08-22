#!/usr/bin/env python3
"""Lint the skills in this repo.

Every rule here exists because something got past `claude plugin validate
--strict`. That command is not a gate: probed against deliberately broken
fixtures on claude 2.1.239 it accepts a `name` that disagrees with its
directory, a 1500-character description, unknown frontmatter keys including
`allowed-tools` and `model`, `../` links, and — worst — frontmatter that is not
valid YAML at all. It warns only on a *missing* description. From the repo root
it validates `marketplace.json` and never opens a SKILL.md.

So this file is the actual contract. Run it in CI and locally; a green
`validate --strict` means nothing on its own.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# Codex caps the skill list at roughly 8000 characters and, when it overflows,
# SHORTENS DESCRIPTIONS FIRST — and a shortened description is exactly what
# breaks implicit triggering. So the per-skill cap is not a style rule, it is
# what keeps the whole set inside a budget that degrades silently.
MAX_DESCRIPTION_CHARS = 260

# A hard ceiling on skills, for the same reason. `claude plugin details` reports
# roughly 100 always-on tokens per skill, so this is also a context budget.
MAX_SKILLS = 12

# Total description budget, well inside Codex's cap so we notice before it bites.
MAX_TOTAL_DESCRIPTION_CHARS = 5000

# Frontmatter is an allow-list, not a suggestion. `allowed-tools` and `model` are
# Claude-Code-only and this repo installs into Codex and Copilot too; a skill
# that silently loses its tool restriction on another client is worse than one
# that never claimed to have it. CAT-1730 originally required `mcp_tools:` and
# `cli_fallback:` here — dropped 2026-08-22, expressed in prose instead.
ALLOWED_FRONTMATTER_KEYS = {"name", "description"}

# Things that must never appear in a skill, each because it shipped somewhere and
# broke. The value is why, so a failure explains itself.
BANNED_SUBSTRINGS: dict[str, str] = {
    "--enable-agent-infrastructure": (
        "removed from `diagrid project create` in CLI v1.63.0 (verified by "
        "downloading the binary). Agent infrastructure now comes with the "
        "managed KV store. This flag shipped in 7 places in typescript-ai, "
        "including executable code that printed it to users as setup guidance."
    ),
    "Diagrid.Agents.Workflow": (
        "NuGet package that does not exist and returns 404. The published id is "
        "`Diagrid.AI.Microsoft.AgentFramework`. A skill that emits a coordinate "
        "which does not resolve is worse than no skill."
    ),
    "diagrid-ai": (
        "not the PyPI distribution name. It is `diagrid` (0.4.3), with framework "
        "extras rather than per-framework distributions."
    ),
    "go-sdk/workflow": (
        "does not exist in any released tag. Go's workflow API is "
        "`github.com/dapr/durabletask-go/workflow`."
    ),
}


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def split_frontmatter(text: str, path: Path, f: Findings) -> dict | None:
    """Return parsed frontmatter, or None having recorded why not.

    Parsed with a real YAML loader rather than a regex on purpose. A `": "`
    inside a plain scalar makes the block invalid ("mapping values are not
    allowed here"), `validate --strict` passes it, and the skill then fails only
    when a client tries to load it. A regex reading `description:` would not
    notice either.
    """
    if not text.startswith("---\n"):
        f.error(str(path.relative_to(REPO)), "no YAML frontmatter block at the top of the file")
        return None
    end = text.find("\n---", 3)
    if end == -1:
        f.error(str(path.relative_to(REPO)), "frontmatter block is never closed with `---`")
        return None
    raw = text[4:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0]
        f.error(
            str(path.relative_to(REPO)),
            f"frontmatter is not valid YAML ({detail}). A colon followed by a "
            f"space inside an unquoted value is the usual cause — quote the "
            f"value or rephrase it.",
        )
        return None
    if not isinstance(data, dict):
        f.error(str(path.relative_to(REPO)), "frontmatter is not a mapping")
        return None
    return data



def allows_banned(text: str, banned: str) -> bool:
    """Whether the file explicitly acknowledges a banned string.

    Teaching "`X` does not exist, never write it" is exactly the content we
    want, and a substring check cannot tell it from an instruction to use `X` —
    the good skill and the bad skill contain the same characters. This gate
    caught three such counter-examples on its first real run and was wrong all
    three times.

    An explicit marker rather than looking for a nearby negation: a heuristic is
    satisfied by accident. "This is not optional: use `X`" reads as negated and
    is precisely the defect. A marker cannot be tripped by prose.
    """
    return f"lint-allow-banned: {banned}" in text


def check_skill(skill_dir: Path, f: Findings) -> str | None:
    """Check one skill. Returns its description for the whole-set budget."""
    rel = str(skill_dir.relative_to(REPO))
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        f.error(rel, "no SKILL.md")
        return None

    text = md.read_text(encoding="utf-8")
    data = split_frontmatter(text, md, f)
    if data is None:
        return None

    where = str(md.relative_to(REPO))

    unknown = sorted(set(data) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        f.error(
            where,
            f"frontmatter keys not allowed: {', '.join(unknown)}. Allowed: "
            f"{', '.join(sorted(ALLOWED_FRONTMATTER_KEYS))}. `allowed-tools` and "
            f"`model` are Claude-Code-only and this repo installs into Codex and "
            f"Copilot too — express the restriction in prose instead.",
        )

    name = data.get("name")
    if not name:
        f.error(where, "frontmatter has no `name`")
    elif name != skill_dir.name:
        f.error(where, f"`name: {name}` disagrees with its directory `{skill_dir.name}`")

    description = data.get("description")
    if not description:
        f.error(where, "frontmatter has no `description` — without one the skill never triggers")
        return None
    if not isinstance(description, str):
        f.error(where, f"`description` is {type(description).__name__}, not a string")
        return None

    n = len(description)
    if n > MAX_DESCRIPTION_CHARS:
        f.error(
            where,
            f"description is {n} characters, over the {MAX_DESCRIPTION_CHARS} cap "
            f"by {n - MAX_DESCRIPTION_CHARS}. Codex shortens descriptions first "
            f"when its ~8000-char list overflows, and a shortened description is "
            f"what breaks implicit triggering.",
        )

    # `../` cannot resolve once a skill is installed on its own: `npx skills`
    # copies the skill directory alone, so a sibling reference dangles. This is
    # the rule whose absence produced 124 dangling links upstream.
    for m in re.finditer(r"\]\(([^)]+)\)", text):
        target = m.group(1)
        if target.startswith("../"):
            f.error(where, f"link `{target}` escapes the skill directory with `../`")
        elif not target.startswith(("http://", "https://", "#", "mailto:")):
            local = (skill_dir / target.split("#")[0]).resolve()
            if not local.exists():
                f.error(where, f"link `{target}` does not resolve to a file in this skill")

    for banned, why in BANNED_SUBSTRINGS.items():
        if banned in text and not allows_banned(text, banned):
            f.error(
                where,
                f"contains `{banned}` — {why}\n     If this is a deliberate "
                f"counter-example, acknowledge it with a line reading:\n     "
                f"<!-- lint-allow-banned: {banned} — why this is safe here -->",
            )

    return description


def check_isolation(skill_dirs: list[Path], f: Findings) -> None:
    """Copy each skill alone to a temp dir and assert every reference resolves.

    This is the gate whose absence caused the upstream breakage: installed one at
    a time, a skill that leans on a sibling directory has nothing to lean on.
    """
    for skill_dir in skill_dirs:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / skill_dir.name
            shutil.copytree(skill_dir, dest)
            for md in dest.rglob("*.md"):
                text = md.read_text(encoding="utf-8")
                for m in re.finditer(r"\]\(([^)]+)\)", text):
                    target = m.group(1)
                    if target.startswith(("http://", "https://", "#", "mailto:")):
                        continue
                    if not (md.parent / target.split("#")[0]).resolve().exists():
                        f.error(
                            str(skill_dir.relative_to(REPO)),
                            f"installed alone, `{target}` in {md.name} does not resolve",
                        )


def check_plugin_validate(f: Findings) -> None:
    """Run `claude plugin validate` as a weak extra signal, never as the gate.

    Recorded as a note rather than an error when it is unavailable: CI should not
    fail because a runner has no `claude` binary, and a pass here proves almost
    nothing anyway.
    """
    if shutil.which("claude") is None:
        f.note("`claude` not on PATH — skipped `plugin validate` (it is not the gate)")
        return
    for target in (".", "./skills"):
        proc = subprocess.run(
            ["claude", "plugin", "validate", target, "--strict"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            f.error(f"claude plugin validate {target}", proc.stdout.strip() or proc.stderr.strip())


def main() -> int:
    f = Findings()

    if not SKILLS_DIR.is_dir():
        print("no skills/ directory", file=sys.stderr)
        return 1

    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not skill_dirs:
        print("skills/ contains no skills", file=sys.stderr)
        return 1

    if len(skill_dirs) > MAX_SKILLS:
        f.error(
            "skills/",
            f"{len(skill_dirs)} skills, over the {MAX_SKILLS} cap. Each costs "
            f"roughly 100 always-on tokens in every session and competes for "
            f"triggers with its siblings.",
        )

    descriptions: dict[str, str] = {}
    for skill_dir in skill_dirs:
        desc = check_skill(skill_dir, f)
        if desc:
            descriptions[skill_dir.name] = desc

    check_isolation(skill_dirs, f)
    check_plugin_validate(f)

    total = sum(len(d) for d in descriptions.values())
    if total > MAX_TOTAL_DESCRIPTION_CHARS:
        f.error(
            "skills/",
            f"descriptions total {total} characters, over the "
            f"{MAX_TOTAL_DESCRIPTION_CHARS} budget. Codex caps its skill list at "
            f"~8000 and truncates before it warns.",
        )

    print(f"{len(skill_dirs)} skills, {total} characters of description\n")
    for name in sorted(descriptions):
        print(f"  {len(descriptions[name]):>4}  {name}")
    print()

    for note in f.notes:
        print(f"note: {note}")

    if f.errors:
        print(f"\n{len(f.errors)} problem(s):\n", file=sys.stderr)
        for err in f.errors:
            print(f"  ✗ {err}\n", file=sys.stderr)
        return 1

    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
