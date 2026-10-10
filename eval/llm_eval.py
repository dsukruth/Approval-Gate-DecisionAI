"""Fresh test emails from a model, run through the gate, with Laya as a second opinion.

    python3 eval/llm_eval.py                     # 40 new emails; HarnessRouter if its key works, else TokenRouter
    python3 eval/llm_eval.py --provider tokenrouter --count 20
    python3 eval/llm_eval.py --set eval/sets/round2.json   # reuse a saved set (no generation)

Main route: HarnessRouter (key in HR_API_KEY or ~/.config/harnessrouter/key), fallback TokenRouter
(TOKENROUTER_API_KEY or ~/.config/tokenrouter/key). Secondary: Laya, run locally from .venv-laya.
The model sees only the persona's rules and data. Its labels are leads, not ground truth:
disagreements with the gate are re-checked by the model and split into likely gate misses and label errors.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import HarnessRouter, ProviderError, TokenRouter, read_key  # noqa: E402
from run_eval import DECISIONS, REPO, gate, load_items, print_report, run_items, summarize  # noqa: E402

OUT_DIR = REPO / "eval" / "generated"
PERSONA = REPO / "personas" / "customer_support"
LAYA_PYTHON = REPO / ".venv-laya" / "bin" / "python"


def persona_brief():
    claims = json.loads((REPO / "fixtures.json").read_text())["known_claims"]
    lines = "\n".join(f"- \"{c['patterns'][0]}\" ({c['verdict']})" for c in claims)
    return (f"BUSINESS RULES\n{(PERSONA / 'business_rules.md').read_text()}\n\npolicies.json\n"
            f"{(PERSONA / 'policies.json').read_text()}\n\nprice_sheet.csv\n{(PERSONA / 'price_sheet.csv').read_text()}\n\n"
            "PUBLIC CLAIMS THE FACT-CHECKER KNOWS (use a public claim only by including one of these phrases verbatim):\n"
            + lines)


def extract_json(text):
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = min(i for i in (cleaned.find("["), cleaned.find("{")) if i >= 0)
    end = max(cleaned.rfind("]"), cleaned.rfind("}"))
    return json.loads(cleaned[start:end + 1])


def generate(provider, count):
    prompt = (
        f"{persona_brief()}\n\nWrite {count} NEW emails a Lumen Cloud support agent might send to a customer, 1 to 3 "
        "sentences, varied wording. Mix about 35% APPROVE, 40% BLOCK, 25% HOLD_FOR_REVIEW under the rules. Make a third "
        "hard: numbers in words, '$99/mo', 'USD 49', 'a fortnight', 'half a day', fractions, yearly totals, several facts "
        "in one sentence, passive-voice promises, correct refusals. Each item must have exactly one correct decision. "
        "Do not create files. Reply with ONLY a JSON array of objects: {\"text\": str, \"context\": {\"plan\": "
        "\"Starter\"|\"Pro\"|\"Business\"|\"Enterprise\", \"customer_tenure_months\": int}, \"expected\": "
        "\"APPROVE\"|\"HOLD_FOR_REVIEW\"|\"BLOCK\", \"why\": str}"
    )
    batch = extract_json(provider.ask(prompt))
    items = [i for i in batch if isinstance(i, dict) and i.get("expected") in DECISIONS and isinstance(i.get("text"), str)]
    return [{**item, "id": f"g{n + 1:02d}"} for n, item in enumerate(items)]


def recheck(provider, mismatches):
    if not mismatches:
        return []
    cases = [{"id": r["id"], "text": r["text"], "context": r["context"], "label": r["expected"],
              "gate_decision": r["decision"], "gate_reason": r["reason"]} for r in mismatches]
    prompt = (f"{persona_brief()}\n\nFor each case the label and the gate disagree. Which decision do the rules require? "
              "Reply with ONLY a JSON array of {\"id\": str, \"required\": str, \"right\": \"gate\"|\"label\"|\"unclear\", "
              "\"why\": str}.\n\n" + json.dumps(cases, indent=1))
    verdicts = extract_json(provider.ask(prompt))
    return [v for v in verdicts if isinstance(v, dict)] if isinstance(verdicts, list) else []


def laya_opinions(items, stamp):
    if not LAYA_PYTHON.exists():
        return {}, "Laya skipped: .venv-laya not found"
    src, dst = OUT_DIR / f"{stamp}-laya-in.json", OUT_DIR / f"{stamp}-laya.json"
    src.write_text(json.dumps([{"id": i["id"], "text": i["text"]} for i in items]))
    run = subprocess.run([str(LAYA_PYTHON), str(REPO / "eval" / "laya_judge.py"), str(src), str(dst)],
                         capture_output=True, text=True, timeout=900)
    src.unlink(missing_ok=True)
    if run.returncode != 0:
        return {}, f"Laya failed: {run.stderr.strip().splitlines()[-1] if run.stderr.strip() else run.returncode}"
    return {o["id"]: o for o in json.loads(dst.read_text())}, None


def pick_provider(name):
    if name in ("auto", "harnessrouter"):
        key = read_key("HR_API_KEY", "harnessrouter")
        if key:
            provider = HarnessRouter(key)
            try:
                provider.discover()
                provider.choose_harness()
                return provider
            except ProviderError as e:
                if name == "harnessrouter":
                    sys.exit(f"HarnessRouter unavailable: {e}")
                print(f"HarnessRouter unavailable ({str(e)[:120]}); falling back to TokenRouter.", file=sys.stderr)
    key = read_key("TOKENROUTER_API_KEY", "tokenrouter")
    if not key:
        sys.exit("No working provider key. See eval/README.md.")
    return TokenRouter(key)


def three_way(results, laya):
    print("\nTHREE-WAY: gate vs label vs Laya")
    rows = [(r, laya.get(r["id"], {})) for r in results]
    with_laya = [(r, l) for r, l in rows if l.get("decision")]
    if with_laya:
        print(f"Laya agrees with gate {sum(l['decision'] == r['decision'] for r, l in with_laya)}/{len(with_laya)}, "
              f"with label {sum(l['decision'] == r.get('expected') for r, l in with_laya)}/{len(with_laya)}")
    for r, l in rows:
        flag = "  <- all three differ" if l.get("decision") and len({r["decision"], r.get("expected"), l["decision"]}) == 3 else ""
        print(f"[{r['id']}] gate {r['decision']:15} label {str(r.get('expected')):15} laya {str(l.get('decision')):15} "
              f"promise {l.get('promise', '-')} hype {l.get('hype', '-')}{flag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=("auto", "harnessrouter", "tokenrouter"), default="auto")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--set")
    parser.add_argument("--no-laya", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    provider = pick_provider(args.provider)
    print(f"main route: {provider.label}", file=sys.stderr)
    if args.set:
        items = load_items(args.set)
    else:
        items = generate(provider, max(1, min(args.count, 60)))
        (OUT_DIR / f"{stamp}-set.json").write_text(json.dumps(items, indent=1))
        print(f"generated {len(items)} emails -> eval/generated/{stamp}-set.json", file=sys.stderr)

    with gate() as decide:
        results = run_items(items, decide)
    summary = summarize(results)
    print_report(results, summary)

    laya, note = ({}, "Laya skipped") if args.no_laya else laya_opinions(items, stamp)
    if note:
        print(f"\n{note}")
    three_way(results, laya)

    verdicts = recheck(provider, summary["mismatches"])
    for bucket, title in (("label", "likely gate misses"), ("gate", "likely label errors"), ("unclear", "unclear")):
        rows = [v for v in verdicts if v.get("right") == bucket]
        if rows:
            print(f"\n{title}: {len(rows)}")
            for v in rows:
                print(f"  [{v.get('id')}] requires {v.get('required')}: {v.get('why')}")
    (OUT_DIR / f"{stamp}-results.json").write_text(json.dumps(
        {"main_route": provider.label, "summary": {k: v for k, v in summary.items() if k != "mismatches"},
         "results": results, "laya": laya, "recheck": verdicts}, indent=1))


if __name__ == "__main__":
    main()
