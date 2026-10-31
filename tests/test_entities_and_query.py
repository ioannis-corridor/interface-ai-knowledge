from datetime import date

from ks.entities import extract_entities, extract_prose_facts
from ks.query import parse_rules
from ks.text import numbers_in, tokenize

RELEASE = """
2 min read

[Jane Doe](https://example-cu.test/newsroom/author/jane-doe) June 20, 2025

# Example CU plans Riverside branch closure

The Riverside branch will serve members through the end of the first quarter. This location will close March 31, 2026.

The Riverside Example CU branch is located at 100 Main St. Branch hours are:

**Lobby**

Monday-Thursday: 8:30 a.m.-5 p.m.

Friday: 8:30 a.m.-6 p.m.

Saturday: 8:30 a.m.-12:30 p.m.

Sunday: Closed

**Drive-up**

Monday-Friday: 8 a.m.-6 p.m.

Saturday: 9 a.m.-noon

ABOUT EXAMPLE CU: Membership has grown to more than 167,000 with assets exceeding $3.2 billion. It has nearly 700 employees and 22 branch office locations. It was the fifth time Forbes recognized Example CU. Our routing number is 123456789.
"""


def test_prose_entities():
    facts = extract_entities(RELEASE, "https://example-cu.test/newsroom/riverside", "Riverside closure", "01", 60,
                             date(2025, 6, 20), None)
    by = {(f.product, f.metric): f.value for f in facts}
    assert by[("branch count", "count")] == "22"
    assert by[("employee count", "count")] == "700"
    assert by[("Forbes recognition", "ordinal")] == "fifth"
    assert by[("routing number", "id")] == "123456789"
    assert by[("Riverside branch", "close_date")] == "March 31, 2026"       # not the article date
    assert by[("Riverside branch", "hours_lobby")].startswith("Monday-Thursday: 8:30 a.m.-5 p.m.; Friday")
    assert "9 a.m.-noon" in by[("Riverside branch", "hours_driveup")]
    assert by[("Riverside branch", "address")] == "100 Main St"


def test_prose_rate_and_fee_lines():
    md = "# Certificates\n\n6-month certificate APY: 2.95%\n\nLost debit card replacement fee: $2.50\n"
    facts = extract_prose_facts(md, "https://example-cu.test/rates/certificates", "Certificates", "01", 85, None, None)
    by = {(f.family, f.metric): f for f in facts}
    assert by[("certificate", "apy")].value == "2.95%" and by[("certificate", "apy")].term_months == 6
    assert by[("fee", "fee")].value == "$2.50" and by[("fee", "fee")].product == "Lost debit card replacement"


def test_expired_promo_sentence_has_low_authority():
    md = "Summer special: 6-month certificate APY 2.95% (offer ended 2025-09-30)"
    facts = extract_prose_facts(md, "https://example-cu.test/promo", "Promo", "02", 85, None, None)
    assert facts and all(f.authority <= 35 for f in facts)


def test_query_rates_and_qualifiers():
    q = parse_rules("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?")
    assert (q.intent, q.family, q.term_months, q.model_year, q.metric) == ("fact", "auto", 60, 2025, "apr")
    q = parse_rules("What dividend rate do I earn on Share Savings with a balance between $10,000 and $24,999?")
    assert (q.family, q.product, q.balance, q.metric) == ("savings", "Share Savings", 10000.0, "dividend_rate")
    q = parse_rules("How much interest does a five-year CD pay?")
    assert (q.family, q.term_months) == ("certificate", 60)
    q = parse_rules("jumbo 10 month special apy")
    assert (q.family, q.term_months, q.jumbo, q.special) == ("certificate", 10, True, True)


def test_query_intents():
    assert parse_rules("What link should I use to see your CD rates?").intent == "link"
    assert parse_rules("Has the 12-month certificate rate changed since May?").intent == "change"
    assert parse_rules("Is the Riverside branch still open today?").intent == "status"
    assert parse_rules("Do all branches keep the same lobby hours?").intent == "aggregate"
    assert parse_rules("What credit cards do you offer and what are their APRs?").intent == "list"
    assert parse_rules("Do any savings tiers pay 0.35% APY?").intent == "verify"
    assert parse_rules("What is the highest Share Savings APY?").intent == "superlative"
    assert parse_rules("How much is a lost debit card replacement?").intent == "fee"
    assert parse_rules("What's the minimum balance to earn the top Share Savings rate?").superlative == "max"


def test_query_entities_and_dates():
    q = parse_rules("Can you repeat the routing number?")
    assert q.entity == "routing"
    q = parse_rules("Can you give me the lobby hours for the Mullan Avenue branch?")
    assert (q.entity, q.branch) == ("hours_lobby", "Mullan Avenue")
    q = parse_rules("How many Example CU employees used Volunteer Time Off last year?")
    assert q.entity is None                                   # not a head-count question
    q = parse_rules("What was the rate on the 10-month jumbo special as of May 2026?")
    assert q.as_of_text == date(2026, 5, 31)
    q = parse_rules("What's the penalty for closing a new account early?")
    assert q.entity is None and q.intent == "fee"


def test_tokenizer_and_number_fingerprint():
    assert tokenize("Our CDs and car loans") == ["certificate", "auto", "loan"]
    assert numbers_in("5.39% APR and $1,000 minimum") == {("%", 5.39), ("$", 1000.0)}
