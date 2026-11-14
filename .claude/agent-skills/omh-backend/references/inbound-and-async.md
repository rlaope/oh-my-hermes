# Inbound and Asynchronous Work

Load this when the surface receives webhooks, consumes a message queue, or sizes a connection pool. These are the paths where a delivery the code did not expect to see twice becomes a double charge, and where a missing check is a security defect rather than a style issue.

Everything here is prepared guidance. OMH receives no webhook, reads no queue, and opens no connection.

## 1. Receiving a webhook

Each step runs before the next one.

1. **Verify the signature over the raw body.** Compute the provider's signature over the exact bytes received, before any parsing, and compare it in constant time. A body that was parsed and serialised again is not the body that was signed, so a framework that parses before the handler runs needs its raw-body hook named in the contract. A delivery that fails the check is rejected with nothing processed. The signing secret lives in the secret store, never in the contract; during a rotation the handler accepts the old and the new secret for a stated window.
2. **Reject stale deliveries.** When the provider signs a timestamp, refuse a delivery outside a stated tolerance of a few minutes, so a captured request cannot be replayed later. When it signs none, the event-id record below is the only replay guard; say so in the contract.
3. **Record the delivery once.** At receipt, insert the provider's event id under a unique constraint together with the payload. A delivery whose id is already recorded is acknowledged as a success and dropped.
4. **Acknowledge fast, then process.** Answer 2xx as soon as the delivery is recorded, well inside the provider's timeout, and do the work from a queue or a job. The job marks the event processed in the same transaction that applies its effect (section 5 of `references/service-contract.md`), so a job that crashes before commit runs again and a job that committed does not. A handler that calls slow dependencies before answering times out, the provider retries, and the retry arrives while the first attempt is still running.
5. **Do not trust order or completeness.** Providers deliver out of order and can drop an event. When the current state matters, treat the event as a notification and read the object from the provider's API instead of applying the event body as a change.

## 2. Consuming a queue

- **Delivery is at least once.** The handler is idempotent: it records the message id under a unique constraint, or its effect is naturally repeatable (setting a value, not adding to one). A broker's exactly-once setting covers the broker, not the database write the handler makes.
- **Acknowledge after the effect commits.** Acknowledging on receipt loses the message when the handler crashes. Acknowledging after commit redelivers it when the crash lands in between, and idempotency absorbs that.
- **The lease outlasts the handler.** The visibility timeout or lease is longer than the slowest handler run, or another consumer receives the message while the first is still working on it.
- **State the ordering assumption.** Name the key that orders messages, such as a partition key or a message group, or state that nothing orders them. A handler that assumes order on a queue that does not keep it applies updates backwards.
- **Bound the attempts, then dead-letter.** Retries back off and stop at a maximum attempt count; past it the message moves to a dead-letter queue with the failure reason and the attempt count. Name who watches that queue and how a message is replayed from it.
- **Send a poison message straight to the dead-letter queue.** A message that can never succeed, because it fails validation or points at a row that no longer exists, is not retried. Retrying it blocks the messages behind it.

## 3. Connection pools

- **Size against the database's connection limit.** Pool size times processes per instance times the maximum instance count, plus migrations, admin sessions, and batch jobs, stays under the database's limit with headroom. Autoscaling multiplies the instance count; size for its maximum, or put a connection pooler in front of the database.
- **Checkout has a timeout inside the request budget.** Waiting for a free connection is part of the request's latency (section 6 of `references/service-contract.md`). A checkout with no timeout turns a saturated pool into hanging requests instead of a fast 503.
- **No connection is held across a remote call.** A transaction left open while the handler calls another service holds the connection and every row lock it took for the length of that call.
- **Name the pooler mode.** A pooler that hands out connections per transaction drops session state between transactions: `SET` values, advisory locks, and prepared statements unless the pooler supports them. Name the mode when a pooler is in use.

## 4. Failure modes

| Symptom | What actually went wrong | Correction |
| --- | --- | --- |
| Signature checks fail on valid deliveries | The signature was computed over a re-serialised body | Verify over the raw bytes before parsing |
| A payment or email happens twice | A provider retry or queue redelivery was processed again | Record the event or message id under a unique constraint |
| Retries pile up during a slow dependency | The handler did the work before acknowledging | Store, acknowledge, process from a job |
| One bad message stops the queue | It was retried forever at the head of the line | Bound attempts; send poison messages to the dead-letter queue |
| "Too many connections" after a scale-out | The pool was sized for one instance | Size pool times processes times maximum instances |

Signature checks, delivery counts, and pool saturation are claims about a running system; each stays `not_observed` until the executor reports the observation.
