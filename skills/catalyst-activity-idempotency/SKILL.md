---
name: catalyst-activity-idempotency
description: Make Dapr Workflow activities safe to run twice. Use when writing or reviewing an activity body with a side effect — payment, email, write, third-party call — or when a retry produced a duplicate. Activities execute at least once, never exactly once.
---

# Activity Idempotency

Goal: for every activity you write or review, be able to answer one question with
evidence from the code — if this body runs twice with the same input, is the state of
the outside world the same as if it had run once?

If the answer is no, the activity is not finished, however well it works on the happy
path.

## The guarantee you are designing against

The engine guarantees each scheduled activity runs **at least once**. It does not
guarantee exactly once, and no configuration makes it do so.

An activity runs a second time because:

- The worker crashed **after** the side effect committed but **before** the result was
  persisted to history. The engine has no record of success, so it schedules again.
- The invocation exceeded its deadline and the retry policy fired.
- Infrastructure redelivered the work item.

Note where the difficulty is. In the common case the duplicate happens *after the side
effect already succeeded*. Nothing inside the activity can detect this by looking at
its own inputs — the inputs are identical by design. Only the outside world knows the
work was already done, so only the outside world can refuse it.

## The rule

**Every side effect must carry a key that is stable across retries, and the write must
be conditional on that key.** A key alone does nothing; a conditional write with no
stable key deduplicates nothing. You need both.

## Hazard table

| Activity body does | A second run does | Fix |
| --- | --- | --- |
| `INSERT` a row | Two rows | Unique constraint on the natural key, then upsert or insert-ignore |
| `POST /payments` with amount and card | Charges twice | Send the provider's idempotency key header |
| Send an email or SMS | Two messages | Dedupe key recorded in the same transaction as the send, or a provider-side key |
| Increment a counter or balance | Double count | Replace with an idempotent set, or record contributing event ids and sum |
| Publish an event | Duplicate downstream work | Deterministic message id, and make the consumer idempotent too |
| `DELETE` by id | Second delete is a no-op | Already idempotent — nothing to do |
| `PUT` a full computed document to a fixed key | Same document written twice | Already idempotent — nothing to do |
| Read-only lookup | Nothing observable | Not an idempotency concern |
| Generate a key with `uuid()` *inside* the body | A new key per run, so the key deduplicates nothing | Derive the key from the activity input or the activity context |
| Append to a file or object | Content duplicated | Write to a key derived from the idempotency key instead of appending |

## Choosing the key

A valid key is **stable across every retry of one logical operation** and **distinct
across different logical operations**. Both halves matter: a key that changes per
attempt permits duplicates; a key shared by two genuinely different operations
suppresses work that should happen.

Sources, in order of preference:

1. **A natural key already in the input** — order id, invoice number, transaction
   reference. Best option: it is meaningful to the downstream system and survives a
   workflow rerun.
2. **The activity context's task execution id.** In Catalyst, every retry attempt of one
   activity invocation shares one stable `task_execution_id`; the retry backoff timer
   carries `origin__activity_retry_task_execution_id` pointing back to it. That
   stability is what makes it usable as a key.
3. **Workflow instance id plus something that identifies this call site** — usable when
   an activity is called once per workflow run.

Never use:

- **A value generated inside the activity body** — a fresh UUID, the current timestamp,
  a random suffix. It differs on every attempt, which is precisely the property a key
  must not have. This is the most common idempotency bug in review.
- **The per-attempt scheduling id.** Each retry attempt is a distinct scheduled task
  with its own `task_scheduled_id`. Keying on it gives every attempt a different key.
- **A child workflow's own instance id, when that child may be retried.** A retried
  child workflow is a *new instance with a new instance id* — unlike an activity retry,
  which reuses one execution id. If the key must survive child-workflow retry, derive it
  from the parent, or pass it down in the child's input.

## Why check-then-act is not enough

The pattern below is common, reads as careful, and does not make an activity idempotent:

```
# WRONG — two operations with a gap between them
existing = shipments.find_by_key(key)
if existing:
    return existing.id            # looks like it short-circuits the duplicate
return shipments.create(...)      # ... but two attempts can both reach here
```

Two failures:

1. **The gap.** The read and the write are separate operations. Two attempts can both
   read "absent", then both write.
2. **Retries are not necessarily serial.** An attempt that exceeded its deadline has not
   necessarily stopped running. The engine schedules the retry while the first attempt
   may still be in flight, so the two overlap — exactly the interleaving the check does
   not cover.

Make the *write itself* the thing that refuses the duplicate:

```
# CORRECT — one conditional operation; the store decides
shipments.insert(key=key, ...)  ON CONFLICT (key) DO NOTHING
return shipments.find_by_key(key).id
```

Any of these work, because in each the store adjudicates: a unique constraint, an
upsert, a compare-and-swap, a conditional PUT with an etag or version precondition, or
`INSERT ... IF NOT EXISTS`.

Check-then-act is still worth keeping as a **latency optimization** in front of a
conditional write — it avoids the round trip in the common case. It is not the
correctness mechanism, and it must never be the only mechanism.

## Non-idempotent third-party calls

Some providers offer no idempotency key and no way to query by your own reference. For
those, no in-activity trick makes the call safe. Record intent, then reconcile:

1. **Before the call**, commit an intent record keyed by the idempotency key, with
   status `pending` and whatever reference you will use to recognize the operation later.
2. **Make the call.**
3. **After the call**, update the record to `succeeded` (storing the provider's own id)
   or `failed`.

On a retry, read the intent record first:

| Intent record | Meaning | Do |
| --- | --- | --- |
| Absent | The first attempt did not reach the provider | Proceed from step 1 |
| `pending` | Outcome unknown — the call may or may not have landed | **Reconcile**, do not re-issue |
| `succeeded` | Already done | Return the stored provider id |
| `failed` | Terminal | Return the failure, or retry per policy if transient |

Reconcile by querying the provider for operations matching your reference — a search by
your own order id, a list over the relevant window, a webhook already received.

**If reconciliation is genuinely impossible**, then the choice is between at-most-once
(risk losing the operation) and at-least-once (risk duplicating it). That is a business
decision with money or user trust attached. Surface it to the user and let them choose.
Do not pick silently, and do not present a `pending` record as if it were resolved.

## Retries belong at the call site

Configure the retry policy where the activity is *called*, in the orchestrator — not
inside the activity body. Engine-driven retries use durable timers, so the backoff
survives a worker restart and every attempt appears in history.

A retry loop written inside the activity body is invisible to history, does not survive
a crash, and multiplies with the engine's own retries. Do not add one. If you need
per-error control, express it in the retry policy's error predicate, or return a typed
result the orchestrator can branch on.

Retry transient failures — timeouts, connection resets, 429, 503, transient deadlocks.
Do not retry input validation failures, business rejections, or permanent 4xx: they
consume the retry budget and delay the real failure without any chance of succeeding.

## Keep the payload small

Activity inputs and outputs are serialized into workflow history in the project's
workflow store. Pass identifiers, not documents. Return a status and a reference, not a
response body. Large payloads slow every subsequent replay of that instance and can
exceed state store limits — a failure that surfaces late, under load, on the instances
that matter most.

An idempotency key is small and belongs in the input. Put it there explicitly rather
than reconstructing it in the body, so it is visible to a reviewer.

## Catalyst notes

- **One KV store per project.** `number_of_kvstores_per_project` is 1 on every Catalyst
  plan — free, enterprise and internal alike. Paying does not raise it. A dedupe or
  intent table backed by the managed KV store therefore shares one component with all
  other state in the project: namespace your keys (`dedupe:<workflow>:<key>`) rather than
  assuming a dedicated store. Do not propose a second KV store as the fix.
- **A missing output in run history may be withheld, not absent.** At the default
  `metadata` data-sharing level, workflow and activity `input`, `output` and
  `customStatus` are **removed from the response**, not returned empty. When you are
  checking history to find out whether a duplicate occurred, you cannot see payloads. Say
  "the payload is not available at this data-sharing level" — never "the activity
  returned nothing", which the user has no way to detect as wrong. What is available:
  event types and names, timestamps, `task_scheduled_id`, `task_execution_id`, the retry
  origin key, and failure messages with stack traces.
- **Link the user to the run** when deciding whether a duplicate happened depends on a
  payload you cannot see. The route is `/workflows/<appId>/<runId>` on the console host.
  The project is a query parameter with two spellings and **no cross-fallback** —
  `?project=` matches the name-like project id (`default`), `?projectId=` matches the
  numeric uid (`prj-` prefix optional). A numeric uid passed as `?project=` matches no
  name, so the console never switches project and the run does not resolve where it
  lands. Name goes in `?project=`, number in `?projectId=`; if you cannot tell which you
  hold, omit the parameter. Never hardcode the host — derive it from the API URL in play,
  as production, staging, dev and local differ. A link that 404s or opens the wrong
  project is worse than no link: fall back to the run id and app id in plain text.

## Rules

- **Assume at least once.** An activity that is correct only if it runs once is a bug,
  not a risk to monitor.
- **A key generated inside the activity body is not an idempotency key.** Flag it every
  time.
- **Never let check-then-act stand as the only protection.** Require a conditional write.
- **Do not report a withheld payload as an empty one.** Name the data-sharing level.
- **Do not resolve an unknown outcome by guessing.** A `pending` intent with no
  reconciliation path is a question for the user.
- **This is static work.** Reviewing or writing an activity for idempotency needs the
  source and, at most, reads of run history. It never needs to run the workflow, start an
  instance, or modify state to prove a point. Do not create a project — the organization's
  `default` project already has a managed workflow store.
- For hazards in the *orchestrator* body rather than the activity body, use the
  `catalyst-workflow-determinism` skill. Non-determinism inside an activity is intended
  and is not a finding.
