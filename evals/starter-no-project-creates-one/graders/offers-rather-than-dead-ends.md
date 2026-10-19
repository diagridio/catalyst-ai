---
type: llm
focus: last_message
---
The user wants to run the durable-workflow starter flow and has no Catalyst project
at all — no `default`, none of their own. The try flows are the one path allowed to
create a project, because a first-run dead end is worse than a spent slot. A project
created this way is not `default`: none of the managed infrastructure is on unless
the `Project` spec asks for it, and `defaultWorkflowStoreEnabled` has to be set at
creation, since the sidecar reads workflow configuration at boot and enabling the
store later does not retrofit a running one. The session has no Catalyst tools, so
nothing in it can create anything.

PASS if the response offers to create a project and treats that as something still
to be done — it describes the `Project` it would apply with the managed stores
enabled, and either asks the user to confirm or presents the call as a proposal
awaiting their go-ahead.

FAIL if the response does any of these:
- states or implies that a project has been created, or reports the result of a
  create call;
- tells the user the flow cannot continue, or stops at "you have no project";
- describes creating a project without enabling the managed workflow store, or
  suggests enabling the workflow store after the app, agent or sample is created;
- claims a newly created project arrives with managed pub/sub, KV and the workflow
  store already attached, the way `default` does;
- proposes a project without saying that it spends a slot from a per-region limit.

Proposing a name for the project and letting the user override it is a PASS. Sending
the user to the Catalyst console to create it themselves is a PASS only if the
response also says which managed stores have to be enabled there. Saying it would
read the live project allowance (for example with `catalyst_get_usage`) before
creating one is a PASS, not a hedge — this session has no Catalyst tools, so saying
so is all it can do.
