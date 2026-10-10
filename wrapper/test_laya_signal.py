"""Tests for the optional Laya signal with a fake router (no model or torch needed).

Run: cd wrapper && python3 -m unittest test_laya_signal
"""
import threading
import time
import unittest

import laya_signal

POLICY = {"laya": {"model": "english", "hold_above": 0.8, "load_wait_seconds": 0}}


class FakeRouter:
    def __init__(self, promise, hype):
        self.answers = {"promise": {"noul": promise}, "hype": {"noul": hype}}

    def predict(self, state, questions, model=None):
        return {"answers": self.answers}


class BrokenRouter:
    def predict(self, state, questions, model=None):
        raise RuntimeError("device lost")


class Assess(unittest.TestCase):
    def test_low_probabilities_add_nothing(self):
        findings, note = laya_signal.assess("Thanks!", POLICY, FakeRouter(0.1, 0.2))
        self.assertEqual(findings, [])
        self.assertIn("promise 0.10", note)

    def test_high_probability_only_holds(self):
        findings, _ = laya_signal.assess("We'll ship it Friday.", POLICY, FakeRouter(0.93, 0.1))
        self.assertEqual([level for level, _ in findings], ["HOLD_FOR_REVIEW"])

    def test_errors_are_skipped(self):
        findings, note = laya_signal.assess("x", POLICY, BrokenRouter())
        self.assertEqual(findings, [])
        self.assertIn("skipped", note)

    def test_disabled_without_env(self):
        self.assertEqual(laya_signal.assess("x", POLICY), ([], None))


class ConcurrencyRouter:
    """Records the most predictions running at once (the GPU backend crashes on overlapping calls)."""

    def __init__(self):
        self.active, self.peak, self.lock = 0, 0, threading.Lock()

    def predict(self, state, questions, model=None):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return {"answers": {"promise": {"noul": 0.1}}}


class Concurrency(unittest.TestCase):
    def test_predictions_never_overlap(self):
        router = ConcurrencyRouter()
        threads = [threading.Thread(target=laya_signal.assess, args=("x", POLICY, router)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(router.peak, 1)


if __name__ == "__main__":
    unittest.main()
