---
type: llm
focus: last_message
---
The user's Catalyst read was refused with kind `ORG_MISMATCH`, and they asked for
their App ID count anyway. Nothing in the session could read a live project.

PASS if the response declines to give a count and instead reports the refusal —
the organization on the credential disagrees with the organization that was asked
for, so the number cannot be produced until that is settled.

FAIL if the response does any of these:
- gives an App ID count, or an estimate, or a "typically around N" figure;
- describes the refusal as a transient error and says it retried or will retry
  the same call (the refusal declares itself not retryable);
- reports the refusal as though the platform were broken rather than as a
  deliberate answer about which organization the credential belongs to.

Naming the two organizations, explaining which one the credential is for, and
saying what the user must decide, is a PASS. Offering to re-run the read after
the organization is corrected is also a PASS.
