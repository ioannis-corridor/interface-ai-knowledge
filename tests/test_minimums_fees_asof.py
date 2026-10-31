"""Minimum-to-open / minimum-to-earn questions, fee schedules rendered as tables, fee fallback to product text,
and the caveat when `as_of` predates the first crawl."""
import contract

from ks.entities import extract_prose_facts
from ks.system import KnowledgeSystem

RATES = """# Rates | Example CU
Share Savings

| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 | Min. to Open | Min. to Earn |
| --- | --- | --- | --- | --- | --- |
| Share Savings | $25,000+ | 0.20% | 0.20%1 | $25.00 | $25,000.00 |
| Share Savings | $0 – $24,999.99 | 0.15% | 0.15%1 | $25.00 | $0.00 |

Regular Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 12 Month | 3.37% | 3.40% | $1,000.00 |
| 6 Month | 3.37% | 3.40% | $1,000.00 |

Rates are effective as of 03/03/2026 and are subject to change without notice.
"""
CHECKING = "# Free Checking | Example CU\n\nNo monthly fees and no minimum balance. There's no minimum to open and no monthly service charges.\n"
FEES_TABLE = """## Rate and Fee Schedule

|Deposit Services Consumer|Col2|Col3|Col4|
|---|---|---|---|
|Stop payment (check, ACH, &amp; bill pay)|$30.00* per item|||
|Domestic wire|$25.00 each|||
"""


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    pages = [("https://x.test/rates", "Rates | Example CU", RATES),
             ("https://x.test/personal/checking-accounts", "Free Checking | Example CU", CHECKING),
             ("https://x.test/hubfs/fee-schedule.pdf", "Fees", FEES_TABLE)]
    ks.ingest(contract.Snapshot("01_2026-05-12", "2026-05-12",
                                [contract.Page(url=u, title=t, markdown=m, fetched_at="2026-05-12T00:00:00Z") for u, t, m in pages]))
    return ks


def test_minimum_to_open_and_to_earn():
    ks = build()
    assert ks.answer("What is the minimum to open a Share Savings account?").text == "The minimum to open Share Savings is $25.00."
    cert = ks.answer("What's the minimum deposit for a 12-month certificate?")
    assert "$1,000.00" in cert.text and "3.40" not in cert.text          # falls back to the only minimum listed
    top = ks.answer("What's the minimum balance to earn the top Share Savings rate?")
    assert "0.20%" in top.text and "$25,000" in top.text                 # still a rate question


def test_fee_schedule_rendered_as_pipe_table():
    facts = extract_prose_facts(FEES_TABLE, "https://x.test/hubfs/fee-schedule.pdf", "Fees", "01", 20, None, None)
    by = {f.product: f.value for f in facts}
    assert by["Stop payment (check, ACH, & bill pay)"] == "$30.00 per item"
    assert by["Domestic wire"] == "$25.00 each"
    assert "$30.00" in build().answer("How much is a stop payment?").text


def test_fee_question_about_a_product_falls_back_to_its_page():
    a = build().answer("Is there a monthly fee on Free Checking?")
    assert "no monthly service charges" in a.text.lower() and "%" not in a.text


def test_as_of_before_first_crawl_is_flagged():
    a = build().answer("What was the 6-month certificate APY in January 2026?", as_of="2026-01-31")
    assert "3.40%" in a.text and "earliest available copy" in a.text and "May 2026" in a.text
    assert a.conflict_note and "predates the first crawl" in a.conflict_note
