"""Text utilities shared by the parsers, the index and the answer composer."""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Optional

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
MONTH_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December)"

LONG_DATE_RE = re.compile(MONTH_RE + r"\s+(\d{1,2}),\s+(20\d\d)")
NUMERIC_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
EFFECTIVE_RE = re.compile(r"effective\s+(?:as\s+of\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", re.I)

LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
FOOTNOTE_RE = re.compile(r"(%|\bAPR|\bAPY)(\d)\b")            # "4.10%2" -> "4.10%", "5.39% APR1" -> "5.39% APR"
PCT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
# Mirrors the scorer: a number with optional $ / % unit.
NUM_RE = re.compile(r"(\$)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(%|percent)?", re.I)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do", "does", "for", "from", "get",
    "give", "have", "how", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our", "please",
    "tell", "that", "the", "their", "there", "these", "they", "this", "to", "we", "what", "whats", "which",
    "who", "will", "with", "would", "you", "your", "yours", "about", "any", "some", "right", "now",
    "current", "currently", "today", "know", "want", "like", "need", "should", "offer", "offers",
    "credit", "union", "repeat", "again", "say", "said", "also", "just", "much",
    "many", "when", "where", "why", "did", "was", "were", "has", "had", "been", "being", "am", "pm",
}

SYNONYMS = {
    "cd": "certificate", "cds": "certificate", "certificates": "certificate",
    "car": "auto", "cars": "auto", "vehicle": "auto", "vehicles": "auto", "truck": "auto", "automobile": "auto",
    "mortgages": "mortgage", "homeloan": "mortgage",
    "cheque": "checking", "chequing": "checking",
    "atms": "atm", "branches": "branch", "locations": "branch", "location": "branch", "offices": "branch",
    "yield": "apy", "yields": "apy",
    "fees": "fee", "charges": "fee", "charge": "fee", "cost": "fee", "costs": "fee",
    "phone": "phone", "telephone": "phone",
    "hrs": "hours", "hour": "hours", "timings": "hours", "schedule": "hours",
    "url": "link", "webpage": "page", "web": "page", "website": "page",
    "join": "join", "joining": "join", "membership": "member", "members": "member", "eligible": "eligibility",
    "eligibility": "eligibility", "qualify": "eligibility",
    "loans": "loan", "rates": "rate", "cards": "card", "accounts": "account", "specials": "special",
    "months": "month", "mo": "month", "mos": "month", "years": "year", "yr": "year", "yrs": "year",
}

WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_markdown(s: str) -> str:
    """Links keep their text, images vanish, emphasis markers go away, HTML entities are decoded."""
    s = html.unescape(s or "")
    s = IMAGE_RE.sub("", s)
    s = LINK_RE.sub(r"\1", s)
    s = re.sub(r"[*_`#>]+", "", s)
    s = s.replace("\\", "")
    return norm_space(s)


def clean_cell(s: str) -> str:
    s = strip_markdown(s)
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    s = FOOTNOTE_RE.sub(r"\1", s)
    return norm_space(s)


def parse_long_date(s: str) -> Optional[date]:
    m = LONG_DATE_RE.search(s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def parse_numeric_date(s: str) -> Optional[date]:
    m = NUMERIC_DATE_RE.search(s or "")
    if not m:
        return None
    mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yy < 100:
        yy += 2000
    try:
        return date(yy, mm, dd)
    except ValueError:
        return None


def parse_effective(s: str) -> Optional[date]:
    m = EFFECTIVE_RE.search(s or "")
    return parse_numeric_date(m.group(1)) if m else None


def parse_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


def numbers_in(text: str) -> set:
    """Same numeric fingerprint the scorer uses: (unit, value)."""
    out = set()
    for m in NUM_RE.finditer(text or ""):
        unit = "$" if m.group(1) else ("%" if m.group(4) else "")
        val = float(m.group(2).replace(",", "") + ("." + m.group(3) if m.group(3) else ""))
        out.add((unit, round(val, 4)))
    return out


def tokenize(text: str, keep_stop: bool = False) -> list:
    s = (text or "").lower().replace("–", "-").replace("—", "-").replace("’", "'")
    s = re.sub(r"\b([ap])\.m\.?", r"\1m", s)
    s = re.sub(r"'s\b", "", s)
    s = s.replace("$", " $ ").replace("%", " % ")
    toks = []
    for w in WORD_RE.findall(s):
        w = w.strip("'-")
        if not w:
            continue
        w = SYNONYMS.get(w, w)
        if not keep_stop and w in STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w[-2].isdigit():
            w = w[:-1]
            w = SYNONYMS.get(w, w)
        toks.append(w)
    return toks


def money_to_float(s: str) -> Optional[float]:
    m = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)", s or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def pct_values(s: str) -> list:
    return [float(x.replace("%", "").strip()) for x in PCT_RE.findall(s or "")]


def sentences(text: str) -> list:
    text = norm_space(strip_markdown(text))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", text)
    return [p.strip() for p in parts if len(p.strip()) > 2]


def fmt_money(v: float) -> str:
    if v == float("inf"):
        return "and up"
    if v == int(v):
        return f"${int(v):,}"
    return f"${v:,.2f}"


def range_text(lo: Optional[float], hi: Optional[float]) -> str:
    if lo is None and hi is None:
        return ""
    if hi is None or hi == float("inf"):
        return f"{fmt_money(lo)} and up"
    if lo is None or lo <= 0.01:
        return f"up to {fmt_money(hi)}"
    return f"{fmt_money(lo)} to {fmt_money(hi)}"
