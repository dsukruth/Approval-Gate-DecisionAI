"""Your wrapper. Start with check_source_of_truth() and policy.json.

Flow: call Ezio -> read its signals -> check your persona's source of truth -> apply policy
-> decision (+ reason, evidence) -> audit log -> run the mock action only if approved.

Run one input:  python3 wrapper.py customer_support "Your 30% loyalty discount applies to the Pro plan."
Score yourself: python3 evaluate.py customer_support
"""
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import audit
from checks import build_checks
import laya_signal
import mock_actions
import sot_customer_support
from ezio_client import EzioError, analyze

HERE = Path(__file__).resolve().parent
PERSONAS = HERE.parent / "personas"
POLICY = json.loads((HERE / "policy.json").read_text())
laya_signal.start_loading()

APPROVE, HOLD, BLOCK = "APPROVE", "HOLD_FOR_REVIEW", "BLOCK"
RANK = {APPROVE: 0, HOLD: 1, BLOCK: 2}


@dataclass
class Signals:
    tier: str
    score: float
    summary: str
    accuracy_status: str
    claims_total: int
    claims_verified: int
    claims_contradicted: int
    tone: float
    bias: float
    agreement: float
    claims: list = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    level: str
    message: str
    signal: str = "data"
    source: str = None
    found: str = None
    expected: str = None
    sentence: int = None
    quote: str = None
    fix: dict = None


@dataclass
class Decision:
    decision: str
    reason: str
    evidence: list
    ezio: dict
    findings: list = field(default_factory=list)
    checks: list = field(default_factory=list)


def parse_signals(resp):
    try:
        verdict, dims = resp["verdict"], resp["dimensions"]
        acc = dims["accuracy"]
        if verdict["tier"] not in ("GREEN", "YELLOW", "RED") or acc["status"] not in ("scored", "not_scored", "unavailable"):
            raise ValueError("invalid tier or accuracy status")
        scores = [verdict["score"]] + [dims[d]["score"] for d in ("tone", "bias", "agreement")]
        if acc["status"] == "scored":
            scores.append(acc["score"])
        if any(isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s) or not 0 <= s <= 100 for s in scores):
            raise ValueError("scores must be finite numbers between 0 and 100")
        if not isinstance(verdict["summary"], str) or not isinstance(resp.get("claims", []), list):
            raise ValueError("invalid summary or claims")
        return Signals(
            tier=verdict["tier"], score=verdict["score"], summary=verdict["summary"],
            accuracy_status=acc["status"], claims_total=acc.get("claims_total", 0),
            claims_verified=acc.get("claims_verified", 0), claims_contradicted=acc.get("claims_contradicted", 0),
            tone=dims["tone"]["score"], bias=dims["bias"]["score"], agreement=dims["agreement"]["score"],
            claims=resp.get("claims", []),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise EzioError("malformed mock response", resp) from e


@lru_cache(maxsize=None)
def load_source_of_truth(persona):
    """Every .json and .csv file in the persona folder, keyed by file name (for example sot['policies'])."""
    data = {}
    for f in sorted((PERSONAS / persona).iterdir()):
        if f.stem in ("practice_set", "business_rules"):
            continue
        if f.suffix == ".json":
            data[f.stem] = json.loads(f.read_text())
        elif f.suffix == ".csv":
            with f.open() as handle:
                data[f.stem] = list(csv.DictReader(handle))
    return data


def check_source_of_truth(text, context, sot, persona="customer_support"):
    """Compare the text against the persona's data. Returns a list of Finding(level, message)."""
    if persona != "customer_support":
        return []
    return [Finding(**finding) for finding in sot_customer_support.check(text, context, sot)]


def ezio_claim_findings(signals):
    """Ezio's own fact checks: a contradicted public claim is a BLOCK; supported claims need nothing more."""
    findings = []
    for claim in signals.claims:
        if not isinstance(claim, dict):
            continue
        source = (claim.get("source") or {}).get("publisher", "Ezio")
        if claim.get("verdict") == "contradicted":
            findings.append(Finding(BLOCK, f"Ezio contradicted: '{claim.get('text', '')}' ({source})",
                                    signal="ezio_claim", source=source, found=claim.get("text")))
        elif claim.get("verdict") == "unverifiable":
            findings.append(Finding(POLICY["on_unverifiable_claim"], f"Ezio could not verify: '{claim.get('text', '')}'",
                                    signal="ezio_claim", source=source, found=claim.get("text")))
    return findings


def apply_policy(signals, findings, policy):
    decision, reasons = APPROVE, []

    def raise_to(level, reason):
        nonlocal decision
        reasons.append(reason)
        if RANK[level] > RANK[decision]:
            decision = level

    for f in findings:
        raise_to(f.level, f.message)
    for dim, rule in policy["dimension_minimums"].items():
        score = getattr(signals, dim)
        if score < rule["hold_below"]:
            raise_to(HOLD, f"{dim} score {score} is below {rule['hold_below']}")
    if signals.accuracy_status == "not_scored" and policy["when_accuracy_not_scored"] != "ignore":
        raise_to(policy["when_accuracy_not_scored"], "accuracy was not scored (no claims checked)")
    if signals.accuracy_status == "unavailable":
        raise_to(policy["when_accuracy_unavailable"], "fact-check was unavailable")
    if signals.claims_contradicted and not any(f.level == BLOCK for f in findings):
        raise_to(BLOCK, f"Ezio contradicted {signals.claims_contradicted} claim(s)")
    tier_decision = policy["tier_decisions"][signals.tier]
    if tier_decision != APPROVE:
        raise_to(tier_decision, f"Ezio tier is {signals.tier} ({signals.score})")
    if not reasons:
        reasons.append(f"No issues found (Ezio {signals.tier} {signals.score})")
    return reasons, decision


def build_evidence(findings, signals):
    """Findings first; otherwise record what was checked so every decision carries evidence."""
    supported = [f"Ezio supported: '{c.get('text', '')}'" for c in signals.claims
                 if isinstance(c, dict) and c.get("verdict") == "supported"]
    checked = (f"Checked against price_sheet.csv and policies.json; Ezio {signals.tier} {signals.score}, "
               f"accuracy {signals.accuracy_status}, tone {signals.tone}, bias {signals.bias}, agreement {signals.agreement}")
    return [f.message for f in findings] + supported + [checked]


def decide_without_ezio(text, context, persona, error):
    """Ezio failed: never approve. Our own data can still prove a BLOCK."""
    findings = check_source_of_truth(text, context, load_source_of_truth(persona), persona)
    blocks = [f.message for f in findings if f.level == BLOCK]
    decision = BLOCK if blocks else POLICY["on_ezio_failure"]
    reason = "; ".join([f"Ezio unavailable: {error}"] + blocks)
    evidence = [f.message for f in findings] + [f"Ezio error: {error}; failing closed per policy.json on_ezio_failure"]
    checks = build_checks(findings, None, POLICY, "Laya not run while Ezio is unavailable; skipped")
    return Decision(decision, reason, evidence, {"error": str(error), "response": error.response}, findings, checks)


def decide(text, context=None, persona="customer_support", scenario=None, audit_log=True):
    context = context or {}
    try:
        response = analyze(text, scenario=scenario)
        signals = parse_signals(response)
    except EzioError as e:
        result = decide_without_ezio(text, context, persona, e)
    else:
        laya_findings, laya_note = laya_signal.assess(text, POLICY)
        findings = (check_source_of_truth(text, context, load_source_of_truth(persona), persona)
                    + ezio_claim_findings(signals) + [Finding(level, message, signal="laya") for level, message in laya_findings])
        reasons, decision = apply_policy(signals, findings, POLICY)
        evidence = build_evidence(findings, signals) + ([laya_note] if laya_note else [])
        checks = build_checks(findings, signals, POLICY, laya_note)
        result = Decision(decision, "; ".join(reasons), evidence, response, findings, checks)
    if audit_log:
        audit.record(persona, text, context, result)
    return result


def gate(text, context=None, persona="customer_support"):
    result = decide(text, context, persona)
    print(f"{result.decision}: {result.reason}")
    if result.decision == APPROVE:
        mock_actions.run_for_persona(persona, text)
    else:
        print("[GATE] action not executed")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit('usage: python3 wrapper.py <persona> "<text>" [context-json]')
    gate(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}, sys.argv[1])
