#!/usr/bin/env python3
"""Prove check_coordinates.py catches each failure it claims to, with no network.

The registry lookups are replaced by a table, so every case is deterministic and
the suite runs in CI without reaching PyPI, npm, NuGet, Maven or the Go proxy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_coordinates import (  # noqa: E402
    Entry,
    Lookup,
    RegistryUnreachable,
    agreement_problems,
    parse_manifest,
    registry_problems,
    scan_skills,
)


def fake_registry(table: dict[str, Lookup | Exception]):
    def lookup(entry: Entry) -> Lookup:
        result = table.get(entry.coordinate, Lookup(False))
        if isinstance(result, Exception):
            raise result
        return result

    return lookup


class ParseManifest(unittest.TestCase):
    def test_reads_entries_and_ignores_comments(self) -> None:
        entries = parse_manifest("# header\n\nnpm @diagrid/agent-mastra 0.2.0  # quoted\ngo github.com/x/y -\n")
        self.assertEqual(entries, [Entry("npm", "@diagrid/agent-mastra", "0.2.0"), Entry("go", "github.com/x/y", "-")])

    def test_rejects_an_unknown_ecosystem(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown ecosystem"):
            parse_manifest("cargo serde -\n")

    def test_rejects_a_duplicate(self) -> None:
        with self.assertRaisesRegex(ValueError, "listed twice"):
            parse_manifest("npm @dapr/dapr -\nnpm @dapr/dapr -\n")

    def test_rejects_a_short_line(self) -> None:
        with self.assertRaisesRegex(ValueError, "want <ecosystem>"):
            parse_manifest("npm @dapr/dapr\n")


class Scan(unittest.TestCase):
    def test_finds_coordinates_in_inline_code(self) -> None:
        found = scan_skills(["Install `@diagrid/agent-mastra` and `io.diagrid:diagrid-spring-ai-starter`."])
        self.assertEqual(found, {("npm", "@diagrid/agent-mastra"), ("maven", "io.diagrid:diagrid-spring-ai-starter")})

    def test_ignores_fenced_blocks(self) -> None:
        text = "```csharp\n`Dapr.Actors`\nusing Dapr.Actors;\n```\nsee `Dapr.Workflow`"
        self.assertEqual(scan_skills([text]), {("nuget", "Dapr.Workflow")})

    def test_reads_the_pypi_distribution_from_extras(self) -> None:
        self.assertEqual(scan_skills(['`pip install "diagrid[langgraph]"`']), {("pypi", "diagrid")})


class Agreement(unittest.TestCase):
    def test_passes_when_list_and_skills_agree(self) -> None:
        entries = [Entry("npm", "@diagrid/agent-mastra", "0.2.0"), Entry("go", "github.com/dapr/go-sdk", "-")]
        texts = ["| `@diagrid/agent-mastra` on npm, 0.2.0 |\nimport `github.com/dapr/go-sdk/client`"]
        self.assertEqual(agreement_problems(entries, texts), [])

    def test_flags_a_coordinate_a_skill_names_but_the_list_lacks(self) -> None:
        problems = agreement_problems([], ["use `@diagrid/agent-core`"])
        self.assertEqual(len(problems), 1)
        self.assertIn("does not — add it", problems[0])

    def test_flags_a_listed_coordinate_no_skill_mentions(self) -> None:
        problems = agreement_problems([Entry("npm", "@diagrid/gone", "-")], ["nothing here"])
        self.assertIn("no skill mentions it", problems[0])

    def test_flags_a_quoted_version_the_skills_do_not_carry(self) -> None:
        problems = agreement_problems([Entry("npm", "@diagrid/agent-mastra", "0.2.0")], ["`@diagrid/agent-mastra` on npm, 0.1.0"])
        self.assertIn("no skill line quotes that version", problems[0])

    def test_a_go_import_path_is_covered_by_its_module(self) -> None:
        entries = [Entry("go", "github.com/dapr/durabletask-go", "-")]
        self.assertEqual(agreement_problems(entries, ["`github.com/dapr/durabletask-go/workflow`"]), [])


class Registry(unittest.TestCase):
    def test_passes_a_published_coordinate_at_its_quoted_version(self) -> None:
        lookup = fake_registry({"diagrid": Lookup(True, frozenset({"0.5.0"}), "0.5.0")})
        self.assertEqual(registry_problems([Entry("pypi", "diagrid", "0.5.0")], lookup, strict_versions=True), [])

    def test_fails_a_coordinate_that_does_not_resolve(self) -> None:
        problems = registry_problems([Entry("npm", "@diagrid/typo", "-")], fake_registry({}), strict_versions=False)
        self.assertIn("does not resolve", problems[0])

    def test_fails_a_quoted_version_the_registry_does_not_have(self) -> None:
        lookup = fake_registry({"diagrid": Lookup(True, frozenset({"0.5.0"}), "0.5.0")})
        problems = registry_problems([Entry("pypi", "diagrid", "0.9.9")], lookup, strict_versions=False)
        self.assertIn("does not have", problems[0])

    def test_a_newer_release_fails_only_in_strict_mode(self) -> None:
        lookup = fake_registry({"diagrid": Lookup(True, frozenset({"0.4.3", "0.5.0"}), "0.5.0")})
        entry = [Entry("pypi", "diagrid", "0.4.3")]
        self.assertEqual(registry_problems(entry, lookup, strict_versions=False), [])
        self.assertIn("0.5.0 is out", registry_problems(entry, lookup, strict_versions=True)[0])

    def test_an_absent_coordinate_passes_while_it_stays_absent(self) -> None:
        entry = [Entry("nuget", "Diagrid.Agents.Workflow", "absent")]
        self.assertEqual(registry_problems(entry, fake_registry({}), strict_versions=True), [])

    def test_an_absent_coordinate_fails_once_it_resolves(self) -> None:
        lookup = fake_registry({"Diagrid.Agents.Workflow": Lookup(True, frozenset({"1.0.0"}), "1.0.0")})
        problems = registry_problems([Entry("nuget", "Diagrid.Agents.Workflow", "absent")], lookup, strict_versions=False)
        self.assertIn("now resolves", problems[0])

    def test_an_unreachable_registry_is_reported_not_passed(self) -> None:
        lookup = fake_registry({"@dapr/dapr": RegistryUnreachable("timed out")})
        problems = registry_problems([Entry("npm", "@dapr/dapr", "-")], lookup, strict_versions=False)
        self.assertIn("unreachable", problems[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
