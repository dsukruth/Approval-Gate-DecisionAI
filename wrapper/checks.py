"""Per-signal checklist returned with every decision, so a reader can see which signal passed, held or blocked.

build_checks(findings, signals, policy, laya_note) -> list of {"signal", "label", "status", "detail"} where
status is pass, hold, block or skipped. It only reports; apply_policy in wrapper.py makes the decision.
"""
BLOCK, HOLD = "BLOCK", "HOLD_FOR_REVIEW"
STATUS = {"APPROVE": "pass", HOLD: "hold", BLOCK: "block"}
LABELS = {
    "data": "Prices and policies",
    "promise_tone": "Promises, hype and flattery",
    "ezio_claims": "Ezio public fact-checks",
    "ezio_dimensions": "Ezio tone, bias and agreement",
    "ezio_tier": "Ezio overall tier",
    "laya": "Laya promise model (optional)",
}


def _row(signal, status, detail):
    return {"signal": signal, "label": LABELS[signal], "status": status, "detail": detail}


def _from_findings(signal, findings, kinds, clean):
    hits = [f for f in findings if f.signal in kinds]
    levels = {f.level for f in hits}
    status = "block" if BLOCK in levels else "hold" if HOLD in levels else "pass"
    detail = clean if not hits else hits[0].message + (f" (+{len(hits) - 1} more)" if len(hits) > 1 else "")
    return _row(signal, status, detail)


def _claims_row(findings, signals):
    if not signals.claims:
        return _from_findings("ezio_claims", findings, {"ezio_claim"}, "No public claims to fact-check")
    verdicts = [c.get("verdict") for c in signals.claims if isinstance(c, dict)]
    counts = ", ".join(f"{verdicts.count(v)} {v}" for v in ("supported", "contradicted", "unverifiable") if v in verdicts)
    return _from_findings("ezio_claims", findings, {"ezio_claim"}, counts or "No public claims to fact-check")


def _dimensions_row(signals, policy):
    scores = {dim: getattr(signals, dim) for dim in policy["dimension_minimums"]}
    low = [f"{dim} {score} is below {policy['dimension_minimums'][dim]['hold_below']}"
           for dim, score in scores.items() if score < policy["dimension_minimums"][dim]["hold_below"]]
    detail = "; ".join(low) if low else ", ".join(f"{dim} {score}" for dim, score in scores.items())
    return _row("ezio_dimensions", "hold" if low else "pass", detail)


def _tier_row(signals, policy):
    status = STATUS[policy["tier_decisions"][signals.tier]]
    detail = f"{signals.tier} {signals.score}"
    if signals.accuracy_status == "unavailable" and status == "pass":
        return _row("ezio_tier", STATUS[policy["when_accuracy_unavailable"]], f"{detail}; fact-check unavailable")
    return _row("ezio_tier", status, detail)


def _laya_row(findings, laya_note):
    if laya_note is None:
        return _row("laya", "skipped", "Off. Set LAYA_ENABLED=1 to add it.")
    if "skipped" in laya_note:
        return _row("laya", "skipped", laya_note)
    return _from_findings("laya", findings, {"laya"}, laya_note)


def build_checks(findings, signals, policy, laya_note):
    rows = [
        _from_findings("data", findings, {"data"}, "No conflicts with price_sheet.csv or policies.json"),
        _from_findings("promise_tone", findings, {"promise", "tone"}, "No promises, hype or flattery found"),
    ]
    if signals is None:
        rows += [_row("ezio_claims", "skipped", "Ezio unavailable"),
                 _row("ezio_dimensions", "skipped", "Ezio unavailable"),
                 _row("ezio_tier", "hold", "Ezio unavailable; the gate fails closed")]
    else:
        rows += [_claims_row(findings, signals), _dimensions_row(signals, policy), _tier_row(signals, policy)]
    return rows + [_laya_row(findings, laya_note)]
