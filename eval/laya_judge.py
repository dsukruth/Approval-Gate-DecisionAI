"""Secondary opinion from Laya (local, offline): .venv-laya/bin/python eval/laya_judge.py in.json out.json

Laya cannot see the price sheet, so its decision is a second opinion on intent (promises, hype), not on facts.
"""
import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
from laya import Router  # noqa: E402

QUESTIONS = {
    "decision": {"type": "choice", "instructions": "A support agent wrote this email to a customer. Should it be sent, "
                 "held for a manager, or blocked?",
                 "criteria": {"APPROVE": "accurate, neutral, no promises",
                              "HOLD_FOR_REVIEW": "promises a feature, date or exception, or uses hype, guarantees or flattery",
                              "BLOCK": "states a wrong price, discount, refund, trial or response time, or a false claim"}},
    "promise": {"type": "noul", "instructions": "Does the agent promise a product feature, a delivery date, or an exception to policy?"},
    "hype": {"type": "noul", "instructions": "Is the email over-the-top promotional, flattering, or does it guarantee results?"},
}


def main(src, dst):
    items = json.loads(open(src).read())
    router = Router(max_loaded=1)
    out = []
    for item in items:
        answers = router.predict(item["text"], QUESTIONS, model="english")["answers"]
        out.append({"id": item["id"], "decision": answers["decision"].get("choice"),
                    "promise": round(float(answers["promise"]["noul"]), 2), "hype": round(float(answers["hype"]["noul"]), 2)})
    with open(dst, "w") as handle:
        json.dump(out, handle, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
