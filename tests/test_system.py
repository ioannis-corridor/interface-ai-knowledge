"""End-to-end behaviour on a tiny synthetic site: current value, as_of, stale copy, refusal, conflicts."""
import contract

from ks.system import KnowledgeSystem
from ks.text import numbers_in

RATES_JAN = """# Rates
Regular Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 6 Month | 2.91% | 2.95% | $1,000.00 |
| 12 Month | 3.05% | 3.10% | $1,000.00 |

Rates are effective as of 01/02/2026 and are subject to change without notice.
"""
RATES_MAR = RATES_JAN.replace("2.91% | 2.95%", "3.44% | 3.50%").replace("01/02/2026", "03/01/2026")
PROMO = "# Summer promo\n\nSummer special: 6-month certificate APY 2.95% (offer ended 2025-09-30)\n"
FEES = "# Fees\n\nLost debit card replacement fee: $2.50\n"
CONTACT = "# Contact\n\n**Phone:** 800-555-0100\n\n**Routing Number:** 123456789\n"


def _snap(sid, taken, pages):
    return contract.Snapshot(sid, taken, [contract.Page(url=u, title=t, markdown=m, fetched_at=taken + "T00:00:00Z")
                                          for u, t, m in pages])


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    ks.ingest(_snap("01_2026-01-05", "2026-01-05", [
        ("https://example-cu.test/rates", "Rates | Example CU", RATES_JAN),
        ("https://example-cu.test/fees", "Fees | Example CU", FEES),
        ("https://example-cu.test/contact", "Contact | Example CU", CONTACT)]))
    ks.ingest(_snap("02_2026-03-01", "2026-03-01", [
        ("https://example-cu.test/rates", "Rates | Example CU", RATES_MAR),
        ("https://example-cu.test/promo", "Promo | Example CU", PROMO),
        ("https://example-cu.test/contact", "Contact | Example CU", CONTACT)]))
    return ks


def test_current_value_beats_expired_promo():
    a = build().answer("What is the 6-month certificate APY?")
    assert "3.50%" in a.text and "2.95" not in a.text and a.confident
    assert any(s.url.endswith("/rates") for s in a.sources)


def test_as_of_uses_the_snapshot_of_that_day_only():
    a = build().answer("What was the 6-month certificate APY in January 2026?", as_of="2026-01-31")
    assert "2.95%" in a.text and "3.50" not in a.text


def test_vanished_page_is_carried_forward():
    a = build().answer("How much is a lost debit card replacement?")
    assert "$2.50" in a.text


def test_refusal_has_no_new_numbers():
    q = "What is the 60-month jumbo certificate rate?"
    a = build().answer(q)
    assert not a.confident
    assert not (numbers_in(a.text) - numbers_in(q))


def test_entities_and_consistency():
    ks = build()
    assert "123456789" in ks.answer("What is your routing number?").text
    assert "800-555-0100" in ks.answer("What's your phone number?").text
    a1 = ks.answer("Current APY on a six month share certificate?")
    a2 = ks.answer("What is the 6-month certificate APY?")
    assert numbers_in(a1.text) == numbers_in(a2.text)


def test_conflicts_name_the_stale_promo():
    cs = build().conflicts()
    six = [c for c in cs if "6-month" in c.topic.lower() or "6 month" in c.topic.lower()]
    assert six and set(six[0].values) == {"3.50%", "2.95%"} and six[0].resolution == "3.50%"
    assert "promo" in six[0].reason.lower() or "rates" in six[0].reason.lower()
