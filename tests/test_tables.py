"""Markdown rate tables -> facts. Fixtures are synthetic but mirror the real page layouts."""
from datetime import date

from ks.tables import parse_tables, table_to_facts, rename_generic_products

RATES_PAGE = """
Savings Accounts

Share Savings

| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 | Min. to Open | Min. to Earn |
| --- | --- | --- | --- | --- | --- |
| Share Savings | $25,000+ | 0.20% | 0.20%1 | $25.00 | $25,000.00 |
| Share Savings | $10,000 – $24,999.99 | 0.15% | 0.15%1 | $25.00 | $10,000.00 |

Rates are effective as of 06/15/2026 and are subject to change without notice.

Certificates

Special Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 17 Month Fixed Jumbo Certificate Special | 4.15% | 4.20%1 | $100,000.00 |
| 17 Month Fixed Certificate Special | 4.06% | 4.10%2 | $1,000.00 |

Rates are effective as of 09/01/2026 and are subject to change without notice.

Auto & Motorcycle Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) |
| --- | --- | --- |
| 2024-27 Model Year | 60 Months | 5.39% APR1 |
| 2016 Model Year (and older) | 48 Months | 8.59% APR1 |

Rates are effective as of 08/31/2026. All loans are subject to approval.

Home Loans - Purchase

| Program | Rate | Points | APR | \\*Payment Example |
| --- | --- | --- | --- | --- |
| Purchase: 30-Year Fixed Conventional $100,000 or less | 7.13% | 0 | 7.27% | $673.80 |
| Purchase: 15-Year Fixed Conventional | 6.75% | 0 | 6.88% | $1,327.36 |

Rates are effective as of 09/25/2026.

Personal Loan

| Term | APR (As Low As) |
| --- | --- |
| 36 Months | 10.49%1 |
"""


def _facts(md, url="https://example-cu.test/rates", auth=100):
    out = []
    for t in parse_tables(md):
        out += table_to_facts(t, url, "01", auth, None, None)
    return out


def test_labels_effective_dates_and_footnotes():
    facts = _facts(RATES_PAGE)
    share = [f for f in facts if f.product == "Share Savings" and f.metric == "apy"]
    assert [f.value for f in share] == ["0.20%", "0.15%"]           # footnote digit stripped
    assert share[0].balance == (25000.0, float("inf")) and share[1].balance == (10000.0, 24999.99)
    assert share[0].effective == date(2026, 6, 15)                 # found ten lines below the table


def test_certificate_terms_jumbo_and_special():
    facts = _facts(RATES_PAGE)
    certs = [f for f in facts if f.family == "certificate" and f.metric == "apy"]
    assert {(f.term_months, f.jumbo, f.special, f.value) for f in certs} == {(17, True, True, "4.20%"), (17, False, True, "4.10%")}
    assert all(f.effective == date(2026, 9, 1) for f in certs)


def test_auto_model_year_ranges_and_terms():
    facts = _facts(RATES_PAGE)
    auto = {f.term_months: f for f in facts if f.family == "auto"}
    assert auto[60].model_years == (2024, 2027) and auto[60].value == "5.39%"
    assert auto[48].model_years == (0, 2016) and auto[48].value == "8.59%"


def test_mortgage_amount_tiers_rate_and_apr():
    facts = _facts(RATES_PAGE)
    m = [f for f in facts if f.family == "mortgage"]
    thirty = [f for f in m if f.term_months == 360]
    assert {f.metric: f.value for f in thirty if f.metric in ("rate", "apr")} == {"rate": "7.13%", "apr": "7.27%"}
    assert thirty[0].amount == (0.0, 100000.0) and thirty[0].purpose == "purchase"
    assert [f for f in m if f.term_months == 180 and f.metric == "rate"][0].value == "6.75%"


def test_personal_loan_term_from_product_column():
    facts = _facts(RATES_PAGE)
    pl = [f for f in facts if f.family == "personal_loan"]
    assert pl and pl[0].term_months == 36 and pl[0].value == "10.49%"


def test_generic_label_is_renamed_from_tier_signature():
    promo = """
Checking Accounts

| Balance | Dividend Rate | Annual Percentage Yield (APY)1 |
| --- | --- | --- |
| $25,000 - $99,999.99 | 0.10% | 0.10% |
| $5,000 - $24,999.99 | 2.96% | 3.00% |
"""
    real = """
1st Rate Checking

| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield (APY)1 |
| --- | --- | --- | --- |
| 1st Rate Checking | $25,000 – $99,999.99 | 0.10% | 0.10% |
| 1st Rate Checking | $5,000 – $24,999.99 | 2.47% | 2.50% |
"""
    facts = _facts(real) + _facts(promo, url="https://example-cu.test/checking-offer-lp", auth=40)
    rename_generic_products(facts)
    assert all(f.product == "1st Rate Checking" for f in facts if f.family == "checking")


def test_off_topic_table_on_product_page_loses_authority():
    on_rates = [f for f in _facts(RATES_PAGE) if f.family == "auto"][0]
    on_checking = [f for f in _facts(RATES_PAGE, url="https://example-cu.test/personal/checking-accounts", auth=90)
                   if f.family == "auto"][0]
    assert on_rates.authority == 100 and on_checking.authority < 90
