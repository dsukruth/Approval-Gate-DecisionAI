"""Source-of-truth checks for the customer_support persona (Lumen Cloud).

Every rule reads its expected values from price_sheet.csv and policies.json, so the
checks follow the data rather than any particular wording. Pure functions only.

check(text, context, sot) -> list of finding dicts: level (BLOCK or HOLD_FOR_REVIEW), message, signal
(data, promise or tone), source file, found and expected values, sentence index, quote and an optional fix.
"""
import re

BLOCK, HOLD = "BLOCK", "HOLD_FOR_REVIEW"
PRICE_TOLERANCE = 0.005
CAPS_ACRONYMS = {"GDPR", "CCPA", "HIPAA", "ASAP", "FAQS", "USD", "SAML", "HTTPS"}

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90}
_SMALL = "|".join(sorted(UNITS, key=len, reverse=True))
_TENS = "|".join(TENS)
NUMBER_WORDS = re.compile(rf"\b(?:({_TENS})(?:[\s-]({_SMALL}))?|({_SMALL}))\b", re.I)

PLAN_RE = re.compile(r"\b(Starter|Pro|Business|Enterprise)\b(?![\s-]+(?:days?|hours?)\b)|"
                     r"\b(starter|pro|business|enterprise)(?=\s+(?:plans?|tiers?|accounts?|customers?|users?|subscribers?|package|workspaces?|teams?)\b)")
_AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MONEY_RE = re.compile(rf"\$\s?({_AMOUNT})|\b(?:usd|us\$)\s?({_AMOUNT})|\b({_AMOUNT})\s*(?:dollars|usd|bucks)\b", re.I)
PRICE_WORDS = re.compile(r"\b(per month|a month|each month|monthly|per year|a year|yearly|annually|plan|subscription|renews?|renewal)\b|/\s?(?:mo|month|yr|year)\b", re.I)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
DURATION_RE = re.compile(r"\b(\d+)[\s-]*(business[\s-]+days?|hours?|hrs?|days?|weeks?|months?|years?)\b", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")

DISCOUNT_WORDS = re.compile(r"\b(discounts?|off|save[sd]?|savings|less|cheaper)\b", re.I)
STACK_WORDS = re.compile(r"\b(combine[sd]?|combining|stack(?:ed|ing)?|together|on top of|both discounts|plus the)\b", re.I)
LOYALTY_WORDS = re.compile(r"\bloyal(?:ty)?\b", re.I)
ANNUAL_WORDS = re.compile(r"\b(annual(?:ly)?|yearly|per year|billed (?:yearly|annually))\b", re.I)
MONTHLY_WORDS = re.compile(r"\bmonthly\b", re.I)
ANNUAL_BILLING = re.compile(r"\b(annual(?:ly)?|yearly|billed (?:yearly|annually))\b", re.I)
REFUND_WORDS = re.compile(r"\b(refunds?|refunded|refundable|money[\s-]back)\b", re.I)
OPEN_ENDED_REFUND = re.compile(r"\b(any ?time|whenever|first year|full year|lifetime|forever|no matter (?:when|how long)|"
                               r"no time limit|without (?:a |any )?time limit|unlimited|indefinitely|at any point)\b", re.I)
REFUND_SCOPE = re.compile(r"\b(?:every|all|any|each) (?:of (?:your|the) )?(?:past |previous )?(?:payments?|charges?|invoices?|renewals?)\b|"
                          r"\bpast (?:payments|charges|invoices)\b", re.I)
TRIAL_WORDS = re.compile(r"\b(trial|free for|try \w+ (?:for )?free)\b", re.I)
CARD_REQUIRED = re.compile(r"\b(card|credit card)\b[^.]*\b(required|needed)\b|\brequires? a (?:credit )?card\b|"
                           r"\b(?:need|needs|require|requires|ask for|asks for)\b[^.]{0,25}\b(?:credit |debit )?card\b|\bcard on file\b", re.I)
NEGATION = re.compile(r"\b(no|not|without|never|won't|don't|doesn't|isn't|aren't|can't|cannot)\b", re.I)
RESPONSE_WORDS = re.compile(r"\b(respond|responds|response|reply|replies|hear back|get back|first answer|sla)\b", re.I)
SLA_WORDS = re.compile(r"\b(first response|first reply|response time|sla)\b", re.I)
COMMIT_WORDS = re.compile(r"\b(\w+'ll|i will|we will|will|i can|we can|i'm going to|we're going to|going to|"
                          r"make sure|promise[sd]?|ensure|commit(?:ted)? to)\b", re.I)
PROMISE_OBJECTS = re.compile(r"\b(ship|ships|shipping|shipped|build|built|release[sd]?|develop|implement|deliver|delivered|"
                             r"launch|launches|roll(?:s|ed)? out|rollout|go live|add|adding|roadmap|features?|integrations?|"
                             r"functionality|exception|waive[sd]?|override|extend(?:ed)? (?:your|the) (?:trial|refund|deadline)|"
                             r"extra (?:discount|month|months|days|week)|free (?:month|months|upgrade|extension)|"
                             r"special (?:deal|price|pricing|discount)|free of charge|made available|roll(?:ing)? out to|coming to)\b", re.I)
STRONG_PROMISE = re.compile(r"\b(i promise|we promise|i guarantee|we guarantee|i can assure you|i assure you|"
                            r"you can count on|you have my word)\b", re.I)
DELIVERY_STATES = re.compile(r"\b(ready|live|done|finished|complete|completed|in place|up and running)\b", re.I)
FIX_OBJECTS = re.compile(r"\b(fix|fixed|patch|patched|deploy|deployed|resolve[sd]?)\b", re.I)
WHEN_PHRASES = re.compile(r"\b(?:by|before|until) (?:this |next |the )?(?:end of (?:the |this |next )?(?:day|week|month|quarter|year|sprint)|"
                          r"eod|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|q[1-4]|january|february|"
                          r"march|april|june|july|august|september|october|november|december)\b|"
                          r"\bnext (?:week|month|quarter|year|release|sprint|update)\b|\bthis (?:week|month|quarter|year)\b|"
                          r"\blater this (?:week|month|year)\b|\bin the next (?:release|update|version|few (?:days|weeks))\b", re.I)
EXCEPTION_PHRASES = re.compile(r"\b(make an exception|waive[sd]?|just this once|on the house|bend the rules|goodwill|"
                               r"as a (?:(?:one|1)-time |special )?courtesy|courtesy (?:refund|credit)|(?:one|1)-time (?:exception|courtesy|credit)|"
                               r"outside (?:of )?(?:the |our )?policy)\b", re.I)
DENIAL = re.compile(r"\b(isn't|is not|aren't|are not|not (?:yet )?(?:available|eligible)|ineligible|doesn't|does not|"
                    r"don't|do not|not yet|won't|unfortunately)\b", re.I)
NO_PROMISE = re.compile(r"\b(?:can't|cannot|can not|unable to|not able to|won't) (?:promise|guarantee|commit)\b|\bno promises\b", re.I)
NEGATORS = re.compile(r"\b(not|never|no|can't|cannot|can not|won't|wouldn't|don't|do not|unable to|not able to)\b", re.I)
HYPE_WORDS = re.compile(r"\b(guarantee[sd]?|amazing|incredible|unbelievable|greatest|revolutionary|you(?:'ll| will) love|"
                        r"never regret|best (?:deal|value|plan) ever|once in a lifetime|act now|life[\s-]changing|"
                        r"(?:best|finest|greatest|top|leading|number one) [\w\s-]{0,30}\b(?:in the world|on the market|anywhere|out there)|"
                        r"(?:will|'ll) never (?:have|experience|see|lose|happen|go down|fail)|zero downtime|100% uptime|"
                        r"assure you|ever (?:need|want)|never (?:want|need) (?:to look at )?another)\b", re.I)
FLATTERY = re.compile(r"\b(great question|what a great|(?:you're|you are) (?:absolutely|so|totally) right|"
                      r"excellent point|good point|brilliant question|"
                      r"you(?:'re| are| have)\b[^.]{0,40}\b(?:sharpest|smartest|brightest|most (?:insightful|thoughtful|perceptive)|"
                      r"rare eye|brilliant|genius)|(?:wonderfully|incredibly|remarkably|truly) (?:perceptive|insightful|thoughtful|sharp)|"
                      r"(?:what|such) an? (?:wonderful|brilliant|perceptive|insightful|thoughtful|excellent) (?:note|question|point|observation|idea))\b", re.I)


def _word_number(match):
    tens, unit_after_tens, unit = match.groups()
    if tens:
        return str(TENS[tens.lower()] + (UNITS[unit_after_tens.lower()] if unit_after_tens else 0))
    return str(UNITS[unit.lower()])


PHRASES = [
    (re.compile(r"\bhalf an? day\b", re.I), "12 hours"),
    (re.compile(r"\ba fortnight\b", re.I), "14 days"),
    (re.compile(r"\b(within|in|inside|under|after|for) (?:a|1) (?:full |whole |single )?(business )?day\b", re.I), r"\1 1 \2day"),
    (re.compile(r"\b(within|in|inside|under|after|for) an? (week|hour)\b", re.I), r"\1 1 \2"),
    (re.compile(r"\b(?:a|1) quarter\b(?=\s+(?:off|less|cheaper|discount))", re.I), "25%"),
    (re.compile(r"\b(?:a|1) fifth\b(?=\s+(?:off|less|cheaper|discount))", re.I), "20%"),
    (re.compile(r"\b(?:a|1) third\b(?=\s+(?:off|less|cheaper|discount))", re.I), "33%"),
    (re.compile(r"\b(?:a|1) tenth\b(?=\s+(?:off|less|cheaper|discount))", re.I), "10%"),
    (re.compile(r"\bhalf\b(?=\s+(?:off|price))", re.I), "50%"),
]


def normalize(text):
    """Straighten quotes, spell out number words as digits, word phrases ('half a day') as numbers, 'percent' as '%'."""
    straight = text.replace("\u2019", "'").replace("\u2018", "'")
    digits = NUMBER_WORDS.sub(_word_number, straight)
    for pattern, replacement in PHRASES:
        digits = pattern.sub(replacement, digits)
    return re.sub(r"(\d)\s*(?:percent|per cent)\b", r"\1%", digits, flags=re.I)


def _finding(level, message, signal="data", source=None, found=None, expected=None):
    return {"level": level, "message": message, "signal": signal, "source": source, "found": found, "expected": expected}


def _money(found, value):
    """Format the expected amount in the same style the email used ('$99' or '99 dollars')."""
    if found.lstrip().startswith("$"):
        return f"${value}"
    return f"USD {value}" if found.lstrip().upper().startswith("USD") else f"{value} dollars"


def load_tables(sot):
    plans = {row["plan"]: row for row in sot["price_sheet"]}
    return plans, sot["policies"]


def _plan_mentions(sentence):
    return [(m.start(), (m.group(1) or m.group(2)).capitalize()) for m in PLAN_RE.finditer(sentence)]


def _nearest_plan(position, mentions, context_plan):
    """The plan named closest before the value ('Business is $99'), else the closest after ('$99 for Business')."""
    before = [m for m in mentions if m[0] <= position]
    if before:
        return max(before, key=lambda mention: mention[0])[1]
    if mentions:
        return min(mentions, key=lambda mention: mention[0])[1]
    return context_plan


BILLING_WORDS = re.compile(r"\b(monthly|month to month|annual(?:ly)?|yearly|billed (?:yearly|annually))\b", re.I)


def _annual_billing_near(sentence, start, end):
    """Billing period named closest to an amount, so 'monthly ... $588 a year, annual ... $470.40' reads per amount."""
    near = [m for m in BILLING_WORDS.finditer(sentence) if abs(m.start() - start) <= 60 or abs(m.start() - end) <= 60]
    if not near:
        return False
    closest = min(near, key=lambda m: min(abs(m.start() - start), abs(m.start() - end)))
    return not closest.group(0).lower().startswith("month")


def _context_plan(context, plans):
    plan = str(context.get("plan", "")).capitalize()
    return plan if plan in plans or plan == "Enterprise" else None


def _duration_hours(amount, unit):
    unit = unit.lower()
    if unit.startswith(("hour", "hr")):
        return amount
    if "day" in unit:
        return amount * 24
    return None


def _negated(sentence, match):
    """True when a negator sits just before the match or right after it ('will not ship')."""
    before = sentence[max(0, match.start() - 24):match.start()]
    after = sentence[match.end():match.end() + 6]
    return bool(NEGATORS.search(before) or re.match(r"\s*(not|n't)\b", after, re.I))


def check_prices(sentence, mentions, context_plan, plans):
    findings = []
    is_price_talk = bool(PRICE_WORDS.search(sentence))
    for m in MONEY_RE.finditer(sentence):
        amount = float(next(g for g in m.groups() if g).replace(",", ""))
        if not (mentions or is_price_talk):
            continue  # a dollar figure that is not about a plan (a fine, a credit) is outside our data
        plan = _nearest_plan(m.start(), mentions, context_plan if is_price_talk else None)
        if plan == "Enterprise":
            findings.append(_finding(BLOCK, f"Enterprise pricing is custom via sales (policies.json); the email quotes ${amount:g}.",
                                     source="policies.json", found=m.group(0).strip()))
            continue
        rows = [plans[plan]] if plan in plans else list(plans.values())
        annual_billing = _annual_billing_near(sentence, m.start(), m.end())
        valid = {v for r in rows for v in (float(r["monthly_price_usd"]), float(r["annual_price_per_month_usd"]),
                                           float(r["annual_price_per_month_usd"]) * 12)}
        if not annual_billing:  # 12 x the monthly price is only a valid yearly total on monthly billing
            valid |= {float(r["monthly_price_usd"]) * 12 for r in rows}
        if any(abs(amount - v) < PRICE_TOLERANCE for v in valid):
            continue
        found = m.group(0).strip()
        if plan in plans:
            row = plans[plan]
            column = "annual_price_per_month_usd" if annual_billing else "monthly_price_usd"
            findings.append(_finding(BLOCK, f"{plan} costs ${row['monthly_price_usd']}/mo monthly or ${row['annual_price_per_month_usd']}/mo "
                                            f"billed annually (price_sheet.csv); the email says ${amount:g}.",
                                     source="price_sheet.csv", found=found, expected=_money(found, row[column])))
        else:
            findings.append(_finding(HOLD, f"${amount:g} matches no price on price_sheet.csv and no plan is named.",
                                     source="price_sheet.csv", found=found))
    return findings


def check_discounts(sentence, context, policies):
    discounts = policies["discounts"]
    loyalty, annual = discounts["loyalty"], discounts["annual_billing"]
    findings = []
    is_discount = DISCOUNT_WORDS.search(sentence) or LOYALTY_WORDS.search(sentence)
    if not is_discount:
        return findings
    stacked = loyalty["percent"] + annual["percent"]
    if STACK_WORDS.search(sentence) and re.search(r"\bdiscounts?\b", sentence, re.I) and not discounts["stacking_allowed"]:
        findings.append(_finding(BLOCK, "Discounts cannot be stacked (policies.json: stacking_allowed=false).", source="policies.json"))
    is_loyalty, is_annual = bool(LOYALTY_WORDS.search(sentence)), bool(ANNUAL_WORDS.search(sentence))
    for m in PERCENT_RE.finditer(sentence):
        pct, found = float(m.group(1)), m.group(0)
        if pct == stacked and not discounts["stacking_allowed"]:
            findings.append(_finding(BLOCK, f"{pct:g}% equals loyalty + annual stacked; discounts cannot be combined (policies.json).",
                                     source="policies.json", found=found))
        elif is_loyalty and not is_annual and pct != loyalty["percent"]:
            findings.append(_finding(BLOCK, f"Loyalty discount is {loyalty['percent']}% (policies.json); the email says {pct:g}%.",
                                     source="policies.json", found=found, expected=f"{loyalty['percent']}%"))
        elif is_annual and not is_loyalty and pct != annual["percent"]:
            findings.append(_finding(BLOCK, f"Annual billing discount is {annual['percent']}% (policies.json); the email says {pct:g}%.",
                                     source="policies.json", found=found, expected=f"{annual['percent']}%"))
        elif pct not in (loyalty["percent"], annual["percent"]):
            findings.append(_finding(BLOCK, f"{pct:g}% matches no discount in policies.json (loyalty {loyalty['percent']}%, annual {annual['percent']}%).",
                                     source="policies.json", found=found))
    if is_loyalty and re.search(r"\b(you|your)\b", sentence, re.I) and not DENIAL.search(sentence):
        findings.extend(_loyalty_eligibility(context, loyalty))
    return findings


def _loyalty_eligibility(context, loyalty):
    plan, tenure = context.get("plan"), context.get("customer_tenure_months")
    findings = []
    if plan and str(plan).capitalize() not in loyalty["applies_to"]:
        findings.append(_finding(BLOCK, f"Loyalty discount applies to {', '.join(loyalty['applies_to'])} only; customer is on {plan}.",
                                 source="policies.json"))
    if isinstance(tenure, (int, float)) and tenure < loyalty["min_tenure_months"]:
        findings.append(_finding(BLOCK, f"Loyalty discount needs {loyalty['min_tenure_months']}+ months tenure; customer has {tenure:g}.",
                                 source="policies.json"))
    return findings


def check_refunds(sentence, policies):
    refunds = policies["refunds"]
    monthly_days, annual_days = refunds["monthly_plans_days"], refunds["annual_plans_days"]
    window = f"refunds within {monthly_days} days for monthly plans, {annual_days} days for annual (policies.json)"
    findings = []
    if OPEN_ENDED_REFUND.search(sentence):
        findings.append(_finding(BLOCK, f"Open-ended refund promised; policy {window}.", source="policies.json"))
    scope = next((m for m in REFUND_SCOPE.finditer(sentence) if not _negated(sentence, m)), None)
    if scope:
        findings.append(_finding(BLOCK, f"Refunds cover the {refunds['scope']} only (policies.json); the email offers '{scope.group(0)}'.",
                                 source="policies.json", found=scope.group(0)))
    is_annual, is_monthly = bool(ANNUAL_WORDS.search(sentence)), bool(MONTHLY_WORDS.search(sentence))
    allowed = {annual_days} if is_annual and not is_monthly else {monthly_days} if is_monthly and not is_annual else {monthly_days, annual_days}
    for m in DURATION_RE.finditer(sentence):
        amount, unit = int(m.group(1)), m.group(2).lower()
        days = amount if "day" in unit else amount * 7 if unit.startswith("week") else None
        if days not in allowed:
            expected = f"{next(iter(allowed))} days" if len(allowed) == 1 else None
            findings.append(_finding(BLOCK, f"Email says {amount} {unit}; policy {window}.",
                                     source="policies.json", found=m.group(0), expected=expected))
    return findings


def check_trial(sentence, mentions, plans, policies):
    trial = policies["free_trial"]
    findings = []
    for m in DURATION_RE.finditer(sentence):
        amount, unit = int(m.group(1)), m.group(2).lower()
        days = amount if "day" in unit else amount * 7 if unit.startswith("week") else amount * 30 if unit.startswith("month") else None
        if days != trial["days"]:
            findings.append(_finding(BLOCK, f"Free trial is {trial['days']} days (policies.json); the email says {amount} {unit}.",
                                     source="policies.json", found=m.group(0), expected=f"{trial['days']} days"))
    for _, plan in mentions:
        if plan not in trial["plans"]:
            findings.append(_finding(BLOCK, f"Free trial is only on {', '.join(trial['plans'])} (policies.json); the email offers it on {plan}.",
                                     source="policies.json", found=plan))
    if not trial["card_required"] and CARD_REQUIRED.search(sentence) and not NEGATION.search(sentence):
        findings.append(_finding(BLOCK, "Free trial needs no card (policies.json); the email says a card is required.", source="policies.json"))
    return findings


def check_response_time(sentence, mentions, context_plan, plans):
    if not (mentions or SLA_WORDS.search(sentence)):
        return []
    findings = []
    for m in DURATION_RE.finditer(sentence):
        hours = _duration_hours(int(m.group(1)), m.group(2))
        if hours is None:
            continue
        plan = _nearest_plan(m.start(), mentions, context_plan)
        if plan in plans:
            expected = float(plans[plan]["first_response_hours"])
            if hours != expected:
                findings.append(_finding(BLOCK, f"{plan} first response is {expected:g} hours (price_sheet.csv); the email says {m.group(0)}.",
                                         source="price_sheet.csv", found=m.group(0), expected=f"{expected:g} hours"))
        elif hours not in {float(r["first_response_hours"]) for r in plans.values()}:
            findings.append(_finding(HOLD, f"Response time '{m.group(0)}' matches no plan on price_sheet.csv.",
                                     source="price_sheet.csv", found=m.group(0)))
    return findings


def check_commitments(sentence):
    declined = bool(NO_PROMISE.search(sentence))  # "I can't promise X will ship" is the right answer, not a promise
    commits = [] if declined else [m for m in COMMIT_WORDS.finditer(sentence) if not _negated(sentence, m)]
    exceptions = [m for m in EXCEPTION_PHRASES.finditer(sentence) if not _negated(sentence, m)]
    dated = bool(WHEN_PHRASES.search(sentence))
    feature_promise = PROMISE_OBJECTS.search(sentence) and (commits or (dated and not declined))
    fix_by_date = FIX_OBJECTS.search(sentence) and dated
    delivery_by_date = DELIVERY_STATES.search(sentence) and dated and not declined
    explicit = any(not _negated(sentence, m) for m in STRONG_PROMISE.finditer(sentence)) and not declined
    if feature_promise or fix_by_date or delivery_by_date or explicit or exceptions:
        return [_finding(HOLD, "Agent promises a feature, delivery or exception (policies.json: can_promise_product_features=false); needs a manager.",
                         signal="promise", source="policies.json")]
    return []


def check_tone(sentence):
    findings = []
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", sentence) if w not in CAPS_ACRONYMS]
    shouting = len(caps) >= 2 or (caps and "!" in sentence)
    if re.search(r"!{2,}", sentence) or shouting:
        findings.append(_finding(HOLD, f"Over-the-top style ({'shouting ' + ', '.join(caps) if shouting else 'repeated exclamation marks'}).",
                                 signal="tone"))
    hype = next((m for m in HYPE_WORDS.finditer(sentence) if not _negated(sentence, m)), None)
    if hype:
        findings.append(_finding(HOLD, f"Hype or guarantee language ('{hype.group(0)}') needs review.", signal="tone", found=hype.group(0)))
    flattery = FLATTERY.search(sentence)
    if flattery:
        findings.append(_finding(HOLD, f"Flattery or agreeing with the customer ('{flattery.group(0)}') needs review.",
                                 signal="tone", found=flattery.group(0)))
    return findings


def check_sentence(sentence, context, plans, policies):
    mentions = _plan_mentions(sentence)
    context_plan = _context_plan(context, plans)
    findings = check_prices(sentence, mentions, context_plan, plans) + check_discounts(sentence, context, policies)
    if TRIAL_WORDS.search(sentence):
        findings += check_trial(sentence, mentions, plans, policies)
    elif REFUND_WORDS.search(sentence):
        findings += check_refunds(sentence, policies)
    elif RESPONSE_WORDS.search(sentence) or SLA_WORDS.search(sentence):
        findings += check_response_time(sentence, mentions, context_plan, plans)
    return findings + check_commitments(sentence) + check_tone(sentence)


def _locate(finding, index, original):
    """Attach where the finding came from, and a fix only when the wrong value appears verbatim in the email."""
    found, expected = finding["found"], finding["expected"]
    fix = {"sentence": index, "find": found, "replace": expected} if found and expected and found in original else None
    return {**finding, "sentence": index, "quote": original.strip(), "fix": fix}


def check(text, context, sot):
    plans, policies = load_tables(sot)
    context = context if isinstance(context, dict) else {}
    originals = [s for s in SENTENCE_RE.split(text) if s.strip()]
    located, seen = [], set()
    for index, original in enumerate(originals):
        for finding in check_sentence(normalize(original), context, plans, policies):
            key = (finding["level"], finding["message"])
            if key not in seen:
                seen.add(key)
                located.append(_locate(finding, index, original))
    return located
