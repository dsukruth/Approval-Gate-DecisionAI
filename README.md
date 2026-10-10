# Approval Gate: Lumen Cloud customer support

**A trust score doesn't make a decision. This wrapper does.**

Approval Gate decides whether an AI-drafted customer-support email may be sent. Every draft gets one of three decisions, with the reason and the evidence behind it:

| Decision | Meaning |
|---|---|
| `APPROVE` | The mock `send_email` action runs. |
| `HOLD_FOR_REVIEW` | A support lead reads it before anything is sent. |
| `BLOCK` | It is never sent. |

Built for the Decision-Grade AI Buildathon (Ezio AI) with the `customer_support` persona: Lumen Cloud, a fictional SaaS company with a price sheet and a policy file.

![Approval Gate console: a blocked email with the signal checklist, the failing sentence highlighted, and a suggested fix](docs/images/console-block-fix.jpg)

## Why a wrapper

Ezio scores tone, bias, agreement and public facts, but it cannot see Lumen Cloud's price sheet. Most wrong emails ("Your 30% loyalty discount applies to the Pro plan") come back GREEN with accuracy not scored. The gate adds an independent check against the company's own data, reads each Ezio dimension separately, and fails closed when Ezio is unreachable.

## Results

| Check | Result |
|---|---|
| Practice set (16 labelled emails) | 16/16 exact, 8/8 bad caught, 0 good blocked |
| Failure drills (down, rate limited, server error, malformed, unavailable, slow) | 15/15 |
| Independent eval, round 1 (32 emails written from the rules without seeing the code) | 32/32, 0 false blocks |
| Independent eval, round 2 (40 adversarial emails) | 40/40, 0 false blocks (this set was used to find gaps, so it is not an unbiased score) |
| Unit tests | 67 passing |

## How it decides

```mermaid
flowchart LR
    A["Draft email + customer context"] --> W["POST /decide"]
    W --> S["Source-of-truth rules<br/>price_sheet.csv + policies.json"]
    W --> E["Ezio API (local mock)<br/>claims, tone, bias, agreement, tier"]
    W -.->|optional| L["Laya promise model"]
    S --> P["Policy: strictest signal wins"]
    E --> P
    L --> P
    P --> D{"Decision"}
    D -->|APPROVE| M["send_email (mock action)"]
    D -->|HOLD or BLOCK| N["Not sent"]
    P --> AU["audit_log.jsonl"]
```

| Signal | What it checks | Effect |
|---|---|---|
| Prices and policies | Prices, yearly totals, discounts and eligibility, stacking, refund windows and scope, free trial, first-response times, sentence by sentence. Reads "$99/mo", "USD 49", "nineteen dollars", "half a day", "a quarter off". | Contradiction: BLOCK |
| Promises, hype and flattery | Feature, date or exception promises; guarantees; superlatives; flattery. "We can't guarantee" and "I can't promise" are not promises. | HOLD |
| Ezio public fact-checks | Laws and regulations the company files do not cover. | Contradicted: BLOCK. Unverifiable: HOLD. Supported: no hold. |
| Ezio tone, bias, agreement | Each dimension on its own, because a GREEN tier can hide one very low score. | Below threshold: HOLD |
| Ezio overall tier | GREEN, YELLOW, RED | YELLOW: HOLD. RED: BLOCK. |
| Laya (optional, off by default) | A local "System 1" model asked whether the email promises a feature, date or exception. | Can only add a HOLD at 0.80 or above |

Thresholds and their one-sentence justifications are in [POLICY.md](POLICY.md) and [wrapper/policy.json](wrapper/policy.json).

## Explainable decisions

Every `POST /decide` response keeps the required `decision`, `reason` and `evidence`, and adds:

- `findings`: each problem with its signal, the sentence it came from, the value found, the value the data expects, the source file, and a `fix` when the wrong value appears word for word.
- `checks`: six rows (prices and policies; promises, hype and flattery; Laya; Ezio fact-checks; Ezio dimensions; Ezio tier) marked passed, held, blocked or skipped.

```json
{
  "decision": "BLOCK",
  "reason": "Loyalty discount is 15% (policies.json); the email says 30%.",
  "findings": [{
    "level": "BLOCK", "signal": "data", "source": "policies.json",
    "found": "30%", "expected": "15%", "sentence": 0,
    "fix": {"sentence": 0, "find": "30%", "replace": "15%"}
  }],
  "checks": [{"signal": "data", "label": "Prices and policies", "status": "block", "detail": "Loyalty discount is 15% (policies.json); the email says 30%."}],
  "action_executed": false
}
```

Both fields are also written to the audit log.

## The console

`wrapper/ui/` holds an offline page for a support lead. You draft an email, set the customer's plan and tenure, and press **Check and send**. The page shows:

- the decision and whether the mock email was sent
- the grouped signal checklist
- the email sentence by sentence, with failing values marked
- a suggested fix built only from price-sheet and policy values; **Use and re-check** sends it back through the gate

The page never decides or sends anything itself. Light and dark themes, and it works down to 375px.

<img src="docs/images/console-mobile-dark.jpg" alt="The console in dark mode on a phone-width screen" width="320">

## Run it

Python 3.9 or newer, standard library only. Nothing to install.

```bash
# practice set plus the six failure drills, then the results page
python3 gate.py practice --persona customer_support

# one email through the gate, with its mock send_email action
python3 gate.py try --persona customer_support "The Pro plan is \$49 per month."

# console, wrapper and mock together for a demo
python3 gate.py serve --persona customer_support

# final judging set (passphrase from the organizers)
python3 gate.py judge --persona customer_support --team "Your Team Name"

# unit tests
cd wrapper && python3 -m unittest test_sot_customer_support test_wrapper_policy test_laya_signal test_checks
```

### Optional: Laya (local "System 1" decision model)

[Laya](https://huggingface.co/convaiinnovations/laya) is an open model (Convai, Apache-2.0, ModernBERT-large encoder) that scores typed answers in one forward pass instead of generating text. The gate uses it as an optional, add-only signal in [`wrapper/laya_signal.py`](wrapper/laya_signal.py):

- **Question asked:** "Does the support agent promise a product feature, a delivery date, or an exception to company policy?" (a yes/no `noul` question).
- **Effect:** a probability of 0.80 or more adds a HOLD_FOR_REVIEW with the probability as evidence. Laya can never approve or block, so the price and policy rules and Ezio stay in charge.
- **Calibration:** on the practice texts, real promises scored 0.82 to 0.93 and good emails at most 0.44. A second "hype" question was tested and dropped, because it scored a plain price statement ("The Pro plan is $49 per month.") at 0.89.
- **Robustness:** the model loads in a background thread, so `/health` answers at once. It loads offline from the local cache (`HF_HUB_OFFLINE=1`). Predictions are serialized behind a lock, because the Apple GPU (Metal) backend aborts on overlapping calls, and any load or prediction error skips Laya with a note in the evidence.
- **Off by default:** judged runs use the standard-library path. With Laya on, the practice set and failure drills still score 16/16 and 15/15.

```bash
python3 -m venv .venv-laya && .venv-laya/bin/pip install laya
LAYA_ENABLED=1 GATE_WRAPPER_CMD=".venv-laya/bin/python wrapper/serve.py" python3 gate.py practice --persona customer_support
```

## Testing beyond the practice set

The [`eval/`](eval/) folder holds independent tests. It is outside `wrapper/`, so it never changes the judging fingerprint.

| Tool | What it does |
|---|---|
| `eval/run_eval.py <set.json>` | Runs any set of `{text, context, expected}` emails through the real gate against a private mock and reports exact matches, catch rate, false blocks and every disagreement. Judges can use it for their own batch of questions. |
| `eval/sets/round1.json`, `round2.json` | 72 emails written blind from the business rules by separate agents (32 and 40). Both score 100% with no false blocks; round 2 was used to find and fix gaps. |
| `eval/llm_eval.py` | Asks a frontier model, through HarnessRouter (main route) or TokenRouter (fallback), to write fresh test emails from the rules and data only. It runs them through the gate, gets Laya's opinion on each, and has the model re-check every disagreement to separate real gate misses from label errors. Keys come from `HR_API_KEY` / `TOKENROUTER_API_KEY` or `~/.config/<provider>/key` and are never printed or committed. |
| `eval/laya_judge.py` | Laya as the second opinion: approve, hold or block, plus promise and hype probabilities for every generated email. |

The first model-written round (40 emails, `eval/generated/20261010-222555-*`) scored 32/40 exact with 2 false blocks. The misses it found (new promise and flattery wording, card-required phrasing, and a correctly discounted price being blocked) are the next rule improvements. Laya agreed with the gate on intent-style cases but, as expected, cannot judge prices it has never seen.

### Sharing a temporary demo link

The wrapper has no authentication and is meant for local, fictional data. To show it to someone for a short time, run `gate.py serve`, note the wrapper port it prints, and open a Cloudflare quick tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:<wrapper-port>
```

The link works only while both processes run.

## Project layout

| Path | What it is |
|---|---|
| `wrapper/sot_customer_support.py` | Source-of-truth, promise and tone rules (pure functions) |
| `wrapper/wrapper.py` | Ezio call, signal parsing, policy, decision, fail-closed path |
| `wrapper/checks.py` | Per-signal checklist returned with every decision |
| `wrapper/laya_signal.py` | Optional Laya signal (add-only HOLD) |
| `wrapper/policy.json` | Thresholds and justifications |
| `wrapper/ui/` | Console page (`persona.html`, `persona.css`, `persona.js`) |
| `wrapper/test_*.py` | Unit tests |
| `eval/` | Independent eval sets, batch runner, and the HarnessRouter / TokenRouter / Laya test tool |
| `docs/screenshots/` | Console screenshots and the final results page (50.0 / 50) |
| `POLICY.md` | One-page decision policy |
| `STARTER.md` | The organizers' original starter README (setup, judging, rules) |

`harness/`, `mock_ezio.py`, `fixtures.json` and `personas/` are the organizers' files and are unchanged.
