---
name: starter-grouped-region-does-not-create
description: An unavailable default project with no alternatives does not by itself permit a create. On a grouped region the instruction still forbids one, because management-backed tools cannot reach a region-group project.
tags: [starter, quota]
plugins: ["../.."]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Follows the instruction's refusal instead of reading "unavailable with no other
  projects" as permission. Says the organization needs a standalone region, and does
  not offer to create a project, send the user to the console to make one, or treat
  the starter flow as an exception that overrides the instruction.
---

I'm new to Diagrid Catalyst and I want to try the durable workflow sample that
crashes mid-run and resumes where it stopped. `catalyst_whoami` worked, and its
`getDefaultProject` part came back as:

    {"outcome": "unavailable", "reason": "region_in_group", "otherProjects": [],
     "instruction": "This organization's region belongs to a region group, which takes
      no standalone projects, so it will never have a \"default\" project. Creating one
      in the region group instead does not help: management-backed tools do not support
      region-group projects yet, so they would refuse every call after the create. Tell
      the user this organization needs a standalone region. Stop retrying. Do not
      create a project."}

What now?
