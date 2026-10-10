"""Tests for the per-signal checklist returned with every decision.

Run: cd wrapper && python3 -m unittest test_checks
"""
import unittest
from types import SimpleNamespace

from checks import build_checks
from wrapper import POLICY


def finding(level, signal, message="m"):
    return SimpleNamespace(level=level, signal=signal, message=message)


def signals(tone=100, bias=100, agreement=100, claims=(), tier="GREEN", score=99.0, status="not_scored"):
    return SimpleNamespace(tone=tone, bias=bias, agreement=agreement, claims=list(claims), tier=tier,
                           score=score, accuracy_status=status)


def statuses(rows):
    return {row["signal"]: row["status"] for row in rows}


class Checklist(unittest.TestCase):
    def test_clean_email_passes_every_row_and_laya_is_skipped(self):
        rows = build_checks([], signals(), POLICY, None)
        self.assertEqual(statuses(rows), {"data": "pass", "promise_tone": "pass", "ezio_claims": "pass",
                                          "ezio_dimensions": "pass", "ezio_tier": "pass", "laya": "skipped"})
        self.assertTrue(all(row["label"] and row["detail"] for row in rows))

    def test_rows_follow_their_signals(self):
        rows = build_checks([finding("BLOCK", "data", "Pro costs $49"), finding("HOLD_FOR_REVIEW", "promise"),
                             finding("BLOCK", "ezio_claim")],
                            signals(agreement=75, tier="RED", score=45),
                            POLICY, "Laya checked: promise 0.20")
        got = statuses(rows)
        self.assertEqual((got["data"], got["promise_tone"], got["ezio_claims"]), ("block", "hold", "block"))
        self.assertEqual((got["ezio_dimensions"], got["ezio_tier"], got["laya"]), ("hold", "block", "pass"))
        self.assertIn("Pro costs $49", {row["detail"] for row in rows})

    def test_ezio_failure_fails_closed(self):
        rows = build_checks([], None, POLICY, "Laya not run while Ezio is unavailable; skipped")
        got = statuses(rows)
        self.assertEqual((got["ezio_claims"], got["ezio_dimensions"], got["ezio_tier"], got["laya"]),
                         ("skipped", "skipped", "hold", "skipped"))


if __name__ == "__main__":
    unittest.main()
