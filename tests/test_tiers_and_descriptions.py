"""Newest-model tier, products dropped since an earlier crawl, generic-label dedupe, describe questions, and the
fragment filters in free-text answers."""
import contract

from ks.answer.retrieval import _is_sentence
from ks.index import split_chunks
from ks.system import KnowledgeSystem
from ks.text import numbers_in

RATES_MAY = """# Rates | Example CU
Special Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 25 Month Fixed Certificate Special | 3.57% | 3.60% | $1,000.00 |

Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) |
| --- | --- | --- |
| 2023-26 Model Year | 48 Months | 4.99% APR1 |
| 2016 Model Year (and older) | 48 Months | 8.54% APR1 |
"""
RATES_SEP = """# Rates | Example CU
Special Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 17 Month Fixed Certificate Special | 4.06% | 4.10% | $1,000.00 |

Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) |
| --- | --- | --- |
| 2024-27 Model Year | 48 Months | 5.19% APR1 |
| 2016 Model Year (and older) | 48 Months | 8.59% APR1 |

Variable IRAs

| IRA Type | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| Roth: $15,000+ | 0.60% | 0.60% | $15,000.00 |
| Traditional: $15,000+ | 0.60% | 0.60% | $15,000.00 |
"""
RETIREMENT = """# Retirement | Example CU
Variable IRAs

| Balance | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| $15,000+ | 0.60% | 0.60% | $15,000.00 |
"""
STUDENT = """# Student Loans | Example CU
Already have a student loan with us? Log in to Shine to view your balance.

Whether you need to fill the funding gap for college or simplify repayment after graduation, we have flexible options to help you take your education higher.

[Apply for Student Loan](https://x.test/apply) [Apply for Refinancing](https://x.test/refi)
"""


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    ks.ingest(contract.Snapshot("01_2026-05-12", "2026-05-12", [
        contract.Page(url="https://x.test/rates", title="Rates | Example CU", markdown=RATES_MAY, fetched_at="2026-05-12T00:00:00Z")]))
    ks.ingest(contract.Snapshot("02_2026-09-28", "2026-09-28", [
        contract.Page(url="https://x.test/rates", title="Rates | Example CU", markdown=RATES_SEP, fetched_at="2026-09-28T00:00:00Z"),
        contract.Page(url="https://x.test/personal/retirement", title="Retirement | Example CU", markdown=RETIREMENT, fetched_at="2026-09-28T00:00:00Z"),
        contract.Page(url="https://x.test/personal/loans/student-loans", title="Student Loans | Example CU", markdown=STUDENT, fetched_at="2026-09-28T00:00:00Z")]))
    return ks


def test_brand_new_car_means_the_newest_model_year_tier():
    a = build().answer("What's the 48 month car loan rate for a brand new car?")
    assert "5.19%" in a.text and "8.59" not in a.text


def test_product_dropped_since_an_earlier_crawl_says_so():
    a = build().answer("Do you offer a 25-month certificate special?")
    assert not a.confident and "no longer lists" in a.text and not numbers_in(a.text) - numbers_in("25-month")
    assert a.conflict_note and "May 2026" in a.conflict_note and "3.60%" in a.conflict_note
    old = build().answer("What is the 25-month certificate special APY?", as_of="2026-05-31")
    assert "3.60%" in old.text


def test_generic_table_label_does_not_duplicate_roth_rows():
    a = build().answer("Roth IRA rates?")
    assert a.text.count("0.60%") == 1 and "Variable IRAs" not in a.text


def test_describe_question_skips_faq_and_cta_fragments():
    a = build().answer("Tell me about your student loans")
    assert "flexible options" in a.text and "Log in" not in a.text and "Apply for" not in a.text
    b = build().answer("I'm a student going to a new university - do you have any loan options with flexibility?")
    assert b.text.startswith("Student loans:") and "flexible options" in b.text


def test_fragment_filters():
    assert not _is_sentence("Open my Holiday Club Launchpad Savings")
    assert _is_sentence("Rates are effective as of 06/02/2026.")
    assert _is_sentence("No monthly fees and no minimum balance and no hoops to jump through at all")
    chunks = split_chunks("[Open my Holiday Club](https://x.test/a) [See details](https://x.test/b)\n\nLaunchpad Savings\n")
    assert chunks == []
