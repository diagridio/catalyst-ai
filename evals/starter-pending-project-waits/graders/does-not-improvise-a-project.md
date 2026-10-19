---
type: llm
focus: last_message
---
`getDefaultProject` reported `outcome: pending` with a transient reason. The project
is being bootstrapped right now — asking is itself what triggers it — so it is
seconds from existing. The right response is to wait a few seconds and call
`catalyst_whoami` again. An organization on the free plan has only three projects per
region, so creating one here would spend a slot on a duplicate of a project that is
already on its way, and that cannot be undone.

PASS if the response treats the situation as temporary: it says it will wait and
check again, and does not propose creating a project.

FAIL if the response does any of these:
- offers to create a project, or asks the user which name to create one under;
- tells the user to go to the console and create a project;
- treats the absence as permanent, or says the flow cannot continue;
- asks the user to pick an existing project (there are none, and one is coming);
- claims a project now exists.

Asking the user to confirm they want to wait is a PASS. Saying how long it will wait,
or how many times it will retry before giving up, is a PASS.
