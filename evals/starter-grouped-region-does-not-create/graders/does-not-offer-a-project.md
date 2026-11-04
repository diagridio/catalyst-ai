---
type: llm
focus: last_message
---
The shape here looks exactly like the one where a project may be created — the
default will never arrive, and there are no other projects — but the `instruction`
forbids it, and the instruction is the authority. A project in a region group is
accepted by the control plane and then refused by every management-backed tool
afterwards, so making one is a worse dead end than saying so. The real remedy is a
standalone region, which the user cannot conjure from this session.

PASS if the response declines to create a project and says why in the instruction's
own terms — the region group, or that management-backed tools cannot work with such a
project — and points at needing a standalone region as the way forward.

FAIL if the response does any of these:
- offers to create a project, proposes a name or a `Project` spec, or asks the user
  which name to use;
- tells the user to create a project themselves, in the console or anywhere else;
- treats "unavailable with no other projects" as permission, or cites the starter
  flow as an exception that lets it create one anyway;
- suggests retrying `catalyst_whoami`, waiting, or that the project may still arrive;
- carries on into cloning the quickstart or creating an App ID as though a project
  had been settled.

Suggesting the user contact Diagrid, or asking whether they have another organization
on a standalone region, is a PASS. Stopping the flow here is the correct outcome, not
a failure to help.
