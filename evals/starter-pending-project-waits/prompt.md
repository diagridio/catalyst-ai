---
name: starter-pending-project-waits
description: A pending default project is seconds from existing, and asking is what triggers it. Reading pending as unavailable is how an agent spends one of three free-plan project slots on a duplicate.
tags: [starter, quota]
plugins: ["../.."]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Recognises `pending` as transient, says it will wait a few seconds and call
  `catalyst_whoami` again, and does not offer to create a project or send the user
  to the console to make one.
---

I'm new to Diagrid Catalyst and I want to try the durable workflow sample that
crashes mid-run and resumes where it stopped. `catalyst_whoami` worked, and its
`getDefaultProject` part came back as:

    {"outcome": "pending", "reason": "region_not_connected", "otherProjects": [],
     "instruction": "This organization's region is still coming up, so its \"default\"
      project cannot be created yet. Wait a few seconds and repeat the same call. This
      organization has no other project either, so ask the user to create one and to
      tell you its name. Do not create a project."}

What now?
