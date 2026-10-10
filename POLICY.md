# Decision Policy: Lumen Cloud customer support

**Gated action:** `send_email` to a customer. **Decisions:** APPROVE (send), HOLD_FOR_REVIEW (a support lead reads it first), BLOCK (never send). When signals disagree, the strictest one wins: BLOCK, then HOLD, then APPROVE.

## Signals

| # | Signal | What it checks | Effect |
|---|---|---|---|
| 1 | Source-of-truth check (`wrapper/sot_customer_support.py`) | Every price, discount, refund window, free trial and first-response time in the email, sentence by sentence, against `price_sheet.csv` and `policies.json`. Reads "$99/mo", "nineteen dollars", "15 percent", "one day" and several facts in one sentence. Uses the customer's plan and tenure from `context` for discount eligibility. | A contradiction is BLOCK, with the expected value and the file it came from as evidence. |
| 2 | Agent-authority and tone rules | Promises of features, delivery dates or policy exceptions; hype, guarantees, shouting, flattery. Negated phrases ("we can't guarantee") do not count. | HOLD |
| 3 | Ezio fact-checks (`claims[]`) | Public claims such as laws and regulations, which our files do not cover. | Contradicted is BLOCK. Unverifiable is HOLD. Supported needs nothing more, even when our files are silent. |
| 4 | Ezio tier and dimensions | Overall tier plus tone, bias and agreement scores, inspected individually because a GREEN tier can hide one very low dimension. | YELLOW is HOLD, RED is BLOCK, low dimension is HOLD. |
| 5 | Laya (optional, off by default) | A local decision model asked "does the agent promise a feature, a delivery date or a policy exception?" | Can only add a HOLD at 0.80 or more. Never approves or blocks. |

## Thresholds

| Setting | Value | Why |
|---|---|---|
| Ezio tier GREEN / YELLOW / RED | APPROVE / HOLD / BLOCK | GREEN still has to pass our own checks; RED means Ezio found a serious problem. |
| Tone | hold below 60 | Ezio marks under 60 as critical. One friendly "!" or an acronym like GDPR costs only 6 to 10 points, so normal replies pass. |
| Bias | hold below 80 | Each one-sided marker costs 15 points, so under 80 means two or more and the email pushes instead of informs. |
| Agreement | hold below 80 | Any flattery drops agreement below 80, and our rules send flattery to a manager. |
| Accuracy not scored | ignore | Ezio cannot see our price sheet; the source-of-truth check covers those facts, and a missing score is not a reason to block. |
| Accuracy unavailable | HOLD | We cannot rule out a wrong public claim, so a person reviews it. |
| Unverifiable claim | HOLD | Neither safe nor proven wrong. |
| Price match | exact to the cent | $79 is not $79.20; prices quoted to customers must be exact. |
| Laya | hold at 0.80 or above | On practice texts real promises scored 0.82 to 0.93 and good emails at most 0.44. A hype question was dropped because it scored plain prices at 0.89. |

## Explainability

Every decision returns, and the audit log records, two extra fields next to `reason` and `evidence`:

- `findings`: each problem with its signal, the sentence it came from, the value found, the value our data expects, the source file, and a `fix` when the wrong value appears word for word (for example `30%` to `15%`).
- `checks`: one row per signal (prices and policies; promises, hype and flattery; Ezio fact-checks; Ezio tone, bias and agreement; Ezio tier; Laya) marked passed, held, blocked or skipped.

The persona page highlights the failing sentence, shows the checklist, and offers the suggested fix, which goes back through `POST /decide` so the gate decides again.

## Failure behaviour

The gate fails closed. If Ezio is down, rate-limited past its retries, too slow, or returns a malformed response, the email is never approved: it is HOLD_FOR_REVIEW, or BLOCK when our own data already proves the email wrong. Every decision, including failures, is written to `audit_log.jsonl` with its reason and evidence, and the mock `send_email` runs only on APPROVE.
