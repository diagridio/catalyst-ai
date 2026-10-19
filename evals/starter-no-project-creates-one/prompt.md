---
name: starter-no-project-creates-one
description: On an unavailable default project with no alternatives, the try flows may create one. A bare project has no managed infrastructure, and the workflow store cannot be added to a sidecar that has already booted.
tags: [starter, quota]
plugins: ["../.."]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Reads the outcome as permanent, offers to create a project rather than dead-ending,
  and says its `spec` must enable the managed pub/sub, KV store and workflow store.
  Says a new project spends one of the few slots the plan allows, and asks before
  creating anything rather than reporting it done.
---

I'm new to Diagrid Catalyst and I want to try the durable workflow sample that
crashes mid-run and resumes where it stopped. `catalyst_whoami` worked, and its
`getDefaultProject` part came back as:

    {"outcome": "unavailable", "reason": "default_deleted", "otherProjects": [],
     "instruction": "This organization's \"default\" project was deleted, and it is
      never recreated. Stop retrying. This organization has no other project either,
      so ask the user to create one and to tell you its name. Do not create a project."}

What now?
