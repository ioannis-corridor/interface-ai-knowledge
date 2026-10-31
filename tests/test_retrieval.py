"""Free-text and link answers: FAQ layout, definitional lead paragraphs, stray-rate refusal, link targets."""
import contract

from ks.system import KnowledgeSystem

MOBILE = """# Mobile payments | Example CU
## Frequently asked questions

- Can I use both my debit and credit card in my mobile wallet? Yes! Add one—or both—of your Example CU cards to Apple Pay, Google Pay or Samsung Pay.
"""
BLOG = """# Mobile wallets: a simple guide | Example CU
2 min read

Mobile wallets are everywhere. Turn your phone into a mobile wallet and pay with a tap. Most card issuers support them.
"""
GRANT = """# First-time homebuyers get a boost | Example CU
2 min read

[Jane Doe](https://x.test/newsroom/author/jane) August 09, 2024

Example CU is partnering with the Federal Home Loan Bank to help first-time homebuyers through the Home$tart program. This initiative provides up to $15,000 in assistance toward down payment and closing costs.

“Programs like Home$tart are critical to helping more families achieve the dream of owning a home,” said the CEO.
"""
CPI_BLOG = "# Inflation explained | Example CU\n\nFor 2019, the last full year available, the CPI rate was 1.8% annually.\n"
RATES = "# Rates | Example CU\nRegular Certificates\n\n| Certificate | Dividend Rate | Annual Percentage Yield (APY) |\n| --- | --- | --- |\n| 12 Month | 3.37% | 3.40% |\n"
JOIN = "# Join | Example CU\n\n[Join Example CU](https://join.x.test/) today. [Join now](https://join.x.test/start?src=nav)\n"


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    pages = [("https://x.test/connect/mobile-payments", "Mobile payments | Example CU", MOBILE),
             ("https://x.test/learn/blog/mobile-wallets-guide", "Mobile wallets | Example CU", BLOG),
             ("https://x.test/newsroom/first-time-homebuyers-hometart", "Boost | Example CU", GRANT),
             ("https://x.test/learn/blog/inflation", "Inflation | Example CU", CPI_BLOG),
             ("https://x.test/personal/savings-account", "Savings | Example CU", RATES),
             ("https://x.test/about/join", "Join | Example CU", JOIN),
             ("https://x.test/contact", "Contact | Example CU", "# Contact\n\n**Phone:** 800-555-0100\n")]
    ks.ingest(contract.Snapshot("01_2026-09-28", "2026-09-28",
                                [contract.Page(url=u, title=t, markdown=m, fetched_at="2026-09-28T00:00:00Z") for u, t, m in pages]))
    return ks


def test_faq_question_sentence_yields_the_answer_sentence():
    a = build().answer("Can I add my debit and credit cards to a mobile wallet?")
    assert "Apple Pay, Google Pay or Samsung Pay" in a.text and not a.text.startswith("- Can I")
    assert a.sources[0].url.endswith("/mobile-payments")


def test_definitional_question_takes_the_lead_paragraph_with_its_figure():
    a = build().answer("What is the Home$tart program?")
    assert "$15,000" in a.text and "critical" not in a.text


def test_rate_question_without_a_product_never_quotes_a_stray_percentage():
    a = build().answer("Rate on a used pickup from 2019, 5 year loan?")
    assert not a.confident and "1.8" not in a.text


def test_link_answers():
    ks = build()
    assert "x.test/personal/savings-account#rates" in ks.answer("What link should I use to see your CD rates?").text
    assert "https://join.x.test/" in ks.answer("How do I join online?").text
    assert "x.test/contact" in ks.answer("What's the URL for your branch locator?").text
