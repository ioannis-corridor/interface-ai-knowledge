"""Markdown rate tables -> Facts. Every row becomes one fact per numeric column."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from .model import INF, Fact, canonical_product
from .pages import is_business, url_family
from .text import clean_cell, money_to_float, norm_space, parse_effective, strip_markdown

ROLE_PATTERNS = [
    ("product", r"account type|^certificate$|ira type|card type|^product$|^program$|^account$"),
    ("tier", r"balance tier|^balance$|loan program|loan type|loan amount|^amount$"),
    ("term", r"^term$|^terms$"),
    ("dividend_rate", r"dividend rate"),
    ("apy", r"annual percentage yield|\bapy\b"),
    ("apr", r"annual percentage rate|\bapr\b"),
    ("rate", r"^rate$|interest rate"),
    ("points", r"\bpoints?\b"),
    ("min_open", r"min\.? to open|minimum to open|minimum opening"),
    ("min_earn", r"min\.? to earn|minimum to earn|minimum balance"),
    ("payment", r"payment"),
]
NUMERIC_ROLES = {"dividend_rate", "apy", "apr", "rate", "points", "min_open", "min_earn", "payment"}
MONTH_TERM_RE = re.compile(r"(\d+)\s*[- ]?\s*(?:month|months|mo)\b", re.I)
YEAR_TERM_RE = re.compile(r"(\d+)\s*[- ]?\s*(?:year|years|yr)\b", re.I)
MODEL_YEAR_RE = re.compile(r"(20\d\d)\s*[-–]\s*(\d{2,4})\s*model year|model year\s*(20\d\d)\s*[-–]\s*(\d{2,4})", re.I)
OLDER_RE = re.compile(r"(20\d\d)\s*model year\s*\(?and older", re.I)
RANGE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*[-–]\s*\$?\s?([\d,]+(?:\.\d+)?)")
PLUS_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*\+")
OR_LESS_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*or less", re.I)


@dataclass
class Table:
    header: List[str]
    rows: List[List[str]]
    label: str
    section: str
    effective: Optional[date]
    raw: str


def _split_row(line: str) -> List[str]:
    return [clean_cell(c) for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{2,}", line)) and set(line.strip()) <= set("|-: ")


def _context_above(lines: List[str], start: int) -> Tuple[str, str]:
    label, section = "", ""
    for i in range(start - 1, max(-1, start - 30), -1):
        s = lines[i].strip()
        if not s or s.startswith("|") or s.startswith("![") or s.startswith("<"):
            continue
        low = s.lower()
        if low.startswith("rates are effective") or "subject to change" in low:
            continue
        link_item = re.match(r"^-\s*\[([^\]]+)\]\(", s)
        heading = re.match(r"^#{1,6}\s*(.+)$", s)
        if link_item:
            cand = norm_space(link_item.group(1))
            if (label and not section) or (not label and "rate" in cand.lower()):
                section = cand
            continue
        if heading:
            cand = strip_markdown(heading.group(1))
            if label and not section:
                section = cand
                break
            if not label and len(cand) < 60:
                label = cand
            continue
        if "](" in s or len(s) > 70 or s.endswith(("?", ".", "!")) or s.startswith(("-", "*", "[", "_")):
            only_links = "](" in s and re.sub(r"\[[^\]]*\]\([^)]*\)", "", s).strip() == ""
            if only_links or not label:
                continue  # a row of CTA links, or prose above a table that has no label yet
            break
        cand = clean_cell(s)
        if not label:
            label = cand
        elif not section:
            section = cand
            break
    return label, section


def _effective_below(lines: List[str], end: int) -> Optional[date]:
    seen = 0
    for i in range(end, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("|"):
            break
        d = parse_effective(s)
        if d:
            return d
        seen += 1
        if seen >= 6:
            break
    return None


def parse_tables(markdown: str) -> List[Table]:
    lines = markdown.splitlines()
    out: List[Table] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            block = lines[i:j]
            if len(block) >= 3 and _is_separator(block[1]):
                header = _split_row(block[0])
                rows = [r for r in (_split_row(ln) for ln in block[2:]) if any(c for c in r)]
                label, section = _context_above(lines, i)
                out.append(Table(header, rows, label, section, _effective_below(lines, j), "\n".join(block)))
            i = j
        else:
            i += 1
    return out


def _roles(header: List[str]) -> dict:
    roles = {}
    for idx, h in enumerate(header):
        hl = re.sub(r"(?<=[a-zA-Z)])\d\b", "", h).lower().strip()
        for role, pat in ROLE_PATTERNS:
            if re.search(pat, hl) and role not in roles.values():
                roles[idx] = role
                break
    return roles


def detect_family(label: str, section: str, product: str, tier: str, header: str, url: str) -> Optional[str]:
    """The table's own label and cells decide first; the section heading above is only a fallback."""
    fam = _detect_family(" ".join([label, product, header]).lower(), product, tier, label, url, use_url=False)
    if fam:
        return fam
    return _detect_family(" ".join([label, section, product, header]).lower(), product, tier, label + " " + section, url, use_url=True)


def _detect_family(blob: str, product: str, tier: str, label_blob: str, url: str, use_url: bool) -> Optional[str]:
    prod = product.lower()
    if "ira" in blob.split() or "ira type" in blob or re.search(r"\b(roth|traditional)\b", prod):
        return "ira"
    if "certificate" in blob or "term-share" in blob or re.search(r"^\d+\s*month\b", prod) or "jumbo" in prod:
        return "certificate"
    if "money market" in blob or "investor" in blob:
        return "money_market"
    if "health savings" in blob or re.search(r"\bhsa\b", blob):
        return "hsa"
    if "checking" in blob:
        return "checking"
    if "card type" in blob or "visa" in blob or "credit card" in blob:
        return "credit_card"
    if "model year" in (tier + " " + prod).lower():
        low = label_blob.lower()
        if re.search(r"\b(boat|rv|camper|recreational)\b", low):
            return "boat_rv"
        if re.search(r"\b(atv|snowmobile|jet ski|utv)\b", low):
            return "atv"
        return "auto"
    if re.search(r"purchase:|refinance:|fixed conventional|home loans|mortgage", blob):
        return "mortgage"
    if re.search(r"\bheloc\b|line of credit", blob):
        return "heloc"
    if "home equity" in blob:
        return "home_equity_loan"
    if "home improvement" in blob:
        return "home_improvement"
    if "personal loan" in blob:
        return "personal_loan"
    if re.search(r"\b(boat|rv|recreational)\b", blob):
        return "boat_rv"
    if re.search(r"\b(atv|snowmobile|jet ski)\b", blob):
        return "atv"
    if "savings" in blob or "holiday club" in blob or "launchpad" in blob:
        return "savings"
    if not use_url:
        return None
    hint = url_family(url)
    if hint == "deposit":
        return "savings"
    if hint in ("auto", "mortgage", "heloc", "home_equity_loan", "home_improvement", "personal_loan", "credit_card", "checking", "ira"):
        return hint
    return None


def _term(*texts: str) -> Optional[int]:
    for t in texts:
        m = MONTH_TERM_RE.search(t or "")
        if m:
            return int(m.group(1))
        m = YEAR_TERM_RE.search(t or "")
        if m:
            return int(m.group(1)) * 12
    return None


def _model_years(text: str) -> Optional[Tuple[int, int]]:
    m = MODEL_YEAR_RE.search(text or "")
    if m:
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        lo, hi = int(a), int(b)
        if hi < 100:
            hi += 2000
        return (min(lo, hi), max(lo, hi))
    m = OLDER_RE.search(text or "")
    if m:
        return (0, int(m.group(1)))
    return None


def _money_range(text: str) -> Optional[Tuple[float, float]]:
    t = (text or "").replace("–", "-")
    m = RANGE_RE.search(t)
    if m:
        return (money_to_float(m.group(1)), money_to_float(m.group(2)))
    m = PLUS_RE.search(t)
    if m:
        return (money_to_float(m.group(1)), INF)
    m = OR_LESS_RE.search(t)
    if m:
        return (0.0, money_to_float(m.group(1)))
    m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)\s*-\s*([\d,]+(?:\.\d+)?)", t)
    if m:
        return (money_to_float(m.group(1)), money_to_float(m.group(2)))
    return None


# Tables that belong on a page of this family (an auto table on the checking page is off topic and loses authority).
RELATED_FAMILIES = {
    "deposit": {"savings", "money_market", "hsa", "certificate", "ira"},
    "ira": {"ira", "certificate", "savings"},
    "mortgage": {"mortgage", "heloc", "home_equity_loan", "home_improvement"},
    "home_equity_loan": {"home_equity_loan", "heloc", "mortgage", "home_improvement"},
}
OFF_TOPIC_PENALTY = 40


def _off_topic(page_family: Optional[str], family: str) -> bool:
    if not page_family or page_family in ("business", "contact"):
        return False
    return family not in RELATED_FAMILIES.get(page_family, {page_family})


def _cell(row: List[str], index: Optional[int]) -> str:
    return row[index] if index is not None and index < len(row) else ""


def _value_text(cell: str) -> str:
    v = norm_space(re.sub(r"\b(APR|APY)\b", "", cell).replace(" %", "%"))
    m = re.match(r"(\d+(?:\.\d+)?%)(\s*-\s*\d+(?:\.\d+)?%)?", v)
    return m.group(0) if m else v


def _has_number(cell: str) -> bool:
    return bool(re.search(r"\d", cell or "")) and cell.strip() not in ("—", "-", "–")


def table_to_facts(table: Table, url: str, snapshot_id: str, authority: int, page_date: Optional[date],
                   fetched_at: Optional[date]) -> List[Fact]:
    roles = _roles(table.header)
    header_text = " ".join(table.header)
    product_col = next((i for i, r in roles.items() if r == "product"), None)
    tier_col = next((i for i, r in roles.items() if r == "tier"), None)
    term_col = next((i for i, r in roles.items() if r == "term"), None)
    first_cells = " ".join(r[0] for r in table.rows[:3] if r)
    if product_col is None and term_col == 0 and re.search(r"month|year|special|jumbo", first_cells, re.I):
        product_col, term_col = 0, None
    if product_col is None and 0 not in roles and first_cells and not re.search(r"[\d$%]", first_cells):
        product_col = 0
    if not any(r in roles.values() for r in ("dividend_rate", "apy", "apr", "rate")):
        return []
    facts: List[Fact] = []
    page_family = url_family(url)
    business_page = is_business(url)
    for row in table.rows:
        if len(row) < 2:
            continue
        product_text, tier_text, term_text = (_cell(row, product_col), _cell(row, tier_col), _cell(row, term_col))
        family = detect_family(table.label, table.section, product_text, tier_text, header_text, url)
        if not family:
            continue
        label = table.label
        if re.search(r"\brates?\b", label, re.I) or label.lower() in ("special", "regular", "specials"):
            label = re.sub(r"\s*\brates?\b\s*$", "", table.section or table.label, flags=re.I)
        product = product_text or label or family
        if family in ("auto", "boat_rv", "atv"):
            product = {"auto": "Auto & Motorcycle Loan", "boat_rv": "Boat & RV Loan", "atv": "ATV, Snowmobile & Jet Ski Loan"}[family]
        if family == "credit_card":
            product = re.sub(r"\s*\brate\b\s*$", "", product, flags=re.I)
            if table.label and "visa" in table.label.lower() and "introductory" not in product.lower() \
                    and product.lower() not in table.label.lower():
                product = table.label
        product = canonical_product(norm_space(product), family)
        low_prod, low_label = product.lower(), (table.label + " " + table.section).lower()
        business = business_page or "business" in low_prod or "business" in low_label
        if business and family == "credit_card" and "business" not in low_prod:
            product = "Business " + product
        term = _term(term_text, product_text, tier_text)
        model_years = _model_years(tier_text) or _model_years(product_text)
        rng = _money_range(tier_text) or (_money_range(product_text) if family in ("mortgage", "ira") else None)
        balance = rng if family in ("savings", "money_market", "hsa", "checking", "ira") else None
        amount = rng if family not in ("savings", "money_market", "hsa", "checking", "ira") else None
        if family == "ira" and rng and not term:
            balance = rng
        ira_type = None
        m = re.match(r"\s*(roth|traditional)\b", low_prod)
        if m:
            ira_type = m.group(1)
        purpose = None
        m = re.match(r"\s*(purchase|refinance)\b", low_prod)
        if m:
            purpose = m.group(1)
        elif family == "mortgage" and "refinance" in low_label:
            purpose = "refinance"
        elif family == "mortgage" and "purchase" in low_label:
            purpose = "purchase"
        auth = authority - (OFF_TOPIC_PENALTY if _off_topic(page_family, family) else 0)
        quote = " | ".join(c for c in row if c)
        for idx, role in roles.items():
            if role not in NUMERIC_ROLES or idx >= len(row) or not _has_number(row[idx]):
                continue
            metric = role
            cell_text = row[idx]
            if "APR" in cell_text.upper() and metric in ("apy", "rate"):
                metric = "apr"
            if "APY" in cell_text.upper() and metric in ("apr", "rate"):
                metric = "apy"
            value = _value_text(cell_text)
            if metric in ("apy", "apr", "rate", "dividend_rate") and "%" not in value and re.fullmatch(r"[\d.]+", value):
                value += "%"
            facts.append(Fact(
                family=family, product=product, metric=metric, value=value, url=url,
                snapshot_id=snapshot_id, authority=auth, term_months=term, model_years=model_years,
                balance=balance, amount=amount, jumbo="jumbo" in low_prod, special="special" in low_prod,
                ira_type=ira_type, purpose=purpose, intro="introductory" in low_prod or "intro " in low_prod,
                business=business, effective=table.effective, article_date=page_date, fetched_at=fetched_at,
                quote=quote, label=norm_space(f"{table.section} {table.label} {product} {tier_text} {term_text}"),
                extra={"table": id(table), "raw_label": table.label},
            ))
    return facts


GENERIC_LABEL_RE = re.compile(
    r"^(?:(?:dupaco )?(?:checking|savings|money market|certificates?|hsa|health savings|share)(?: accounts?)?(?: rates?)?|rates?|account rates?)$", re.I)


def rename_generic_products(facts: List[Fact]) -> None:
    """A table labelled just 'Checking Accounts' on a promo page is the same product as the authoritative table
    with the same balance tiers. Give it that product's name so the two can be compared."""
    from collections import defaultdict
    by_family: dict = defaultdict(list)
    for f in facts:
        if f.balance and f.family in ("checking", "savings", "money_market", "hsa"):
            by_family[f.family].append(f)
    for fs in by_family.values():
        sig_products: dict = defaultdict(set)
        per_table: dict = defaultdict(set)
        for f in fs:
            per_table[(f.url, f.extra.get("table"), f.product)].add(f.balance)
        authoritative = {g.product for g in fs if g.authority >= 85}
        for (_url, _tid, product), sig in per_table.items():
            if not GENERIC_LABEL_RE.match(product) and product in authoritative:
                sig_products[frozenset(sig)].add(product)
        for f in fs:
            if GENERIC_LABEL_RE.match(f.product):
                sig = frozenset(per_table[(f.url, f.extra.get("table"), f.product)])
                cands = sig_products.get(sig, set())
                if len(cands) == 1:
                    f.product = next(iter(cands))
