"""Pure text-formatting helpers shared by the answer composer and the conflicts report."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from .model import INF, Fact
from .text import fmt_money, range_text

METRIC_WORDS = {"apy": "APY", "dividend_rate": "dividend rate", "apr": "APR", "rate": "rate", "fee": "fee",
                "min_open": "minimum to open", "min_earn": "minimum balance to earn dividends on"}


def metric_word(metric: str) -> str:
    return METRIC_WORDS.get(metric, metric)


def years_text(model_years: Tuple[int, int]) -> str:
    lo, hi = model_years
    return f"{hi} and older model years" if lo == 0 else f"{lo}-{hi} model years"


def term_text(months: Optional[int]) -> str:
    if not months:
        return ""
    if months % 12 == 0 and months >= 120:
        return f"{months // 12}-year"
    return f"{months}-month"


def tier_phrase(f: Fact) -> str:
    """'balances $10,000 to $24,999.99', '2024-2027 model years', 'loan amounts up to $100,000'."""
    bits = []
    if f.model_years:
        bits.append(years_text(f.model_years))
    if f.balance:
        lo, hi = f.balance
        bits.append(f"balances of {fmt_money(lo)} and up" if hi == INF else f"balances {range_text(lo, hi)}")
    if f.amount:
        lo, hi = f.amount
        bits.append(f"loan amounts of {fmt_money(lo)} and up" if hi == INF else f"loan amounts {range_text(lo, hi)}")
    return ", ".join(bits)


def product_name(f: Fact) -> str:
    if f.family == "certificate" and re.fullmatch(r"\d+ Month Certificate", f.product):
        return f.product.replace(" Month ", "-month ").lower()
    return f.product


def has_term_words(name: str) -> bool:
    return bool(re.search(r"\d+[- ]?month|\d+[- ]?year", name, re.I))


def month_text(d: date) -> str:
    return d.strftime("%B %Y")


def tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).replace(" .", ".").replace(" ,", ",").strip()
    return text[0].upper() + text[1:] if text else text


def plain_text(s: str) -> str:
    """Member-facing text is plain: no markdown emphasis, brackets or angle-bracket templates."""
    s = re.sub(r"[*_`\[\]]+|<[^>]{0,40}>", "", s or "")
    s = re.sub(r"(^|\s)#+\s", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()
