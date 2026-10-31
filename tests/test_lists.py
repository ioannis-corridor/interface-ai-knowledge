"""List answers: all cards (personal + business), all certificates, and mortgage tiers with rate and APR."""
import contract

from ks.system import KnowledgeSystem
from ks.text import numbers_in

RATES = """# Rates | Example CU
Special Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 17 Month Fixed Jumbo Certificate Special | 4.15% | 4.20%1 | $100,000.00 |
| 17 Month Fixed Certificate Special | 4.06% | 4.10%2 | $1,000.00 |

Regular Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 12 Month | 3.37% | 3.40%1 | $1,000.00 |
| 6 Month | 3.37% | 3.40%1 | $1,000.00 |

Platinum Visa

| Card Type | APR |
| --- | --- |
| Introductory Balance Transfer Rate | 2.90%1 |
| Platinum Visa Rate | 12.50% – 19.50%2 |

Rewards Visa

| Card Type | APR |
| --- | --- |
| Standard | 15.50% – 21.00%1 |

Home Loans - Purchase

| Program | Rate | Points | APR | \\*Payment Example |
| --- | --- | --- | --- | --- |
| Purchase: 30-Year Fixed Conventional $300,000 or less | 7.25% | 0 | 7.32% | $2,046.53 |
| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.13% | 0 | 7.27% | $673.80 |
| Purchase: 15-Year Fixed Conventional | 6.75% | 0 | 6.88% | $1,327.36 |

Rates are effective as of 09/25/2026.
"""
BUSINESS_CARDS = """# Business credit cards | Example CU
Business Platinum Visa

| Card Type | APR |
| --- | --- |
| Business Platinum Visa | 15.50%1 |

Business Rewards Visa

| Card Type | APR |
| --- | --- |
| Business Rewards Visa | 20.50%1 |
"""
STALE_MORTGAGE = """# Homebuying guidance | Example CU
| Program | Rate | Points | APR | Payment |
| --- | --- | --- | --- | --- |
| Purchase: 30-Year Fixed Conventional $300,000 or less | 6.000% | 0.00% | 6.037% | $1,798.65 |
"""


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    pages = [("https://x.test/rates", "Rates | Example CU", RATES),
             ("https://x.test/business/credit-cards", "Business credit cards | Example CU", BUSINESS_CARDS),
             ("https://x.test/homebuying-guidance", "Homebuying guidance | Example CU", STALE_MORTGAGE)]
    ks.ingest(contract.Snapshot("01_2026-09-28", "2026-09-28",
                                [contract.Page(url=u, title=t, markdown=m, fetched_at="2026-09-28T00:00:00Z") for u, t, m in pages]))
    return ks


def test_cards_list_covers_personal_and_business_without_intro_offer():
    a = build().answer("What credit cards do you offer and what are their APRs?")
    for name in ("Platinum Visa", "Rewards Visa", "Business Platinum Visa", "Business Rewards Visa"):
        assert name in a.text
    assert "12.50%" in a.text and "20.50%" in a.text and "2.90" not in a.text


def test_platinum_standard_apr_is_not_the_intro_rate():
    a = build().answer("What is the standard purchase APR on the Platinum Visa?")
    assert "12.50%" in a.text and "2.90" not in a.text


def test_certificate_list_reads_back_every_term():
    a = build().answer("Get me the rates for the certificate accounts.")
    assert "Specials" in a.text and "4.10%" in a.text and "4.20%" in a.text
    assert "6-month" in a.text and "12-month" in a.text and "Which" not in a.text


def test_mortgage_tiers_list_rate_and_apr_and_skip_the_stale_page():
    a = build().answer("Can you tell me the interest rate for a 30-year mortgage?")
    nums = numbers_in(a.text)
    assert {("%", 7.13), ("%", 7.25)} <= nums and ("%", 6.0) not in nums and ("%", 6.037) not in nums
    assert "7.27% APR" in a.text
    pinned = build().answer("What's the 30-year mortgage rate on a $250,000 loan?")
    assert "7.25%" in pinned.text and "7.13" not in pinned.text
