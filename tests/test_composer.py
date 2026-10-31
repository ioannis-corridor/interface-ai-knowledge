"""Composer paths on a synthetic site: tier listing, superlative, verify, change, link, fee, as-of refusal."""
import contract

from ks.format import plain_text
from ks.system import KnowledgeSystem
from ks.text import numbers_in

RATES = """# Rates
Share Savings

| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 | Min. to Open | Min. to Earn |
| --- | --- | --- | --- | --- | --- |
| Share Savings | $25,000+ | 0.20% | 0.20%1 | $25.00 | $25,000.00 |
| Share Savings | $10,000 – $24,999.99 | 0.15% | 0.15%1 | $25.00 | $10,000.00 |
| Share Savings | $0 – $9,999.99 | 0.10% | 0.10%1 | $25.00 | $0.00 |

Rates are effective as of 06/15/2026 and are subject to change without notice.

Special Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 17 Month Fixed Certificate Special | 4.06% | 4.10%2 | $1,000.00 |

Rates are effective as of {special_eff} and are subject to change without notice.

Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) |
| --- | --- | --- |
| {my} Model Year | 60 Months | {auto60} APR1 |
| {my} Model Year | 72 Months | 5.49% APR |

Rates are effective as of 08/31/2026. All loans are subject to approval.
"""
CALCULATOR = """# Vehicle calculator
Auto Loan Rates

| Account Type | Balance Tier | Annual Percentage Yield |
| --- | --- | --- |
| 2023–26 Model Year | 60 Months | 5.34% APR |
"""
FEES = "# Fee schedule\n\nMISCELLANEOUS FEES AND CHARGES\n\nStop payment (check, ACH, & bill pay) $30.00* per item\nDomestic wire $25.00 each\nInternational wire transfer $55.00 each\n"
CONTACT = "# Contact\n\n**Phone:** 800-555-0100\n"


def _snap(sid, taken, pages):
    return contract.Snapshot(sid, taken, [contract.Page(url=u, title=t, markdown=m, fetched_at=taken + "T00:00:00Z")
                                          for u, t, m in pages])


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    may = RATES.format(special_eff="03/03/2026", my="2023-26", auto60="5.19%").replace(
        "| 17 Month Fixed Certificate Special | 4.06% | 4.10%2 | $1,000.00 |\n", "")   # no 17-month special yet
    sep = RATES.format(special_eff="09/01/2026", my="2024-27", auto60="5.39%")
    ks.ingest(_snap("01_2026-05-12", "2026-05-12", [
        ("https://x.test/rates", "Rates | Example CU", may),
        ("https://x.test/calculators/vehicle", "Calculator | Example CU", CALCULATOR),
        ("https://x.test/hubfs/fees.pdf", "Fees", FEES), ("https://x.test/contact", "Contact | Example CU", CONTACT)]))
    ks.ingest(_snap("02_2026-09-28", "2026-09-28", [
        ("https://x.test/rates", "Rates | Example CU", sep),
        ("https://x.test/calculators/vehicle", "Calculator | Example CU", CALCULATOR),
        ("https://x.test/hubfs/fees.pdf", "Fees", FEES), ("https://x.test/contact", "Contact | Example CU", CONTACT)]))
    return ks


def test_pinned_tier_gives_one_value_and_lists_tiers_when_unpinned():
    ks = build()
    a = ks.answer("What dividend rate do I earn on Share Savings with $12,000?")
    assert "0.15%" in a.text and "0.20" not in a.text and "0.10" not in a.text
    b = ks.answer("What are the Share Savings rates?")
    assert numbers_in(b.text) >= {("%", 0.2), ("%", 0.15), ("%", 0.1)}


def test_superlative_and_verify():
    ks = build()
    assert "0.20%" in ks.answer("What is the highest Share Savings APY?").text
    yes = ks.answer("Do any Share Savings tiers pay 0.15% APY?")
    assert yes.text.startswith("Yes") and "0.15%" in yes.text
    no = ks.answer("Do any Share Savings tiers pay 0.35% APY?")
    assert no.text.startswith("No") and "0.20%" in no.text and "0.35" not in no.text


def test_stale_calculator_never_wins_and_is_noted():
    ks = build()
    a = ks.answer("What's the APR for a 60-month auto loan on a 2025 vehicle?")
    assert "5.39%" in a.text and "5.34" not in a.text
    assert a.conflict_note and "5.34%" in a.conflict_note
    assert all("calculator" not in s.url for s in a.sources)


def test_change_history_follows_drifting_model_year_tiers():
    a = build().answer("How has the 60-month auto loan APR for new vehicles changed?")
    assert "5.19%" in a.text and "5.39%" in a.text and "changed from" in a.text


def test_as_of_product_not_offered_yet_refuses_without_numbers():
    q = "What is the 17-month certificate special APY?"
    ks = build()
    assert "4.10%" in ks.answer(q).text
    old = ks.answer(q, as_of="2026-05-31")
    assert not old.confident and not numbers_in(old.text)


def test_fee_lookup_and_strict_refusal():
    ks = build()
    assert "$25.00" in ks.answer("What does an outgoing domestic wire cost?").text
    assert "$55.00" in ks.answer("Cost to wire money overseas?").text
    lost = ks.answer("Is there a fee for a lost debit card?")
    assert not lost.confident and not numbers_in(lost.text)


def test_link_and_phone():
    ks = build()
    assert "x.test/rates" in ks.answer("What link shows your certificate rates?").text
    assert "800-555-0100" in ks.answer("What's your phone number?").text


def test_plain_text_strips_markdown_and_templates():
    assert plain_text("***bold*** `code` <val> ## Heading") == "bold code Heading"
    assert plain_text("see https://x.test/rates#rates -> now") == "see https://x.test/rates#rates -> now"
