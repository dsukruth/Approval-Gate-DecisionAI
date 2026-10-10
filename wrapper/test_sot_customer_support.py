"""Unit tests for the customer_support source-of-truth checks.

Sentences here are written for the tests, not copied from the practice set.
Run: cd wrapper && python3 -m unittest test_sot_customer_support
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sot_customer_support as sot  # noqa: E402
from wrapper import load_source_of_truth  # noqa: E402

DATA = load_source_of_truth("customer_support")
BLOCK, HOLD = "BLOCK", "HOLD_FOR_REVIEW"


def levels(text, context=None):
    return {finding["level"] for finding in sot.check(text, context or {}, DATA)}


def findings(text, context=None):
    return sot.check(text, context or {}, DATA)


class NumberWords(unittest.TestCase):
    def test_words_to_digits(self):
        self.assertEqual(sot.normalize("forty-nine dollars"), "49 dollars")
        self.assertEqual(sot.normalize("ninety nine dollars"), "99 dollars")
        self.assertEqual(sot.normalize("fifteen percent off"), "15% off")


class Prices(unittest.TestCase):
    def test_correct_monthly_and_annual_prices(self):
        self.assertEqual(levels("Business costs $99 a month."), set())
        self.assertEqual(levels("Pro works out to $39.20/mo when billed yearly."), set())
        self.assertEqual(levels("Starter is nineteen dollars monthly."), set())

    def test_wrong_price_blocks(self):
        self.assertIn(BLOCK, levels("Pro is $45 per month."))
        self.assertIn(BLOCK, levels("Our Starter tier is twenty-nine dollars a month."))

    def test_rounded_annual_price_blocks(self):
        self.assertIn(BLOCK, levels("Pro costs $39 per month."))

    def test_enterprise_price_blocks(self):
        self.assertIn(BLOCK, levels("Enterprise is $499 per month."))

    def test_unknown_price_without_plan_holds(self):
        self.assertIn(HOLD, levels("That comes to $57 per month."))

    def test_context_plan_used_when_text_has_none(self):
        self.assertIn(BLOCK, levels("Your plan is $19 per month.", {"plan": "Business"}))
        self.assertEqual(levels("Your plan is $99 per month.", {"plan": "Business"}), set())


class Discounts(unittest.TestCase):
    def test_correct_discounts(self):
        self.assertEqual(levels("Paying yearly saves you 20%."), set())
        self.assertEqual(levels("You get 15% off as a loyal customer.", {"plan": "Business", "customer_tenure_months": 13}), set())

    def test_wrong_percent_blocks(self):
        self.assertIn(BLOCK, levels("The loyalty discount is 25%."))
        self.assertIn(BLOCK, levels("Switch to annual billing for 10% off."))

    def test_stacking_blocks(self):
        self.assertIn(BLOCK, levels("Stack the loyalty and annual discounts together."))
        self.assertIn(BLOCK, levels("With both discounts you pay 35% less."))

    def test_loyalty_eligibility(self):
        self.assertIn(BLOCK, levels("You qualify for the loyalty discount.", {"plan": "Pro", "customer_tenure_months": 4}))
        self.assertIn(BLOCK, levels("You qualify for the loyalty discount.", {"plan": "Starter", "customer_tenure_months": 40}))
        self.assertEqual(levels("You qualify for the loyalty discount.", {"plan": "Pro", "customer_tenure_months": 12}), set())


class Refunds(unittest.TestCase):
    def test_correct_refund_windows(self):
        self.assertEqual(levels("Annual plans can be refunded within 14 days."), set())
        self.assertEqual(levels("Monthly subscribers have a 30-day refund window."), set())

    def test_wrong_refund_blocks(self):
        self.assertIn(BLOCK, levels("Annual plans are refundable within 30 days."))
        self.assertIn(BLOCK, levels("We offer a 60 day money-back refund."))
        self.assertIn(BLOCK, levels("It's a full refund at any time."))


class TrialAndResponse(unittest.TestCase):
    def test_trial(self):
        self.assertEqual(levels("Pro comes with a 14-day free trial, no credit card needed."), set())
        self.assertIn(BLOCK, levels("Try Business free for 30 days."))
        self.assertIn(BLOCK, levels("Starter includes a 14-day free trial."))

    def test_response_time(self):
        self.assertEqual(levels("Starter customers hear back within 48 hours."), set())
        self.assertIn(BLOCK, levels("Pro tickets get a first reply within 4 hours."))
        self.assertIn(BLOCK, levels("Business is $99 a month and we respond within one day."))

    def test_multi_claim_sentence(self):
        self.assertIn(BLOCK, levels("Starter is $19 and Pro is $59 per month."))


class PromisesAndTone(unittest.TestCase):
    def test_no_claims_passes(self):
        self.assertEqual(levels("Thanks for writing in, I will get back to you by Friday."), set())

    def test_feature_promise_holds(self):
        self.assertIn(HOLD, levels("We will build the Salesforce integration for you by March."))
        self.assertIn(HOLD, levels("I can make an exception and waive the fee this time."))

    def test_hype_holds(self):
        self.assertIn(HOLD, levels("This is INCREDIBLE value, you'll never regret it!!!"))
        self.assertIn(HOLD, levels("Results are guaranteed."))

    def test_acronyms_are_not_hype(self):
        self.assertEqual(levels("Your GDPR request is logged."), set())


class MockAlignment(unittest.TestCase):
    """Cases found by reading mock_ezio.py: legal fines, negations, broader promises, flattery."""

    def test_large_public_figures_are_not_plan_prices(self):
        self.assertEqual(levels("Under CAN-SPAM, each violation can cost up to $53,088.", {"plan": "Pro"}), set())

    def test_negated_guarantee_and_exception_pass(self):
        self.assertEqual(levels("We can't guarantee a delivery date for that request."), set())
        self.assertEqual(levels("I\u2019m unable to make an exception, but annual billing saves 20%."), set())

    def test_broader_feature_promises_hold(self):
        self.assertIn(HOLD, levels("We will add dark mode to the dashboard by the end of the quarter."))
        self.assertIn(HOLD, levels("The bulk export feature will ship next month."))
        self.assertIn(HOLD, levels("Just this once, I'll extend your trial by another week."))

    def test_custom_quote_from_sales_passes(self):
        self.assertEqual(levels("You can request a custom quote from our sales team."), set())

    def test_flattery_holds(self):
        self.assertIn(HOLD, levels("Great question! The Pro plan is $49 per month."))

    def test_single_capitalised_word_without_exclamation_passes(self):
        self.assertEqual(levels("Please NOTE the new invoice date."), set())

    def test_milder_hype_words_hold(self):
        self.assertIn(HOLD, levels("Business is the greatest plan we have ever made."))


class GeneralisationGaps(unittest.TestCase):
    """Phrasings found missing by an independent eval; tests use different sentences than that eval."""

    def test_feature_with_a_date_holds_without_commit_word(self):
        self.assertIn(HOLD, levels("The new audit log feature launches next week, so it's ready for your rollout."))

    def test_third_party_contractions_commit(self):
        self.assertIn(HOLD, levels("They'll add SSO support to your workspace."))

    def test_fix_with_a_date_holds(self):
        self.assertIn(HOLD, levels("Our developers will get the login bug patched by tomorrow."))

    def test_fix_without_a_date_passes(self):
        self.assertEqual(levels("We fixed the duplicate charge yesterday."), set())
        self.assertEqual(levels("I will fix the billing address on your invoice."), set())

    def test_refund_scope_and_open_ended_block(self):
        self.assertIn(BLOCK, levels("You can get a refund on all of your past payments."))
        self.assertIn(BLOCK, levels("Refunds have no time limit."))

    def test_correct_refund_scope_passes(self):
        self.assertEqual(levels("Refunds apply to your first payment, not every renewal."), set())


class StructuredFindings(unittest.TestCase):
    """Each finding says which signal raised it, where, what was found, what the data expects, and a fix."""

    def test_price_finding_has_location_values_and_fix(self):
        (f,) = findings("Thanks for asking. Our Business plan is $89 per month.")
        self.assertEqual((f["signal"], f["sentence"], f["source"]), ("data", 1, "price_sheet.csv"))
        self.assertEqual((f["found"], f["expected"]), ("$89", "$99"))
        self.assertEqual(f["fix"], {"sentence": 1, "find": "$89", "replace": "$99"})
        self.assertEqual(f["quote"], "Our Business plan is $89 per month.")

    def test_annual_price_expectation(self):
        (f,) = findings("Billed annually, Pro works out to $35 per month.")
        self.assertEqual(f["expected"], "$39.20")

    def test_percent_and_hours_fixes(self):
        (f,) = findings("The loyalty discount is 25%.")
        self.assertEqual(f["fix"], {"sentence": 0, "find": "25%", "replace": "15%"})
        (g,) = findings("Starter customers get a first response within 12 hours.")
        self.assertEqual((g["found"], g["expected"]), ("12 hours", "48 hours"))

    def test_no_fix_when_value_was_written_in_words(self):
        (f,) = findings("Pro is forty-five dollars a month.")
        self.assertEqual(f["expected"], "49 dollars")
        self.assertIsNone(f["fix"])

    def test_promise_and_tone_signals_have_no_fix(self):
        (f,) = findings("We will build that integration for you.")
        self.assertEqual((f["signal"], f["fix"]), ("promise", None))
        (g,) = findings("Results are guaranteed.")
        self.assertEqual(g["signal"], "tone")


class RoundTwoGaps(unittest.TestCase):
    """Gaps found by a second independent eval; sentences here are written separately from it."""

    def test_more_money_and_duration_formats(self):
        self.assertIn(BLOCK, levels("Starter costs USD 25 a month."))
        self.assertIn(BLOCK, levels("Business customers hear back within half a day."))
        self.assertEqual(levels("Starter tickets are answered within two days."), set())

    def test_yearly_totals_follow_the_billing_period(self):
        self.assertIn(BLOCK, levels("Paying annually for Starter comes to $228 a year."))
        self.assertEqual(levels("Billed annually, Starter comes to $182.40 a year."), set())
        self.assertEqual(levels("Pro is $49 a month, or $39.20 a month billed annually."), set())

    def test_fraction_discounts(self):
        self.assertIn(BLOCK, levels("Annual billing knocks a third off the Pro price."))

    def test_card_required_wording(self):
        self.assertIn(BLOCK, levels("The Business trial needs a credit card up front."))
        self.assertEqual(levels("The Pro trial needs no card."), set())

    def test_denying_an_ineligible_discount_passes(self):
        ctx = {"plan": "Pro", "customer_tenure_months": 5}
        self.assertEqual(levels("Since you joined five months ago, the loyalty discount isn't available to you yet.", ctx), set())

    def test_declining_to_promise_passes(self):
        self.assertEqual(levels("I can't promise the integration will be built, but I've shared your idea with the team."), set())

    def test_more_promise_and_exception_wording_holds(self):
        self.assertIn(HOLD, levels("Dark mode will be made available to Business workspaces before the end of the quarter."))
        self.assertIn(HOLD, levels("As a goodwill gesture, I've credited your account with a free month."))

    def test_open_flattery_superlatives_and_absolutes_hold(self):
        self.assertIn(HOLD, levels("You are one of the most insightful customers we have."))
        self.assertIn(HOLD, levels("Lumen Cloud is the best platform in the world for teams like yours."))
        self.assertIn(HOLD, levels("Rest assured, you will never lose data with us."))
        self.assertIn(HOLD, levels("Your team will have everything it could ever need."))

    def test_ordinary_future_statements_pass(self):
        self.assertEqual(levels("Your invoice will be available in the billing tab by tomorrow."), set())


class RoundTwoFalseBlocks(unittest.TestCase):
    def test_contracted_negation_of_card(self):
        self.assertEqual(levels("Starting the Pro trial won't require a card."), set())

    def test_lowercase_plan_nouns_and_preceding_plan_wins(self):
        self.assertEqual(levels("Pro accounts get a reply within a day, and Starter tickets within two days."), set())
        self.assertEqual(levels("Business gets a four-hour first response and pro users hear back within 24 hours."), set())

    def test_billing_period_is_read_next_to_each_amount(self):
        self.assertEqual(levels("Pro billed monthly comes to $588 a year, or $470.40 a year on annual billing."), set())
        self.assertIn(BLOCK, levels("On annual billing, Pro comes to $588 a year."))

    def test_one_time_courtesy_holds(self):
        self.assertIn(HOLD, levels("Happy to refund you as a one-time courtesy."))


if __name__ == "__main__":
    unittest.main()
