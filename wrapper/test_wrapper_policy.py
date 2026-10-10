"""Policy tests for wrapper.apply_policy and Ezio claim handling, using synthetic signals.

Run: cd wrapper && python3 -m unittest test_wrapper_policy
"""
import unittest

from wrapper import APPROVE, BLOCK, HOLD, POLICY, Signals, apply_policy, ezio_claim_findings


def signals(tone=100, bias=100, agreement=100, claims=(), tier="GREEN", status="not_scored"):
    contradicted = sum(c.get("verdict") == "contradicted" for c in claims)
    return Signals(tier=tier, score=90, summary="", accuracy_status=status, claims_total=len(claims),
                   claims_verified=0, claims_contradicted=contradicted, tone=tone, bias=bias,
                   agreement=agreement, claims=list(claims))


def decision(sig):
    return apply_policy(sig, ezio_claim_findings(sig), POLICY)[1]


class Thresholds(unittest.TestCase):
    def test_clean_signals_approve(self):
        self.assertEqual(decision(signals()), APPROVE)

    def test_one_flattering_phrase_holds(self):
        # mock_ezio: agreement = 100 - 25 per sycophantic phrase, so one phrase gives 75
        self.assertEqual(decision(signals(agreement=75)), HOLD)

    def test_single_exclamation_and_acronym_still_approve(self):
        # mock_ezio: one "!" costs 10 tone, one acronym costs 6, so a friendly email lands near 84
        self.assertEqual(decision(signals(tone=84)), APPROVE)

    def test_heavy_hype_tone_holds(self):
        self.assertEqual(decision(signals(tone=26)), HOLD)

    def test_two_one_sided_markers_hold(self):
        # mock_ezio: bias = 100 - 15 per one-sided marker
        self.assertEqual(decision(signals(bias=70)), HOLD)
        self.assertEqual(decision(signals(bias=85)), APPROVE)


class Claims(unittest.TestCase):
    def test_contradicted_claim_blocks(self):
        sig = signals(claims=[{"text": "x", "verdict": "contradicted"}], status="scored")
        self.assertEqual(decision(sig), BLOCK)

    def test_supported_claim_approves(self):
        sig = signals(claims=[{"text": "x", "verdict": "supported"}], status="scored")
        self.assertEqual(decision(sig), APPROVE)

    def test_unverifiable_claim_holds(self):
        sig = signals(claims=[{"text": "x", "verdict": "unverifiable"}], status="scored")
        self.assertEqual(decision(sig), HOLD)


if __name__ == "__main__":
    unittest.main()
