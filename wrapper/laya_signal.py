"""Optional Laya signal: a local "System 1" decision model that can only add a HOLD.

Off unless LAYA_ENABLED=1 and the `laya` package imports (run the wrapper with .venv-laya/bin/python).
Laya answers yes/no questions about the email with calibrated probabilities. A probability at or above
policy.json laya.hold_above raises HOLD_FOR_REVIEW. It never approves and never blocks, and any load
or prediction error skips it, so the source-of-truth rules and Ezio stay in charge.
"""
import os
import threading

HOLD = "HOLD_FOR_REVIEW"
QUESTIONS = {
    "promise": {"type": "noul", "instructions": "Does the support agent promise a product feature, a delivery date, "
                                                "or an exception to company policy?"},
}
# A "hype" question was tried and dropped: on the practice texts it scored plain price statements
# ("The Pro plan is $49 per month.") at 0.89, so it could not separate hype from facts.
LABELS = {"promise": "promises a feature, date or exception"}

_ready = threading.Event()
_state = {"router": None, "error": None}
_predict_lock = threading.Lock()  # the Metal (MPS) backend aborts on overlapping predictions


def enabled():
    return os.getenv("LAYA_ENABLED") == "1"


def _load_router():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # use the cached checkpoint; the gate must run offline
    from laya import Router
    return Router(max_loaded=1)


def _load(loader):
    try:
        _state["router"] = loader()
    except Exception as e:  # missing package, download failure, unsupported device
        _state["error"] = f"{type(e).__name__}: {e}"
    finally:
        _ready.set()


def start_loading(loader=_load_router):
    """Load the model in the background so the wrapper's /health answers immediately."""
    if enabled() and not _ready.is_set():
        threading.Thread(target=_load, args=(loader,), daemon=True).start()


def _router(wait_seconds):
    if not enabled():
        return None, None
    _ready.wait(wait_seconds)
    if not _ready.is_set():
        return None, "Laya still loading; skipped"
    if _state["router"] is None:
        return None, f"Laya unavailable ({_state['error']}); skipped"
    return _state["router"], None


def assess(text, policy, router=None):
    """Return (findings, note). findings are (level, message) tuples; note is one evidence line or None."""
    config = policy["laya"]
    note = None
    if router is None:
        router, note = _router(config["load_wait_seconds"])
        if router is None:
            return [], note
    try:
        with _predict_lock:
            answers = router.predict(text, QUESTIONS, model=config["model"])["answers"]
        probabilities = {name: float(answers[name]["noul"]) for name in QUESTIONS}
    except Exception as e:
        return [], f"Laya prediction failed ({type(e).__name__}); skipped"
    findings = [(HOLD, f"Laya: {p:.0%} likely the email {LABELS[name]} (holds at {config['hold_above']:.0%}).")
                for name, p in probabilities.items() if p >= config["hold_above"]]
    summary = ", ".join(f"{name} {p:.2f}" for name, p in probabilities.items())
    return findings, f"Laya checked: {summary}"
