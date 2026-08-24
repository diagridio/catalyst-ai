#!/usr/bin/env python3
"""The one place that decides what counts as a link in a skill.

Two gates resolve links and they have to agree. scripts/lint_skills.py resolves
them in the repo and again in a `copytree` of each skill on its own;
scripts/check_install.py resolves them in what `npx skills` actually installs,
which is not a flat copy. Two regexes drift, and the drift is silent — a gate
whose extractor stops matching reports no findings, which reads exactly like a
clean tree.

The rule is narrow on purpose: only `](...)`. An inline code span that looks
like a path is prose, not a link. `skills/catalyst-workflow-from-diagram/
reference/bpmn-to-ir.md` names `prompts/ir-schema.md`, `prompts/bpmn-to-ir.md`
and `REFERENCE.md` in a sentence crediting the upstream dapr-skills repo; none
of those files are in this repo and none of them should be. A hand-rolled
checker that scanned code spans flagged all three as dangling, and a gate that
cries wolf gets switched off — which is worse than no gate at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# A markdown inline link target. Deliberately not code spans, not
# reference-style definitions, not bare URLs — see the module docstring.
_LINK = re.compile(r"\]\(([^)]+)\)")

# Prefixes that mean "not a path on this disk", so there is nothing to resolve.
EXTERNAL_PREFIXES = ("http://", "https://", "#", "mailto:")


def local_link_targets(text: str) -> Iterator[str]:
    """Every markdown link target in `text` that has to resolve to a real file."""
    for match in _LINK.finditer(text):
        target = match.group(1)
        if not target.startswith(EXTERNAL_PREFIXES):
            yield target


def link_path(target: str) -> str:
    """The file part of a link target, with any `#fragment` dropped."""
    return target.split("#", 1)[0]
