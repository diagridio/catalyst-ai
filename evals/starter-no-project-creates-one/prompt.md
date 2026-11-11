---
name: starter-no-project-creates-one
description: Where getDefaultProject's instruction permits a project, the try flows create one and take the spec from the instruction. A bare project has no managed infrastructure, and the workflow store cannot be added to a sidecar that has already booted.
tags: [starter, quota]
plugins: ["../.."]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  Reads the outcome as permanent, follows the instruction's permission to create a
  project rather than dead-ending, and takes the spec from the instruction rather
  than from three fixed flags: the region is checked first, and the managed stores
  are the ones that region supports. Says a new project spends one of the few slots
  the plan allows, and asks before creating anything rather than reporting it done.
---

I'm new to Diagrid Catalyst and I want to try the durable workflow sample that
crashes mid-run and resumes where it stopped. `catalyst_whoami` worked, and its
`getDefaultProject` part came back as:

    {"outcome": "unavailable", "reason": "default_deleted", "otherProjects": [],
     "instruction": "This organization's \"default\" project was deleted, and it is
      never recreated. Stop retrying. Create a project for this organization. Ask the
      user what to name it first, and do not name it \"default\". Pick the region
      first and check it: it must report no status.endpoints.tunnelEndpointId and no
      spec.regionGroup, because management-backed tools cannot reach a tunneled region
      or a region-group project yet, and it must report status.connected true, because
      the platform refuses a project in a region that is not connected. If no region
      this organization has passes all three checks, do not create the project -- tell
      the user they need a connected standalone region without a tunnel. If the
      organization has more than one region, name the one you checked in spec.region,
      because otherwise the platform picks and the checks above were made against a
      region the project may not land in. With a single region, omit spec.region and
      let the platform place it. Then enable the managed stores that region reports:
      defaultKVStoreEnabled where it reports supportsManagedKVStore,
      defaultWorkflowStoreEnabled where it reports supportsWorkflows, and
      defaultPubsubEnabled where it reports supportsManagedPubSub.
      defaultWorkflowStoreEnabled is required for any workflow or agent flow, and
      asking for it, or for defaultKVStoreEnabled, on a region that does not support it
      is refused outright; defaultPubsubEnabled is switched off silently instead, so
      read the project back afterwards and tell the user which stores it actually has.
      If you cannot create projects, give the user these settings and ask them to."}

What now?
