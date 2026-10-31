"""Data model: one Fact is one value for one (product, qualifiers, metric) on one page in one snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Tuple

INF = float("inf")

METRIC_NAMES = {
    "apy": "APY", "dividend_rate": "dividend rate", "apr": "APR", "rate": "rate", "points": "points",
    "min_open": "minimum to open", "min_earn": "minimum to earn", "payment": "payment example",
}

FAMILY_NAMES = {
    "certificate": "certificate", "ira": "IRA", "savings": "savings account", "money_market": "money market",
    "hsa": "Health Savings Account", "checking": "checking account", "auto": "auto loan", "mortgage": "mortgage",
    "heloc": "home equity line of credit", "home_equity_loan": "home equity loan",
    "home_improvement": "home improvement loan", "personal_loan": "personal loan", "credit_card": "credit card",
    "boat_rv": "boat and RV loan", "atv": "ATV, snowmobile and jet ski loan", "student_loan": "student loan",
}


@dataclass
class Fact:
    family: str                          # certificate, savings, auto, mortgage, credit_card, entity ...
    product: str                         # display name, e.g. "17 Month Fixed Certificate Special"
    metric: str                          # apy, dividend_rate, apr, rate, min_open, min_earn, count, hours ...
    value: str                           # as displayed, footnotes stripped: "4.10%", "22", "Mon-Fri 8 a.m.-6 p.m."
    url: str
    snapshot_id: str
    authority: int
    term_months: Optional[int] = None
    model_years: Optional[Tuple[int, int]] = None
    balance: Optional[Tuple[float, float]] = None
    amount: Optional[Tuple[float, float]] = None
    jumbo: bool = False
    special: bool = False
    ira_type: Optional[str] = None       # roth / traditional
    purpose: Optional[str] = None        # purchase / refinance
    intro: bool = False                  # introductory credit-card rate
    business: bool = False
    effective: Optional[date] = None
    article_date: Optional[date] = None
    fetched_at: Optional[date] = None
    quote: str = ""
    label: str = ""                      # natural-language description used for matching and templates
    extra: dict = field(default_factory=dict)

    def soft_key(self) -> tuple:
        """Identity used for conflict detection: same product + qualifiers + metric, tier labels normalised."""
        return (
            self.family, self.business, _norm_product(self.product, self.family), self.metric, self.term_months,
            self.model_years, self.balance, self.amount, self.jumbo, self.special, self.ira_type, self.purpose,
            self.intro,
        )

    def tier_text(self) -> str:
        from .text import range_text
        bits = []
        if self.model_years:
            lo, hi = self.model_years
            bits.append(f"{lo}-{hi} model years" if lo else f"{hi} and older model years")
        if self.balance:
            bits.append("balances " + range_text(*self.balance))
        if self.amount:
            bits.append("loan amounts " + range_text(*self.amount))
        return ", ".join(bits)


PRODUCT_ALIASES = [
    (r"investor", "Investor's Choice Money Market"), (r"share savings", "Share Savings"),
    (r"you[- ]name[- ]it", "You Name It Savings"), (r"bright savings", "Bright Savings"),
    (r"holiday club", "Holiday Club Savings"), (r"high[- ]yield", "High-Yield Savings"),
    (r"launchpad", "Launchpad Savings"), (r"1st rate|first rate", "1st Rate Checking"),
    (r"free checking", "Free Checking"), (r"health savings|\bhsa\b", "Health Savings Account"),
    (r"business platinum", "Business Platinum Visa"), (r"business rewards", "Business Rewards Visa"),
    (r"platinum", "Platinum Visa"), (r"rewards", "Rewards Visa"),
    (r"introductory|intro\b", "Introductory Balance Transfer"),
    (r"heloc|line of credit", "Home Equity Line of Credit"),
]


def canonical_product(product: str, family: str) -> str:
    """Map the many spellings of one product ("Investor's Choice", "Investor’s Choice Money Market") to one name."""
    import re
    low = (product or "").lower()
    if family in ("savings", "money_market", "hsa", "checking", "credit_card", "heloc"):
        for pat, name in PRODUCT_ALIASES:
            if re.search(pat, low):
                return name
    if family == "certificate" and re.fullmatch(r"\d+\s*months?", low):
        return product.rstrip("s") + " Certificate"
    return product


def _norm_product(product: str, family: str) -> str:
    import re
    p = (product or "").lower()
    p = re.sub(r"\b\d+\s*[- ]?\s*(month|months|mo|year|years)\b", " ", p)
    p = re.sub(r"\b(roth|traditional)\s*:?", " ", p)
    p = re.sub(r"\$[\d,.]+\s*(or less)?", " ", p)
    p = re.sub(r"\b(fixed|certificate|special|jumbo|model year|and older)\b", " ", p)
    p = re.sub(r"[^a-z ]", " ", p)
    return " ".join(p.split())
