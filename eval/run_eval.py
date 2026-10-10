"""Score the gate on an eval set: python3 eval/run_eval.py eval/sets/round1.json

An eval set is a JSON array of {"id", "text", "context": {"plan", "customer_tenure_months"}, "expected", "why"}.
"expected" is optional (APPROVE, HOLD_FOR_REVIEW or BLOCK); without it the run just lists decisions.
Each email goes through the real wrapper (wrapper.decide) against a private local mock with no latency.
Standard library only. Nothing here changes wrapper/, so the judging fingerprint is unaffected.
"""
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DECISIONS = ("APPROVE", "HOLD_FOR_REVIEW", "BLOCK")


def load_items(path):
    items = json.loads(Path(path).read_text())
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a JSON array of items")
    valid = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            print(f"skipping item {index}: needs a non-empty 'text'", file=sys.stderr)
            continue
        if item.get("expected") not in (None, *DECISIONS):
            print(f"skipping item {index}: 'expected' must be one of {', '.join(DECISIONS)}", file=sys.stderr)
            continue
        context = item.get("context") if isinstance(item.get("context"), dict) else {}
        valid.append({**item, "id": item.get("id", f"item{index + 1}"), "context": context})
    return valid


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def gate():
    """Start a private mock Ezio, point the wrapper at it, and yield wrapper.decide."""
    port = _free_port()
    env = {**os.environ, "PORT": str(port), "LATENCY": "0"}
    mock = subprocess.Popen([sys.executable, str(REPO / "mock_ezio.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        os.environ["EZIO_URL"] = f"http://127.0.0.1:{port}"
        sys.path.insert(0, str(REPO / "wrapper"))
        from wrapper import decide
        yield decide
    finally:
        mock.terminate()


def run_items(items, decide):
    results = []
    for item in items:
        result = decide(item["text"], item["context"], audit_log=False)
        results.append({**item, "decision": result.decision, "reason": result.reason, "evidence": result.evidence})
    return results


def summarize(results):
    labelled = [r for r in results if r.get("expected")]
    good = [r for r in labelled if r["expected"] == "APPROVE"]
    bad = [r for r in labelled if r["expected"] != "APPROVE"]
    return {
        "items": len(results),
        "labelled": len(labelled),
        "exact": sum(r["decision"] == r["expected"] for r in labelled),
        "caught": sum(r["decision"] != "APPROVE" for r in bad),
        "bad": len(bad),
        "false_blocks": sum(r["decision"] != "APPROVE" for r in good),
        "good": len(good),
        "mismatches": [r for r in labelled if r["decision"] != r["expected"]],
    }


def print_report(results, summary):
    if not summary["labelled"]:
        for r in results:
            print(f"[{r['id']}] {r['decision']:15} {r['text'][:90]}")
        return
    print(f"items {summary['items']}  exact {summary['exact']}/{summary['labelled']}  "
          f"caught {summary['caught']}/{summary['bad']}  false blocks {summary['false_blocks']}/{summary['good']}")
    for r in summary["mismatches"]:
        print(f"\n[{r['id']}] expected {r['expected']} got {r['decision']}\n  text: {r['text']}\n"
              f"  context: {r['context']}\n  why: {r.get('why', '')}\n  gate reason: {r['reason']}")


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: python3 eval/run_eval.py <eval_set.json>")
    items = load_items(argv[1])
    with gate() as decide:
        results = run_items(items, decide)
    print_report(results, summarize(results))


if __name__ == "__main__":
    main(sys.argv)
