---
type: llm
focus: last_message
---
The instruction in the prompt permits a project and carries the spec for it. The
managed stores are not three fixed flags: each one is enabled only where the region
reports it supports that store — `defaultKVStoreEnabled` with `supportsManagedKVStore`,
`defaultWorkflowStoreEnabled` with `supportsWorkflows`, `defaultPubsubEnabled` with
`supportsManagedPubSub`. Asking for KV or workflows on a region that does not support
them is refused outright; pub/sub is switched off silently instead.

PASS if the response describes the `Project` spec it would apply and ties the managed
stores to what the region supports — naming the region check, or the `supports*`
fields, or saying in its own words that it will enable the stores the region offers
and read the project back to see which it actually got. Naming the three
`default*Enabled` fields while making that conditionality clear is a PASS.

FAIL if the response does any of these:
- presents all three `default*Enabled` flags as unconditionally `true`, with nothing
  about the region deciding which are available;
- omits the managed workflow store, or treats it as optional for a workflow flow;
- says the stores can be enabled after the app is created;
- claims the created project arrives with managed infrastructure the way `default`
  does.

Saying it would read the region with `catalyst_get_region` before applying is a PASS,
not a hedge — this session has no Catalyst tools, so saying so is all it can do.
