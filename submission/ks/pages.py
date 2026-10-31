"""Page classification: which pages are authoritative for which kind of fact."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Optional
from urllib.parse import urlparse

from .text import parse_long_date

# Authority classes, highest first. Only consulted when two sources disagree on the same fact.
RATES, PRODUCT, INFO, NEWSROOM, LEARN, LANDING, CALCULATOR, FILE, OTHER = 100, 90, 85, 60, 50, 40, 30, 20, 10

LANDING_PATHS = {
    "/switch-and-earn", "/earn-more", "/homebuying-guidance", "/mortgage-refi", "/thankuse", "/not-for-sale",
    "/makethemost-lp", "/membermoneymarket-lp", "/checking-offer-lp", "/tax-checking-offer-lp",
    "/newcard-balancetransfer-lp", "/21-day-sprint-to-savings-challenge", "/sprint-to-savings-challenge",
}

URL_FAMILY_HINTS = [
    (r"/auto|/vehicle", "auto"), (r"/home-loans|/mortgage", "mortgage"), (r"/home-equity-line|heloc", "heloc"),
    (r"/home-equity", "home_equity_loan"), (r"/home-improvement", "home_improvement"),
    (r"/personal-loans", "personal_loan"), (r"/credit-cards", "credit_card"), (r"/checking", "checking"),
    (r"/savings|/holiday-club", "deposit"), (r"/retirement|/ira", "ira"), (r"/recreational|/boat", "boat_rv"),
    (r"/student", "student_loan"), (r"/business", "business"), (r"/contact", "contact"),
]


def path_of(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/").rstrip("/") or "/"


def url_key(url: str) -> str:
    """Path-level identity, the same way the scorer matches sources."""
    p = urlparse(url if "//" in url else "https://" + url)
    return p.netloc.lower().removeprefix("www.") + p.path.rstrip("/").lower()


def classify(url: str, title: str = "") -> int:
    path = path_of(url)
    q = urlparse(url).query
    if path in ("/rates", "/business-rates"):
        return RATES
    if path.startswith("/hubfs") or path.endswith((".pdf", ".xlsx", ".xls", ".csv")):
        return FILE
    if path.startswith(("/calculators", "/business-calculators")):
        return CALCULATOR
    if path in LANDING_PATHS or path.endswith("-lp"):
        return LANDING
    if path.startswith("/newsroom"):
        return OTHER if re.search(r"/(tag|author)/", path) else NEWSROOM
    if path.startswith(("/learn", "/resources", "/dupacodaily", "/business/resources")) or re.match(r"^/20\d\d/", path):
        return OTHER if re.search(r"/(tag|author)/", path) else LEARN
    if "privacy" in path or path.startswith("/disclosures") or "terms" in path:
        return CALCULATOR          # legal boilerplate: keep it searchable, never authoritative
    if q:
        return PRODUCT
    if path.startswith(("/personal", "/business", "/checking", "/loans", "/savings", "/savings-account")):
        return PRODUCT
    if path.startswith(("/contact", "/about", "/membership", "/connect", "/mobile", "/disclosures", "/protection")) or path == "/":
        return INFO
    return INFO if title else OTHER


def url_family(url: str) -> Optional[str]:
    path = path_of(url).lower()
    for pat, fam in URL_FAMILY_HINTS:
        if re.search(pat, path):
            return fam
    return None


def is_business(url: str) -> bool:
    return "/business" in path_of(url).lower()


def article_date(markdown: str) -> Optional[date]:
    """Newsroom and blog posts carry a 'June 20, 2025' line near the top."""
    head = markdown[:2500]
    m = re.search(r"\b\d+ min read\b.*?(\w+ \d{1,2}, 20\d\d)", head, re.S)
    if m:
        d = parse_long_date(m.group(1))
        if d:
            return d
    return parse_long_date(head)


class BoilerplateFilter:
    """Lines repeated across many pages of one snapshot are navigation, footer or widgets."""

    def __init__(self, pages: list, min_pages: int = 25):
        counts: Counter = Counter()
        for p in pages:
            seen = set()
            for line in p.markdown.splitlines():
                s = line.strip()
                if len(s) > 12 and not s.startswith("|"):
                    seen.add(s)
            counts.update(seen)
        self.common = {s for s, n in counts.items() if n >= min_pages}

    def clean(self, markdown: str) -> str:
        out = []
        for line in markdown.splitlines():
            s = line.strip()
            if s in self.common and not s.lower().startswith("rates are effective"):
                continue
            out.append(line)
        return "\n".join(out)
