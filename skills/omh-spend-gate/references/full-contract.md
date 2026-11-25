# Spend Gate

Load this on-demand contract after the compact `spend-gate` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The page task moves no money -- open a URL, log in, fill a form, capture blockers; use `omh-browser`.
- Users report a payment failure in the product and the ask is to sort those reports; use `omh-feedback-triage`.
- The ask is budget vs actual, a budget variance, or the month-end close; use `omh-finance-analysis`.
- The ask is a provider profile's posture or whether its secrets are present, with nothing bought; use `omh-provider-profile-posture`.

## Examples

Good example:

- Prompt: the api answered 402 payment required, pay it so we get the dataset
- Expected behavior: Read the amount, currency, payee, and method from the 402 challenge, show pre_spend_card/v1 with the cap and what remains of it, wait for the person's typed yes, pay through the client they installed, and report done only with the receipt header and the amount charged.
- Why: A 402 call spends the moment it is retried with a credential; the card is the one point where the person sees the price.

Bad example:

- Prompt: the checkout timed out, just click pay again
- Expected behavior: Mark the first charge unknown, look for it in the order history or the card activity, and show a new card only once it is shown absent.
- Why: A second click after a success nobody saw is a double charge.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the payee: the merchant, the exact site origin, the API host, or the wallet address and its network
- what is bought: the item, the plan, the call count, or the booking, with quantity and dates
- the quote: price, fees, taxes, shipping, and currency, with where and when it was read
- the person's cap for this spend or this period, and what was already spent against it
- the refund, cancellation, or reversal terms the payee states

Expected outputs:

- pre_spend_card/v1
- spend_confirmation/v1
- spend_receipt/v1
- spend_cap_ledger/v1

Artifact expectations:

- pre_spend_card/v1 names the payee with its exact origin or address, the item, the total with fees and taxes in its currency, the rail, the cap and what remains of it (or that the cap cannot be checked), the refund terms, whether the spend can be reversed, and the approver, who is the person whose money moves
- spend_confirmation/v1 records the person's typed yes in this session to that card's payee and total, with a host approval prompt's answer beside it as additional evidence when one appeared, and is void once the payee, the total, the currency, or the item changes
- spend_receipt/v1 cites the observed order id, transaction id, or receipt header with the amount actually charged, and keeps quoted, confirmed, submitted, charged, declined, and unknown as separate states
- spend_cap_ledger/v1 holds metadata only -- date, payee, amount, currency, rail, and receipt reference -- with the running total against the cap, and never a card number, security code, wallet key, password, or one-time code
