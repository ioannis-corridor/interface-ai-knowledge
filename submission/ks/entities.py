"""Prose facts pulled out with regexes: counts, routing number, hours, addresses, closures, awards."""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from .model import Fact
from .text import LONG_DATE_RE, norm_space, parse_long_date, strip_markdown

ORDINALS = "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
DAY_RE = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?"
HOURS_LINE_RE = re.compile(
    rf"^\W*((?:{DAY_RE})(?:\s*[-–—]\s*(?:{DAY_RE}))?)\s*:?\s*(.+?)\W*$", re.I)
ADDRESS_RE = re.compile(r"^\s*(\d{2,5}\s+[A-Z0-9][^,|\n]{3,60}),\s*([A-Z][A-Za-z. ]{2,30}),\s*([A-Z]{2}),?\s*(\d{5})\s*$", re.M)
BRANCH_WORD_RE = re.compile(r"\b([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,2}?)\s+(?:Dupaco\s+)?branch\b")


def _mk(family, product, metric, value, url, sid, authority, quote, label, page_date, fetched, **extra) -> Fact:
    return Fact(family=family, product=product, metric=metric, value=value, url=url, snapshot_id=sid,
                authority=authority, article_date=page_date, fetched_at=fetched, quote=norm_space(quote)[:300],
                label=label, extra=extra)


def _norm_hours(s: str) -> str:
    s = strip_markdown(s).replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\b([ap])\.m\.", r"\1.m.", s, flags=re.I)
    return norm_space(s)


STOP_BRANCH_WORDS = {"dupaco", "the", "a", "new", "newest", "its", "this", "our", "shared", "that", "each", "any",
                     "every", "another", "nearest", "local", "full-service", "credit", "union", "learning", "lab"}


def _clean_branch(name: str) -> Optional[str]:
    words = [w for w in re.split(r"\s+", name.strip()) if w.lower() not in ("branch", "branches")]
    if not words or words[0].lower() in STOP_BRANCH_WORDS:
        return None
    out = []
    for w in words:
        if out and w.lower() == out[-1].lower():
            continue
        out.append(w.title() if w.isupper() else w)
    return " ".join(out)


LOCATED_RE = re.compile(r"The\s+([A-Z][\w'.-]+(?:\s+(?:Avenue|Street|Ave\.?|St\.?|Road|Rd\.?))?)\s+(?:[A-Z][\w'.&-]+\s+){0,3}branch\s+is\s+located\s+at\s+(\d{2,5}\s+[A-Z][^.,\n]{3,60})")


def _branch_name(title: str, text: str) -> Optional[str]:
    m = LOCATED_RE.search(text)
    if m and _clean_branch(m.group(1)):
        return _clean_branch(m.group(1))
    m = re.search(r"The\s+([A-Z][\w'.-]+)\s+(?:[A-Z][\w'.&-]+\s+){0,3}branch\b", text)
    if m and _clean_branch(m.group(1)):
        return _clean_branch(m.group(1))
    m = re.search(r"(?:branch|learning lab)\s+(?:in|at)\s+([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)?)", text)
    if m and _clean_branch(m.group(1)):
        return _clean_branch(m.group(1))
    for blob in (title or "", text[:4000]):
        m = BRANCH_WORD_RE.search(blob)
        if m and _clean_branch(m.group(1)):
            return _clean_branch(m.group(1))
    return None


def extract_entities(markdown: str, url: str, title: str, sid: str, authority: int, page_date: Optional[date],
                     fetched: Optional[date]) -> List[Fact]:
    facts: List[Fact] = []
    text = markdown
    plain = strip_markdown(markdown)

    for m in re.finditer(r"(\d{2})\s+branch(?:\s+office)?\s+locations?", plain):
        facts.append(_mk("entity", "branch count", "count", m.group(1), url, sid, authority,
                         plain[max(0, m.start() - 80):m.end() + 40], "number of branches", page_date, fetched))
    for m in re.finditer(r"(?:over|nearly|more than|approximately|about)\s+(\d{3})\s+employees", plain, re.I):
        facts.append(_mk("entity", "employee count", "count", m.group(1), url, sid, authority,
                         plain[max(0, m.start() - 60):m.end() + 40], "number of employees", page_date, fetched))
    for m in re.finditer(r"assets\s+(?:exceeding|of more than|of over|of)\s+\$(\d(?:\.\d+)?)\s+billion", plain, re.I):
        facts.append(_mk("entity", "total assets", "amount", f"${m.group(1)} billion", url, sid, authority,
                         plain[max(0, m.start() - 60):m.end() + 40], "total assets", page_date, fetched))
    for m in re.finditer(r"(?:more than|over|nearly)\s+(\d{3},\d{3})\s+members|membership has grown to (?:more than|over)\s+(\d{3},\d{3})", plain, re.I):
        facts.append(_mk("entity", "member count", "count", m.group(1) or m.group(2), url, sid, authority,
                         plain[max(0, m.start() - 60):m.end() + 40], "number of members", page_date, fetched))
    for m in re.finditer(rf"\b({ORDINALS})\s+(?:consecutive\s+)?(?:time|year)\s+(?:that\s+)?Forbes", plain, re.I):
        facts.append(_mk("entity", "Forbes recognition", "ordinal", m.group(1).lower(), url, sid, authority,
                         plain[max(0, m.start() - 120):m.end() + 80], "Forbes best-in-state credit union recognition",
                         page_date, fetched))
    for m in re.finditer(r"routing\s+(?:number|#|no\.?)\D{0,40}?(\d{9})\b", plain, re.I):
        facts.append(_mk("entity", "routing number", "id", m.group(1), url, sid, authority,
                         plain[max(0, m.start() - 40):m.end() + 20], "routing number ABA", page_date, fetched))

    # Branch closure announcements: "This location will close March 31, 2026."
    if re.search(r"\bclos(?:e|ure|ing)\b", plain, re.I) and re.search(r"\bbranch\b", plain, re.I):
        for sent in re.split(r"(?<=[.!?])\s+", plain):
            m = re.search(rf"\b(?:will|to|is|be)\s+clos(?:e|ed|ing)\b[^.]{{0,40}}?({LONG_DATE_RE.pattern})", sent, re.I)
            if not m:
                continue
            when = parse_long_date(m.group(1))
            if when and when != page_date:
                branch = _branch_name(title, plain)
                if branch:
                    facts.append(_mk("entity", f"{branch} branch", "close_date", m.group(1), url, sid, authority,
                                     sent, f"{branch} branch closing date", page_date, fetched, branch=branch))
                    break

    # Hours blocks: "**Lobby**" / "**Drive-up**" followed by day lines.
    lines = [line.strip() for line in text.splitlines()]
    branch = None
    for i, line in enumerate(lines):
        m = re.match(r"^\W*(lobby|drive[- ]?(?:up|thru|through))\b\W*(.*)$", strip_markdown(line), re.I)
        if not m:
            continue
        kind = "lobby" if m.group(1).lower().startswith("lobby") else "drive-up"
        parts = []
        rest = m.group(2).strip()
        if rest and HOURS_LINE_RE.match(rest):
            parts.append(rest)
        for j in range(i + 1, min(len(lines), i + 10)):
            s = strip_markdown(lines[j])
            if not s:
                continue
            hm = HOURS_LINE_RE.match(s)
            if hm:
                parts.append(s)
            else:
                break
        if not parts:
            continue
        branch = branch or _branch_name(title, plain) or title.split("|")[0].strip()
        schedule = "; ".join(_norm_hours(p) for p in parts)
        facts.append(_mk("entity", f"{branch} branch", f"hours_{kind.replace('-', '')}", schedule, url, sid, authority,
                         " ".join(parts), f"{branch} branch {kind} hours", page_date, fetched, branch=branch))

    # Street addresses: one per line on the locator page, "located at ..." in releases.
    locator = "/contact" in url or "location" in url
    for i, line in enumerate(lines):
        m = ADDRESS_RE.match(strip_markdown(line))
        if m:
            street, city, state, zipc = (norm_space(g) for g in m.groups())
            context = " ".join(strip_markdown(line) for line in lines[max(0, i - 4):i]).lower()
            is_branch = "dupaco branch" in context or "dupaco credit union" in context
            auth = 100 if (locator and is_branch) else (authority if is_branch or locator else authority - 40)
            facts.append(_mk("entity", f"{city} branch", "address", f"{street}, {city}, {state} {zipc}", url, sid,
                             auth, m.group(0), f"{city} branch address {street}", page_date, fetched,
                             city=city, street=street))
    m = LOCATED_RE.search(plain)
    if m and _clean_branch(m.group(1)):
        b = _clean_branch(m.group(1))
        facts.append(_mk("entity", f"{b} branch", "address", m.group(2), url, sid, authority, m.group(0),
                         f"{b} branch address", page_date, fetched, city=b, street=m.group(2)))
    return facts


# ---------------------------------------------------------------------- prose facts
KV_LINE_RE = re.compile(r"^\s*([A-Za-z][^:|\n]{3,90}?)\s*:\s*(\$\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s?%)\s*\.?\s*$")
RATE_SENT_RE = re.compile(
    r"(\d+)[- ]?(?:month|mo|year|yr)s?\s+(?:share\s+|term[- ]share\s+)?(certificate|cd|certificate special)s?\b[^.%\n]{0,40}?"
    r"\b(apy|apr|dividend rate|rate)\b[^%\n]{0,12}?(\d+\.\d+)\s?%", re.I)
FEE_LINE_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z(][^$|\n]{3,110}?)\s+(?P<value>\$\s?\d[\d,]*(?:\.\d{2})?|Free|No charge)\*?"
    r"(?:\s*(?P<unit>per [A-Za-z/ ]+?|each|for non-members|of (?:the )?amount|plus tax))?\s*\.?\s*$", re.I)
EXPIRED_RE = re.compile(r"\b(offer|promotion|special|promo)\b[^.\n]{0,40}\b(ended|expired|ends|expires|valid through|through)\b[^.\n]{0,30}(\d{4}-\d{2}-\d{2}|" + LONG_DATE_RE.pattern + r"|\d{1,2}/\d{1,2}/\d{2,4})", re.I)


def _family_from_label(label: str) -> Optional[str]:
    low = label.lower()
    if re.search(r"\bfee\b|\bcharge\b|\bcost\b", low):
        return "fee"
    if re.search(r"certificate|\bcd\b|term[- ]share|jumbo", low):
        return "certificate"
    if re.search(r"\bira\b|roth|traditional", low):
        return "ira"
    if "money market" in low:
        return "money_market"
    if "checking" in low:
        return "checking"
    if "savings" in low:
        return "savings"
    if re.search(r"mortgage|home loan|fixed", low):
        return "mortgage"
    if re.search(r"auto|vehicle|car loan", low):
        return "auto"
    if "personal loan" in low:
        return "personal_loan"
    if re.search(r"credit card|visa", low):
        return "credit_card"
    return None


def _metric_from_label(label: str, value: str, family: str) -> str:
    low = label.lower()
    if family == "fee" or value.startswith("$"):
        return "fee"
    if "apy" in low or "yield" in low:
        return "apy"
    if "dividend" in low:
        return "dividend_rate"
    if "apr" in low:
        return "apr"
    return "apy" if family in ("certificate", "ira", "savings", "money_market", "checking", "hsa") else "apr"


def extract_prose_facts(markdown: str, url: str, title: str, sid: str, authority: int, page_date: Optional[date],
                        fetched: Optional[date]) -> List[Fact]:
    """Facts stated in prose: 'Label: value' lines, '6-month certificate APY 2.95%' sentences, fee-schedule lines."""
    from .tables import _term
    facts: List[Fact] = []
    plain_lines = [strip_markdown(line) for line in markdown.splitlines()]
    plain = " ".join(plain_lines)
    auth = authority
    m = EXPIRED_RE.search(plain)
    if m:
        auth = min(auth, 35)          # an expired or dated promotion never beats the live rate sheet
    is_fee_page = bool(re.search(r"fee schedule|service charges|fees and charges", plain, re.I)) or "fee" in (url + title).lower()

    for i, line in enumerate(plain_lines):
        kv = KV_LINE_RE.match(line)
        if kv:
            label, value = norm_space(kv.group(1)), norm_space(kv.group(2)).replace(" %", "%").replace("$ ", "$")
            fam = _family_from_label(label)
            if not fam:
                continue
            metric = _metric_from_label(label, value, fam)
            facts.append(Fact(family=fam, product=re.sub(r"\s*(apy|apr|rate|fee)\s*$", "", label, flags=re.I) or label,
                              metric=metric, value=value, url=url, snapshot_id=sid, authority=auth,
                              term_months=_term(label), jumbo="jumbo" in label.lower(), special="special" in label.lower(),
                              article_date=page_date, fetched_at=fetched, quote=line[:200], label=label))
            continue
        if is_fee_page:
            fee = FEE_LINE_RE.match(line)
            if fee and not re.search(r"effective|schedule|following|subject to|please|charged|we will", line, re.I):
                label = norm_space(fee.group("label")).strip(" -–:")
                if i > 0 and plain_lines[i - 1] and not FEE_LINE_RE.match(plain_lines[i - 1]) and \
                        (label[0] == "(" or label[0].islower()) and len(plain_lines[i - 1]) < 90:
                    label = norm_space(plain_lines[i - 1] + " " + label)
                value = norm_space(fee.group("value")).replace("$ ", "$")
                unit = norm_space(fee.group("unit") or "")
                if len(label) < 4 or re.search(r"^\d|^\$", label):
                    continue
                facts.append(Fact(family="fee", product=label, metric="fee", value=value + (f" {unit}" if unit else ""),
                                  url=url, snapshot_id=sid, authority=auth, article_date=page_date, fetched_at=fetched,
                                  quote=line[:200], label=label, business="business" in label.lower()))

    for m in RATE_SENT_RE.finditer(plain):
        term = int(m.group(1))
        if re.search(r"year|yr", m.group(0)[:12], re.I):
            term *= 12
        metric = {"apy": "apy", "apr": "apr", "dividend rate": "dividend_rate", "rate": "apy"}[m.group(3).lower()]
        sent_auth = auth
        window = plain[max(0, m.start() - 80): m.end() + 120]
        if EXPIRED_RE.search(window) or re.search(r"\b(ended|expired|was|were|previous|old)\b", window, re.I):
            sent_auth = min(sent_auth, 30)
        special = "special" in window.lower()
        facts.append(Fact(family="certificate", product=f"{term} Month Certificate" + (" Special" if special else ""),
                          metric=metric, value=f"{m.group(4)}%", url=url, snapshot_id=sid, authority=sent_auth,
                          term_months=term, special=special, jumbo="jumbo" in window.lower(),
                          article_date=page_date, fetched_at=fetched, quote=norm_space(m.group(0))[:200],
                          label=norm_space(m.group(0))))
    return facts
