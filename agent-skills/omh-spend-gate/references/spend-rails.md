# Spend Rails

Load this before money moves. OMH prepares the card and checks the receipt; the person's own payment surface moves the money, and no spend is `charged` until a receipt is observed. The card's fields and the confirmation rule are in the skill body; this page holds what differs by rail.

## 1. Rails

| Rail | The quote comes from | The receipt that counts | Reversal |
| --- | --- | --- | --- |
| card checkout in a page | the order summary after shipping and tax | the confirmation page's order number, or the merchant's confirmation message | the merchant's refund or cancellation window; a card dispute is a last resort, not a plan |
| HTTP 402 or pay-per-request call | the 402 challenge: amount, currency, method, and the payee it names | a receipt header on the paid response, or the payment client's transaction id | usually none; treat it as final |
| wallet transfer | the transfer preview: the whole destination address, the network, the amount, and the network fee | the transaction id, confirmed on that network | none; a transfer to a wrong address is lost |
| booking or deposit | the price breakdown: unit price, taxes, fees, deposit against balance, and the free-cancellation deadline | the booking reference from the provider | the cancellation window, stated as a date and time |
| paid data endpoint or metered API | the price per call times the planned call count, with a ceiling on calls | the provider's usage record or invoice line for the run | usually none; stop at the ceiling |
| subscription or renewal | the first charge, the renewal amount, the cadence, and the next charge date | the provider's invoice or subscription receipt | cancellation before the next charge date |

A wallet transfer card shows the whole destination address, never a shortened one, and the person confirms the address as well as the amount: a lookalike address that shares the first and last characters is a known way to lose a transfer.

## 2. Native surfaces, by presence

Each surface below is used only when it is present, and none replaces the person's typed confirmation in this session.

- `browser_vault`: when `browser_vault` is in your tool list or tool_search finds it, it fills a saved card only on the exact origin the card was saved for, after its own approval prompt, and refuses in a session nobody can answer. Record that prompt's answer beside the typed confirmation, and stop on a `payment_declined` result rather than retry it. When it is absent or blocked, stop at the payment step: the person enters the card, and never type a card the person gives you into the page.
- `clarify`: when `clarify` is in your tool list or tool_search finds it, ask for the confirmation with the card in the question; otherwise ask in a plain reply and end the turn.
- Browser tools (`browser_navigate`, `browser_snapshot`, `browser_click`): read the quote and the receipt with them. A snapshot of the confirmation page with its order number is an observed receipt; a snapshot of the cart is a quote.
- The approval prompt Hermes shows for a flagged command: when the paying command raises it, record its answer beside the typed confirmation. An auto-approval (`/yolo`, `approvals.mode: off`, or a call the default `smart` mode judged low-risk and approved itself) or a command the check did not flag is no confirmation at all.
- The optional Hermes skill `stripe-link-cli`, the Hermes Pay plugins `pay` (hosted) and `pay-cli` (local), and the `mppx` CLI (`mpp-agent` on a Hermes that still ships it), only when the person installed them. `stripe-link-cli` with `--request-approval` asks the person in their Link app, and `pay` and `pay-cli` confirm each payment through an MCP elicitation and decline when nobody can answer; those answers are additional evidence recorded beside the typed confirmation, never in place of it. `mppx` pays the 402 challenge as it runs and asks no one, so running it is the spend and comes only after the typed confirmation. The `hermes-mpp` plugin, with no `MPP_ALLOWED_ORIGINS` allow list set, auto-pays any supported 402 that ordinary HTTP traffic meets, with no cap or confirmation: stop and tell the person before any HTTP call. The receipt any of them returns fills `spend_receipt/v1`.

## 3. Unknown outcomes

An outcome nobody saw -- a timeout, a dropped connection, a page that reloaded, a server error after submit, a client that exited without a result -- is `unknown`, not failed. It is the rule `omh-llm-app-dev` applies to an ambiguous public post: reconcile before any retry.

1. Mark the spend `unknown` in the ledger with what is known: payee, amount, time, and rail.
2. Look for the charge where it would show: the merchant's order history, the confirmation message, the card or wallet activity, the payment client's status, the provider's usage record.
3. Found: record the receipt and stop; there is nothing to retry.
4. Shown absent: a retry is a new spend, so show the card again and get a new confirmation.
5. Still unknown: report it as unknown with where it was checked, and ask the person to check with the payee before anything is retried.

## 4. Cap ledger

`spend_cap_ledger/v1` is a list of rows the person can read: date, payee, amount, currency, rail, state, and receipt reference, with the running total against the cap. It never holds a card number, security code, wallet key, password, one-time code, or a whole receipt body. An `unknown` row counts against the cap until it is reconciled. The ledger lives where the person keeps it; OMH writes no ledger file of its own. When no ledger is supplied, ask the person for what they already spent against this cap in the period and put it on the card. If they cannot say, what is already spent is unknown: never assume zero and never show the full cap as remaining. The card says the cap cannot be checked, and the spend goes ahead only against a cap the person sets for this spend alone, with the total checked against it. Show the new row for the person to store.
