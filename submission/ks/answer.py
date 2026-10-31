"""Compose answers from facts and chunks. Every number in an answer comes from a Fact or a quoted sentence."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

from .model import FAMILY_NAMES, Fact, INF
from .pages import CALCULATOR, FILE, LANDING, OTHER, url_key
from .store import FactStore, best_of, group_values
from .text import fmt_money, numbers_in, pct_values, range_text, sentences, tokenize

DEPOSIT = {"certificate", "ira", "savings", "money_market", "hsa", "checking"}
PRIMARY_METRIC = {f: "apy" for f in DEPOSIT}
PRIMARY_METRIC.update({"mortgage": "rate", "credit_card": "apr"})
NO_RATE_FAMILIES = {"construction", "student_loan"}
US_STATES = ("Iowa|Illinois|Wisconsin|Minnesota|Missouri|Nebraska|South Dakota|North Dakota|Kansas|Indiana|Michigan|"
             "Ohio|Kentucky|Arizona|Texas|California|Florida|New York|Colorado")

REFUSE_RATE = "The website doesn't list a rate for {thing}. Please contact {org} for current terms."
REFUSE_FEE = "The website's fee schedule doesn't list a fee for {thing}. Please contact {org} to confirm."
REFUSE_GENERIC = "I don't know; the website doesn't say. Please contact {org} for help with that."
REFUSE_BRANCH = "The website doesn't list {what} for the {branch} branch. Please contact {org} or check the branch locator on the contact page."
NOT_YET = "That product isn't listed on the website as of that date. Please contact {org} for details."


class Source:
    def __init__(self, url: str, snapshot_id: str, quote: str = ""):
        self.url, self.snapshot_id, self.quote = url, snapshot_id, quote


class Draft:
    """Internal answer before the final validation step."""

    def __init__(self, text: str, facts: List[Fact] = None, urls: List[Tuple[str, str]] = None, confident: bool = True,
                 conflict_note: Optional[str] = None, allowed_numbers: Optional[set] = None):
        self.text = text
        self.facts = facts or []
        self.urls = urls or []           # (url, quote)
        self.confident = confident
        self.conflict_note = conflict_note
        self.allowed_numbers = allowed_numbers


def _plain(s: str) -> str:
    s = re.sub(r"[*_`#<>\[\]]+", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _metric_word(metric: str) -> str:
    return {"apy": "APY", "dividend_rate": "dividend rate", "apr": "APR", "rate": "rate"}.get(metric, metric)


def _years_text(my: Tuple[int, int]) -> str:
    lo, hi = my
    return f"{hi} and older model years" if lo == 0 else f"{lo}-{hi} model years"


def _term_text(months: Optional[int]) -> str:
    if not months:
        return ""
    if months % 12 == 0 and months >= 120:
        return f"{months // 12}-year"
    return f"{months}-month"


def _tier_phrase(f: Fact) -> str:
    bits = []
    if f.model_years:
        bits.append(_years_text(f.model_years))
    if f.balance:
        lo, hi = f.balance
        bits.append(f"balances of {fmt_money(lo)} and up" if hi == INF else f"balances {range_text(lo, hi)}")
    if f.amount:
        lo, hi = f.amount
        bits.append(f"loan amounts of {fmt_money(lo)} and up" if hi == INF else f"loan amounts {range_text(lo, hi)}")
    return ", ".join(bits)


def _product_name(f: Fact) -> str:
    p = f.product
    if f.family == "certificate" and re.fullmatch(r"\d+ Month Certificate", p):
        return p.replace(" Month ", "-month ").lower()
    return p


class Composer:
    def __init__(self, store: FactStore, index, pages: Dict[str, Dict[str, dict]]):
        self.store = store
        self.index = index
        self.pages = pages          # sid -> url -> {"title","links","class"}
        self.org = "the credit union"

    # ------------------------------------------------------------------ helpers
    def _facts(self, sid: str, family: str, pred=None) -> List[Fact]:
        return self.store.find(sid, family, pred)

    def _companions(self, sid: str, f: Fact, metric: str) -> Optional[Fact]:
        """Same row, other metric (dividend rate for an APY, APR for a mortgage rate)."""
        same = [g for g in self.store.find(sid, f.family) if g.url == f.url and g.quote == f.quote and g.metric == metric]
        return same[0] if same else None

    def _sources(self, facts: List[Fact], limit: int = 4) -> List[Tuple[str, str]]:
        seen, out = set(), []
        for f in sorted(facts, key=lambda x: (-x.authority, x.url)):
            k = url_key(f.url)
            if k in seen:
                continue
            seen.add(k)
            out.append((f.url, f.quote[:200]))
            if len(out) >= limit:
                break
        return out

    def _resolve(self, facts: List[Fact]) -> Tuple[Optional[Fact], List[Fact], Optional[str]]:
        """Pick the winning fact among facts for ONE tier; report disagreeing lower-authority copies."""
        if not facts:
            return None, [], None
        win = best_of(facts)
        agree = [f for f in facts if f.value == win.value]
        others = group_values([f for f in facts if f.value != win.value])
        note = None
        if others:
            parts = [f"{v} on {', '.join(sorted({url_key(g.url) for g in gs}))}" for v, gs in others.items()]
            note = (f"Sources disagree: {win.value} on {url_key(win.url)} is used because that page is the most "
                    f"authoritative and most recently effective; other copies show {'; '.join(parts)}.")
        return win, agree, note

    # ------------------------------------------------------------------ entity answers
    def answer_entity(self, q, sid: str, ref_date: date) -> Optional[Draft]:
        ent = q.entity
        facts = self._facts(sid, "entity")
        if ent == "routing":
            fs = [f for f in facts if f.metric == "id"]
            win = best_of(fs)
            if not win:
                return None
            return Draft(f"{self.org}'s routing number is {win.value}.", [win], self._sources(fs))
        if ent in ("branch_count", "employee_count", "member_count", "assets"):
            product = {"branch_count": "branch count", "employee_count": "employee count",
                       "member_count": "member count", "assets": "total assets"}[ent]
            fs = [f for f in facts if f.product == product]
            if not fs:
                return None
            win = max(fs, key=lambda f: (f.article_date or date.min, f.authority))
            same = [f for f in fs if f.value == win.value]
            noun = {"branch_count": "branch office locations", "employee_count": "employees",
                    "member_count": "members", "assets": "in assets"}[ent]
            lead = "more than " if ent in ("member_count", "assets") else ""
            text = f"{self.org} has {lead}{win.value} {noun}, according to its most recent news release."
            others = sorted({f.value for f in fs if f.value != win.value})
            note = f"Older releases quote {', '.join(others[:4])}; the newest release is used." if others else None
            return Draft(text, same, self._sources(same, 3), conflict_note=note)
        if ent == "forbes":
            fs = [f for f in facts if f.product == "Forbes recognition"]
            if not fs:
                return None
            win = max(fs, key=lambda f: (f.article_date or date.min, f.authority))
            text = (f"Forbes has named {self.org} one of the best credit unions in its state; the most recent announcement "
                    f"says this was the {win.value} time Forbes recognized {self.org}.")
            return Draft(text, [win], self._sources([win]))
        if ent in ("hours_lobby", "hours_driveup"):
            kind = "lobby" if ent == "hours_lobby" else "drive-up"
            fs = [f for f in facts if f.metric == ent]
            if q.branch:
                mine = [f for f in fs if _branch_match(q.branch, f)]
                if not mine:
                    return Draft(REFUSE_BRANCH.format(what=f"{kind} hours", branch=q.branch, org=self.org), confident=False)
                win = max(mine, key=lambda f: (f.article_date or date.min, f.authority))
                return Draft(f"{q.branch} branch {kind} hours: {win.value}.", [win], self._sources(mine, 2))
            if not fs:
                return None
            counts = Counter(f.value for f in fs)
            top, seen_times = [], set()
            for v, _ in counts.most_common():
                times = set(re.findall(r"\d{1,2}(?::\d{2})? ?[ap]\.m\.|noon|midnight", v, re.I))
                if not top or (times - seen_times):
                    top.append(v)
                    seen_times |= times
                if len(top) >= 4:
                    break
            if q.intent == "aggregate":
                lead = f"No, {kind} hours vary by branch. "
            else:
                lead = f"{kind.capitalize()} hours vary by branch. "
            lines = [f"Most branches: {top[0]}"] + [f"Some branches: {v}" for v in top[1:]]
            text = lead + "; ".join(lines) + ". Which branch are you asking about?"
            used = [f for f in fs if f.value in top]
            urls = self._sources(used, 3)
            contact = _pick_url(self.pages.get(sid, {}), ["/contact"])
            if contact:
                urls.insert(0, (contact, "Branch locator"))
            return Draft(text, used, urls)
        if ent == "eligibility":
            return self._eligibility(sid)
        if ent == "account_howto":
            return self._account_howto(q, sid)
        if ent == "address":
            fs = [f for f in facts if f.metric == "address"]
            if not q.branch:
                return None
            mine = [f for f in fs if _branch_match(q.branch, f)]
            if not mine:
                return Draft(REFUSE_BRANCH.format(what="an address", branch=q.branch, org=self.org), confident=False)
            win = max(mine, key=lambda f: (f.authority, f.article_date or date.min, len(f.value)))
            urls = self._sources(mine, 2)
            contact = _pick_url(self.pages.get(sid, {}), ["/contact"])
            if contact and all(url_key(u) != url_key(contact) for u, _ in urls):
                urls.append((contact, "Branch locator"))
            return Draft(f"The {q.branch} branch is at {win.value}.", [win], urls)
        if ent == "closure":
            fs = [f for f in facts if f.metric == "close_date"]
            mine = [f for f in fs if q.branch and _branch_match(q.branch, f)] if q.branch else []
            if not mine:
                if q.branch:
                    return Draft(f"The website doesn't mention a closing for the {q.branch} branch. "
                                 f"Please contact {self.org} to confirm.", confident=False)
                return None
            win = max(mine, key=lambda f: (f.article_date or date.min, f.authority))
            from .text import parse_long_date
            when = parse_long_date(win.value)
            alt = self._closure_alternatives(sid, win)
            if re.search(r"still open|open today|is it open|remain open", q.raw, re.I):
                if when and when <= ref_date:
                    text = f"No. The {q.branch} branch was scheduled to close {win.value}."
                else:
                    text = f"The {q.branch} branch is scheduled to close {win.value}."
            else:
                text = f"The {q.branch} branch was scheduled to close {win.value}."
            if alt:
                text += f" Members can use the {alt} branches instead."
            return Draft(text, [win], self._sources([win]))
        return None

    def _eligibility(self, sid: str) -> Optional[Draft]:
        """Membership eligibility: the 'who can join' bullets plus the states served, from the join page."""
        pages = self.pages.get(sid, {})
        best = None
        for url, meta in pages.items():
            text = meta.get("text", "")
            m = re.search(r"(?:eligible to join|who can join|eligible for membership|membership eligibility)(.{0,900})", text, re.I)
            if not m:
                continue
            rank = (bool(re.search(r"join|membership", url, re.I)), meta.get("class", 0))
            if best is None or rank > best[0]:
                best = (rank, url, m.group(1), text)
        if not best:
            return None
        _, url, tail, text = best
        bullets = [b.strip(" .") for b in re.split(r"\s+-\s+", tail) if 15 < len(b.strip()) < 160][:5]
        bullets = [re.sub(r"[!?].*$", "", b) for b in bullets
                   if re.search(r"\b(live|work|family|member|belong|reside|employ|attend|worship)\b", b, re.I)
                   and not re.search(r"\b(apply|open|start|learn more|sound like)\b", b, re.I)]
        states = re.search(rf"((?:{US_STATES}),?\s+(?:and\s+)?(?:{US_STATES}),?\s+(?:and\s+)?(?:{US_STATES})(?:,?\s+(?:and\s+)?(?:{US_STATES}))*)", text)
        parts = []
        if bullets:
            parts.append(f"You're eligible to join {self.org} if " + "; or ".join(b[0].lower() + b[1:] for b in bullets) + ".")
        if states:
            parts.append(f"{self.org}'s charter area covers counties in {states.group(1).strip()}.")
        if not parts:
            return None
        return Draft(" ".join(parts), urls=[(url, tail[:200])])

    def _account_howto(self, q, sid: str) -> Optional[Draft]:
        """Account-maintenance how-to: point to online banking and the member phone line, both from the contact page."""
        pages = self.pages.get(sid, {})
        contact = _pick_url(pages, ["/contact"])
        if not contact:
            return None
        text = pages[contact].get("text", "")
        phone = re.search(r"\b8\d\d-\d{3}-\d{4}\b", text)
        shine = re.search(r"(Shine (?:Online|Mobile)[^.]{0,80}\.)", text)
        what = re.search(r"(contact information|contact info|address|phone number|email address|e-mail|name|beneficiar\w+)", q.raw, re.I)
        thing = what.group(1).lower() if what else "account details"
        bits = [f"You can update your {thing} by logging in to Shine Online or Mobile Banking"]
        if shine:
            bits[0] += " (use the Contact Us tab for account-specific requests)"
        if phone:
            bits.append(f"or by calling {self.org} at {phone.group(0)}")
        return Draft(", ".join(bits) + ".", urls=[(contact, (shine.group(1) if shine else text[:160]))])

    def _closure_alternatives(self, sid: str, f: Fact) -> Optional[str]:
        page = self.pages.get(sid, {}).get(f.url)
        if not page:
            return None
        m = re.search(r"full-service branches at ([A-Z][\w ]+?) and ([A-Z][\w ]+?)[,.”\"]", page.get("text", ""))
        return f"{m.group(1).strip()} and {m.group(2).strip()}" if m else None

    # ------------------------------------------------------------------ fact answers
    def _candidates(self, q, sid: str) -> Tuple[List[Fact], str]:
        fam = q.family
        metric = q.metric if q.metric in ("apy", "dividend_rate", "apr", "rate") else None
        prim = PRIMARY_METRIC.get(fam, "apr")
        pool = self._facts(sid, fam)
        avail = {f.metric for f in pool}
        if metric not in avail:
            metric = prim if prim in avail else (next(iter(m for m in ("apy", "apr", "rate") if m in avail), None))
        if metric is None:
            return [], prim
        c = [f for f in pool if f.metric == metric]
        if q.business is True:
            bus = [f for f in c if f.business]
            c = bus or c
        else:
            non = [f for f in c if not f.business]
            c = non or c
        if q.product:
            mine = [f for f in c if _product_match(q.product, f.product)]
            c = mine
        if fam == "mortgage":
            arm = re.search(r"\barm\b|adjustable", q.raw, re.I)
            if arm:
                c = [f for f in c if re.search(r"\barm\b|adjustable", f.product, re.I)]
            else:
                c = [f for f in c if not re.search(r"\barm\b|adjustable", f.product, re.I)]
            if q.purpose:
                c = [f for f in c if f.purpose == q.purpose]
            elif any(f.purpose == "purchase" for f in c):
                c = [f for f in c if f.purpose in ("purchase", None)]
        if q.term_months is not None:
            c = [f for f in c if f.term_months == q.term_months]
        if q.model_year is not None:
            c = [f for f in c if f.model_years and (f.model_years[0] <= q.model_year <= f.model_years[1] or
                                                    (f.model_years[0] == 0 and q.model_year <= f.model_years[1]))]
        if q.balance is not None:
            c = [f for f in c if f.balance and f.balance[0] <= q.balance <= f.balance[1]]
        if q.amount is not None and any(f.amount for f in c):
            inside = [f for f in c if f.amount and f.amount[0] <= q.amount <= f.amount[1]]
            if inside:
                smallest = min(f.amount[1] for f in inside)
                c = [f for f in inside if f.amount[1] == smallest]
        if q.jumbo is not None:
            c = [f for f in c if f.jumbo == q.jumbo]
        if q.special is not None:
            c = [f for f in c if f.special == q.special]
        if q.ira_type:
            c = [f for f in c if f.ira_type in (q.ira_type, None)]
        if q.intro is not None:
            c = [f for f in c if f.intro == q.intro]
        elif fam == "credit_card":
            c = [f for f in c if not f.intro] or c
        # Calculators, promo landing pages and files only count when nothing better exists.
        if any(f.authority >= 85 for f in c):
            self._dropped = [f for f in c if f.authority < 60]
            c = [f for f in c if f.authority >= 60]
        else:
            self._dropped = []
        return c, metric

    _dropped: List[Fact] = []

    def _stale_note(self, win: Fact) -> Optional[str]:
        stale = [f for f in self._dropped if f.value != win.value and
                 (f.term_months == win.term_months) and (f.metric == win.metric)]
        if not stale:
            return None
        vals = sorted({f.value for f in stale})
        pages = sorted({url_key(f.url) for f in stale})
        return (f"Other pages ({', '.join(pages)}) still show {', '.join(vals)}; the rate page "
                f"({url_key(win.url)}) is authoritative and current.")

    def answer_fact(self, q, sid: str, exact: bool) -> Draft:
        fam = q.family
        thing = _thing(q)
        if fam == "fee":
            return self.answer_fee(q, sid)
        if fam in NO_RATE_FAMILIES or fam is None:
            return Draft(REFUSE_RATE.format(thing=thing, org=self.org), confident=False)
        cands, metric = self._candidates(q, sid)
        if not cands:
            latest_c, _ = self._candidates(q, self.store.latest) if sid != self.store.latest else ([], None)
            if latest_c:
                return Draft(NOT_YET.format(org=self.org), confident=False)
            return Draft(REFUSE_RATE.format(thing=thing, org=self.org), confident=False)
        tiers: Dict[tuple, List[Fact]] = defaultdict(list)
        for f in cands:
            tiers[f.soft_key()].append(f)
        pinned = q.model_year is not None or q.balance is not None or q.amount is not None
        if len(tiers) > 1 and pinned:
            win = best_of(cands)
            keep = tiers[win.soft_key()]
            losers = [f for f in cands if f.soft_key() != win.soft_key() and f.value != win.value]
            win2, agree, note = self._resolve(keep)
            if losers and not note:
                vals = sorted({f.value for f in losers})
                pages = sorted({url_key(f.url) for f in losers})
                note = (f"Other pages ({', '.join(pages)}) still show {', '.join(vals)} for an older tier table; "
                        f"the rate page is authoritative.")
            return self._single(q, sid, win2, agree, note or self._stale_note(win2), metric)
        if len(tiers) == 1:
            win, agree, note = self._resolve(cands)
            return self._single(q, sid, win, agree, note or self._stale_note(win), metric)
        if q.intent == "superlative" or q.superlative:
            return self._superlative(q, sid, tiers, metric)
        return self._multi(q, sid, tiers, metric)

    def _single(self, q, sid: str, win: Fact, agree: List[Fact], note: Optional[str], metric: str) -> Draft:
        name = _product_name(win)
        tier = _tier_phrase(win)
        term = _term_text(win.term_months) if win.term_months and not re.search(r"\d+[- ]?month|\d+[- ]?year", name, re.I) else ""
        desc = " ".join(x for x in [term, name] if x)
        value = f"{win.value} {_metric_word(metric)}"
        comp = None
        if win.family in DEPOSIT and metric == "apy":
            comp = self._companions(sid, win, "dividend_rate")
        elif win.family in DEPOSIT and metric == "dividend_rate":
            comp = self._companions(sid, win, "apy")
        elif win.family == "mortgage" and metric == "rate":
            comp = self._companions(sid, win, "apr")
        extra = f" ({comp.value} {_metric_word(comp.metric)})" if comp and comp.value != win.value else ""
        if win.family in ("auto", "atv", "boat_rv"):
            text = f"The {term} {FAMILY_NAMES.get(win.family, win.family)} APR for {tier} is {win.value}."
        elif win.family == "credit_card":
            kind = "introductory balance-transfer" if win.intro else "standard"
            text = f"The {name} {kind} APR is {win.value}, based on creditworthiness."
        elif tier:
            text = f"{desc} pays {value}{extra} for {tier}." if win.family in DEPOSIT else \
                f"The {desc} {_metric_word(metric)} is {value}{extra} for {tier}."
        else:
            text = f"{desc} pays {value}{extra}." if win.family in DEPOSIT else f"The {desc} {_metric_word(metric)} is {value}{extra}."
        facts = agree + ([comp] if comp else [])
        return Draft(_tidy(text), facts, self._sources(agree), conflict_note=note)

    def _superlative(self, q, sid: str, tiers: Dict[tuple, List[Fact]], metric: str) -> Draft:
        rows = []
        for key, fs in tiers.items():
            win, agree, _ = self._resolve(fs)
            vals = pct_values(win.value)
            if vals:
                rows.append((max(vals) if q.superlative == "max" else min(vals), win, agree))
        if not rows:
            return self._multi(q, sid, tiers, metric)
        rows.sort(key=lambda r: r[0], reverse=(q.superlative == "max"))
        _, win, agree = rows[0]
        tier = _tier_phrase(win)
        word = "highest" if q.superlative == "max" else "lowest"
        text = f"The {word} {_product_name(win)} {_metric_word(metric)} is {win.value}" + (f", for {tier}." if tier else ".")
        return Draft(_tidy(text), agree, self._sources(agree))

    def _multi(self, q, sid: str, tiers: Dict[tuple, List[Fact]], metric: str) -> Draft:
        """Several tiers match (no tier given in the question): list them all, one value each."""
        items = []
        for key, fs in tiers.items():
            win, agree, _ = self._resolve(fs)
            items.append((win, agree))
        items.sort(key=lambda it: (it[0].business, it[0].intro, it[0].jumbo, -(it[0].special),
                                   it[0].term_months or 0, -(it[0].balance[0] if it[0].balance else 0),
                                   (it[0].amount[1] if it[0].amount else 0), -(it[0].model_years[1] if it[0].model_years else 0)))
        if len(items) > 14:
            items = items[:14]
        fam = items[0][0].family
        parts = []
        for win, _ in items:
            label = _product_name(win)
            tier = _tier_phrase(win)
            term = _term_text(win.term_months) if win.term_months and not re.search(r"\d+[- ]?month|\d+[- ]?year", label, re.I) else ""
            bits = " ".join(x for x in [term, label if fam not in ("auto", "atv", "boat_rv", "personal_loan", "home_improvement") else ""] if x)
            bits = f"{bits} ({tier})" if tier and bits else (tier or bits)
            val = win.value
            if fam == "mortgage" and metric == "rate":
                comp = self._companions(sid, win, "apr")
                if comp:
                    val = f"{win.value} rate / {comp.value} APR"
            parts.append(f"{bits}: {val}" if bits else val)
        head = FAMILY_NAMES.get(fam, fam)
        unit = _metric_word(metric) if not (fam == "mortgage" and metric == "rate") else ""
        text = f"Current {head} {unit} by tier: " + "; ".join(parts) + "."
        facts = [f for _, agree in items for f in agree]
        return Draft(_tidy(text), facts, self._sources(facts))

    # ------------------------------------------------------------------ list
    def answer_list(self, q, sid: str) -> Draft:
        fam = q.family
        if fam == "credit_card":
            cards = [f for f in self._facts(sid, "credit_card") if f.metric == "apr" and not f.intro]
            by: Dict[str, List[Fact]] = defaultdict(list)
            for f in cards:
                by[f.product].append(f)
            order = sorted(by, key=lambda p: (p.startswith("Business"), p))
            parts, used = [], []
            for p in order:
                win, agree, _ = self._resolve(by[p])
                parts.append(f"{p}: {win.value} APR" + (" (variable)" if win.business else ""))
                used += agree
            if not parts:
                return Draft(REFUSE_RATE.format(thing="credit cards", org=self.org), confident=False)
            return Draft(f"{self.org} offers " + "; ".join(parts) + ".", used, self._sources(used, 4))
        if fam in ("certificate", "ira"):
            fs = [f for f in self._facts(sid, fam) if f.metric == "apy" and f.business == bool(q.business)]
            if not fs:
                fs = [f for f in self._facts(sid, fam) if f.metric == "apy"]
            if not fs:
                return Draft(REFUSE_RATE.format(thing=_thing(q), org=self.org), confident=False)
            tiers: Dict[tuple, List[Fact]] = defaultdict(list)
            for f in fs:
                tiers[f.soft_key()].append(f)
            specials, regulars, used = [], [], []
            for key, group in tiers.items():
                win, agree, _ = self._resolve(group)
                used += agree
                (specials if win.special else regulars).append(win)
            specials.sort(key=lambda f: (-(f.term_months or 0), f.jumbo, f.ira_type or ""))
            regulars.sort(key=lambda f: (f.term_months or 0, f.ira_type or ""))
            parts = []
            if specials:
                parts.append("Specials: " + ", ".join(f"{_product_name(f)} {f.value} APY" for f in specials))
            if regulars:
                parts.append("Regular terms: " + ", ".join(f"{_term_text(f.term_months)} {f.value} APY" if fam == "certificate"
                                                           else f"{_product_name(f)} {f.value} APY" for f in regulars))
            head = "Certificate rates" if fam == "certificate" else "IRA certificate rates"
            return Draft(f"{head}: " + ". ".join(parts) + ".", used, self._sources(used, 3))
        cands, metric = self._candidates(q, sid)
        if not cands:
            return Draft(REFUSE_RATE.format(thing=_thing(q), org=self.org), confident=False)
        tiers: Dict[tuple, List[Fact]] = defaultdict(list)
        for f in cands:
            tiers[f.soft_key()].append(f)
        return self._multi(q, sid, tiers, metric)

    # ------------------------------------------------------------------ fees
    FEE_NOISE = {"fee", "cost", "charge", "price", "much", "pay", "account", "service", "member", "non-member",
                 "per", "item", "each", "month", "what", "there", "any", "dupaco"}
    FEE_SYNONYMS = {"lost": {"lost", "replacement", "replace", "reissue", "rush"}, "replacement": {"replacement", "replace", "reissue", "lost", "rush"},
                    "wire": {"wire"}, "incoming": {"incoming", "inbound"}, "outgoing": {"outgoing", "domestic", "outbound"},
                    "overdraft": {"overdraft", "nsf", "insufficient"}, "bounced": {"overdraft", "nsf", "returned"},
                    "cashier": {"official", "cashier", "certified"}, "check": {"check", "draft"}, "atm": {"atm"},
                    "foreign": {"foreign", "international"}, "international": {"international", "foreign"},
                    "stop": {"stop"}, "payment": {"payment"}, "money": {"money"}, "order": {"order"},
                    "notary": {"notary"}, "box": {"box"}, "safe": {"safe"}, "deposit": {"deposit"},
                    "statement": {"statement"}, "copy": {"copy"}, "research": {"research"}, "debit": {"debit"},
                    "card": {"card"}, "coin": {"coin"}, "garnishment": {"garnishment"}, "levy": {"levy"},
                    "inactive": {"inactive", "dormant"}, "dormant": {"inactive", "dormant"}, "closing": {"closed", "closing"},
                    "closed": {"closed", "closing"}, "early": {"prior", "early"}}

    def answer_fee(self, q, sid: str) -> Draft:
        fees = self._facts(sid, "fee")
        thing = q.raw.strip(" ?.")
        for _ in range(6):
            thing = re.sub(r"^(what's|what|how much|is|are|the|a|an|does|do|you|charge|for|cost|of|fee|fees|there|it|much|will)\b\s*", "", thing, flags=re.I)
        thing = thing or "that"
        if not fees:
            return Draft(REFUSE_FEE.format(thing=thing, org=self.org), confident=False)
        keys = [t for t in q.tokens if t not in self.FEE_NOISE and not t.isdigit()]
        if not keys:
            return Draft(REFUSE_FEE.format(thing=thing, org=self.org), confident=False)
        scored = []
        for f in fees:
            ltoks = set(tokenize(f.product))
            covered = 0
            for k in keys:
                alts = self.FEE_SYNONYMS.get(k, {k})
                if alts & ltoks:
                    covered += 1
            if covered == len(keys):
                extra = len(ltoks - {t for k in keys for t in self.FEE_SYNONYMS.get(k, {k})})
                scored.append((-extra, f.authority, f))
        if not scored:
            return Draft(REFUSE_FEE.format(thing=thing, org=self.org), confident=False)
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        win = scored[0][2]
        same = [f for f in fees if f.product == win.product]
        win, agree, note = self._resolve(same)
        text = f"The fee for {win.product[0].lower() + win.product[1:]} is {win.value}."
        if win.value.lower().startswith(("free", "no charge")):
            text = f"{win.product} is free of charge."
        return Draft(_tidy(text), agree, self._sources(agree, 2), conflict_note=note)

    # ------------------------------------------------------------------ verify / change
    def answer_verify(self, q, sid: str) -> Draft:
        if not q.product and q.family == "savings":
            q.product = "Share Savings"
        cands, metric = self._candidates(q, sid)
        if not cands:
            return self.answer_fact(q, sid, True)
        tiers: Dict[tuple, List[Fact]] = defaultdict(list)
        for f in cands:
            tiers[f.soft_key()].append(f)
        wins = [self._resolve(fs)[0] for fs in tiers.values()]
        hits = [w for w in wins if any(abs(v - q.pct_value) < 1e-9 for v in pct_values(w.value))]
        name = _product_name(wins[0])
        if hits:
            w = hits[0]
            tier = _tier_phrase(w)
            text = f"Yes. {name} pays {w.value} {_metric_word(metric)}" + (f" for {tier}." if tier else ".")
            return Draft(_tidy(text), hits, self._sources(hits))
        vals = sorted({v for w in wins for v in pct_values(w.value)})
        top = max(wins, key=lambda w: max(pct_values(w.value) or [0]))
        tier = _tier_phrase(top)
        rng = f"{vals[0]:.2f}% to {vals[-1]:.2f}%" if len(vals) > 1 else f"{vals[0]:.2f}%"
        text = f"No. {name} pays {rng} {_metric_word(metric)}; the highest tier" + (f" ({tier})" if tier else "") + \
               f" earns {top.value} {_metric_word(metric)}."
        return Draft(_tidy(text), wins, self._sources(wins))

    def answer_change(self, q, sid: str) -> Draft:
        cands, metric = self._candidates(q, sid)
        if not cands:
            return self.answer_fact(q, sid, True)
        tiers: Dict[tuple, List[Fact]] = defaultdict(list)
        for f in cands:
            tiers[f.soft_key()].append(f)
        if len(tiers) > 1 and not (q.model_year is not None or q.balance is not None or q.amount is not None):
            return self._multi(q, sid, tiers, metric)
        win = best_of(cands)
        key = win.soft_key()
        series = []
        for s, taken, fs in self.store.history(lambda f: f.soft_key() == key and f.authority >= 50):
            if fs:
                w = best_of(fs)
                series.append((s, taken, w))
        if not series:
            return self._single(q, sid, win, [win], None, metric)
        changes = []
        prev = None
        for s, taken, w in series:
            if prev is None or w.value != prev.value:
                changes.append((taken, w))
            prev = w
        name = _product_name(win)
        tier = _tier_phrase(win)
        label = " ".join(x for x in [_term_text(win.term_months) if not re.search(r"month|year", name, re.I) else "", name] if x)
        label = f"{label} ({tier})" if tier else label
        if len(changes) == 1:
            text = f"The {label} {_metric_word(metric)} has been {win.value} in every snapshot since {_month(changes[0][0])}."
        else:
            steps = [f"{w.value} (as of {_month(t)})" for t, w in changes]
            text = f"The {label} {_metric_word(metric)} changed: " + " -> ".join(steps) + f". The current value is {changes[-1][1].value}."
        used = [w for _, _, w in series]
        return Draft(_tidy(text), used, self._sources([changes[-1][1]] + used, 3))

    # ------------------------------------------------------------------ link
    def answer_link(self, q, sid: str) -> Draft:
        pages = self.pages.get(sid, {})
        low = q.raw.lower()
        if re.search(r"\b(join|become a member|sign up|enroll|open an? account)\b", low):
            counts: Counter = Counter()
            for url, meta in pages.items():
                for l in meta.get("links", []):
                    if "join." in l.lower() or "/join" in l.lower():
                        counts[l.split("?")[0].rstrip("/") + "/"] += 1
            if counts:
                target = counts.most_common(1)[0][0]
                return Draft(f"You can join {self.org} online at {target}", urls=[(target, "")])
        if re.search(r"locator|branch|atm|location|contact|phone", low):
            u = _pick_url(pages, ["/contact"])
            if u:
                return Draft(f"{self.org}'s branch and ATM locator is on the contact page: {u}", urls=[(u, "")])
        targets = {
            "certificate": ["/personal/savings-account", "/rates"], "savings": ["/personal/savings-account", "/rates"],
            "money_market": ["/personal/savings-account", "/rates"], "hsa": ["/personal/savings-account", "/rates"],
            "ira": ["/personal/retirement", "/rates"], "checking": ["/personal/checking-accounts", "/rates"],
            "auto": ["/personal/loans/auto-motorcycle-loans", "/personal/loans/auto-loans", "/rates"],
            "mortgage": ["/personal/loans/home-loans", "/rates"], "credit_card": ["/personal/credit-cards", "/rates"],
            "personal_loan": ["/personal/loans/personal-loans", "/rates"], "heloc": ["/personal/loans/home-equity-line-of-credit", "/rates"],
            "student_loan": ["/personal/loans/student-loans"],
        }
        fam = q.family
        if fam in targets:
            if q.business:
                biz = {"certificate": "/business/savings-accounts", "savings": "/business/savings-accounts",
                       "checking": "/business/checking-accounts", "credit_card": "/business/credit-cards"}
                u = _pick_url(pages, [biz.get(fam, "/business-rates"), "/business-rates"])
            else:
                u = _pick_url(pages, targets[fam])
            if u:
                frag = "#rates" if re.search(r"\brates?\b|apy|apr", low) and "/rates" not in u else ""
                return Draft(f"You can find that on the website at {u}{frag}", urls=[(u, "")])
        if re.search(r"\brates?\b", low):
            u = _pick_url(pages, ["/rates"])
            if u:
                return Draft(f"The rates page is {u}", urls=[(u, "")])
        hits = self.index.search(q.tokens, sid, k=5, url_filter=lambda u: pages.get(u, {}).get("class", 0) >= 60,
                                 url_source=self.store.url_source(sid))
        if hits:
            u = hits[0][2]
            return Draft(f"The relevant page is {u}", urls=[(u, hits[0][1].text[:160])])
        return Draft(REFUSE_GENERIC.format(org=self.org), confident=False)

    # ------------------------------------------------------------------ free text
    def answer_free(self, q, sid: str) -> Draft:
        toks = q.tokens
        if not toks:
            return Draft(REFUSE_GENERIC.format(org=self.org), confident=False)
        pages = self.pages.get(sid, {})
        hits = self.index.search(toks, sid, k=12, url_source=self.store.url_source(sid))
        hits = [h for h in hits if pages.get(h[2], {}).get("class", 0) > OTHER]
        if not hits:
            return Draft(REFUSE_GENERIC.format(org=self.org), confident=False)
        if hits[0][0] < 4.0:
            return Draft(REFUSE_GENERIC.format(org=self.org), confident=False)
        qset = set(toks)
        # A page whose URL slug names what the question asks about beats a page that merely mentions it.
        def slug_boost(h):
            slug = set(tokenize(re.sub(r"[/_?=&.-]+", " ", h[2].split("//")[-1].split("/", 1)[-1])))
            return h[0] * (1 + 0.15 * len(qset & slug))
        hits.sort(key=slug_boost, reverse=True)
        wants_number = bool(re.search(r"how many|how much|what (?:is|was) the (?:number|amount|cost|fee)", q.raw, re.I))
        definitional = bool(re.search(r"^\s*(what is|what's|whats|tell me about|describe|explain|what does .* (?:do|mean|offer))\b", q.raw, re.I))
        if definitional and hits:
            # The lead paragraph of the best page defines the thing; quotes further down only mention it.
            top_url = hits[0][2]
            same = [h for h in hits[:8] if h[2] == top_url and not h[1].is_table]
            if len(same) > 1:
                same.sort(key=lambda h: h[1].pos.get(top_url, 1 << 30))
                hits = same + [h for h in hits if h not in same]
        for score, chunk, url in hits[:6]:
            if chunk.is_table:
                continue
            sents = sentences(chunk.text)
            scored = []
            for i, s in enumerate(sents):
                stoks = set(tokenize(s))
                overlap = len(qset & stoks)
                if overlap == 0:
                    continue
                bonus = 0.6 if (wants_number and re.search(r"\d", s)) else 0.0
                scored.append((overlap + bonus - (0.4 if len(s) > 320 else 0.0), i))
            if not scored:
                continue
            scored.sort(key=lambda t: (-t[0], t[1]))      # ties go to the earlier sentence
            _, i = scored[0]
            picked = [sents[i]]
            if sents[i].rstrip().endswith("?") and i + 1 < len(sents):       # FAQ: question then answer
                picked = sents[i + 1:i + 3]
            elif i + 1 < len(sents) and len(sents[i + 1]) < 260 and (
                    definitional or wants_number or (len(sents[i]) < 160 and set(tokenize(sents[i + 1])) & qset)):
                picked.append(sents[i + 1])
            text = self._scrub_stale_rates(" ".join(picked), sid)
            if text.strip():
                return Draft(_tidy(text[:600]), urls=[(url, sents[i][:200])])
        score, chunk, url = hits[0]
        return Draft(_tidy(chunk.text[:400]), urls=[(url, chunk.text[:200])])

    def _scrub_stale_rates(self, text: str, sid: str) -> str:
        """Drop a free-text sentence that quotes a rate the current rate tables don't contain."""
        current = {v for f in self.store.facts[sid] if f.metric in ("apy", "apr", "rate", "dividend_rate")
                   for v in pct_values(f.value)}
        keep = []
        for s in sentences(text) or [text]:
            vals = pct_values(s)
            if vals and current and any(v not in current for v in vals):
                continue
            keep.append(s)
        return " ".join(keep) if keep else text

    # ------------------------------------------------------------------ dispatch
    def compose(self, q, sid: str, exact: bool, ref_date: date) -> Draft:
        if q.entity and q.intent in ("fact", "status", "aggregate", "free"):
            d = self.answer_entity(q, sid, ref_date)
            if d:
                return d
            if q.entity in ("hours_lobby", "hours_driveup", "address", "closure") and q.branch:
                return Draft(REFUSE_BRANCH.format(what="that information", branch=q.branch, org=self.org), confident=False)
        if q.intent == "link":
            return self.answer_link(q, sid)
        if q.intent == "fee":
            return self.answer_fee(q, sid)
        if q.intent == "list" and q.family:
            return self.answer_list(q, sid)
        if q.intent == "verify" and q.family and q.pct_value is not None:
            return self.answer_verify(q, sid)
        if q.intent == "change" and q.family:
            return self.answer_change(q, sid)
        if q.intent in ("fact", "superlative") and q.family:
            if q.metric is None and not (q.term_months or q.product or q.model_year or q.balance is not None):
                return self.answer_free(q, sid)
            return self.answer_fact(q, sid, exact)
        return self.answer_free(q, sid)


# ---------------------------------------------------------------------- module helpers
def _month(d: date) -> str:
    return d.strftime("%B %Y")


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).replace(" .", ".").replace(" ,", ",").strip()
    text = re.sub(r"\bThe  +", "The ", text)
    return text[0].upper() + text[1:] if text else text


def _thing(q) -> str:
    low = q.raw.lower()
    if re.search(r"\barm\b|adjustable", low):
        m = re.search(r"(\d+/\d+)", q.raw)
        return f"a {m.group(1)} adjustable-rate mortgage" if m else "an adjustable-rate mortgage"
    if q.family == "construction":
        return "construction loans"
    if q.family == "student_loan":
        return "student loans"
    name = FAMILY_NAMES.get(q.family, "that product")
    if q.product:
        name = q.product
    if q.term_months:
        name = f"a {_term_text(q.term_months)} {name}"
    return name


def _product_match(wanted: str, actual: str) -> bool:
    w, a = wanted.lower(), actual.lower()
    if w == a or w in a:
        return True
    wt = {t for t in tokenize(w) if t not in ("account", "visa", "card")}
    at = set(tokenize(a))
    return bool(wt) and wt <= at


def _branch_match(wanted: str, f: Fact) -> bool:
    w = set(tokenize(wanted))
    w = {t for t in w if t not in ("branch", "avenue", "ave", "street", "st", "road", "rd", "drive", "dr", "lane", "ln", "blvd")}
    if not w:
        return False
    hay = " ".join([f.product, f.extra.get("branch", "") or "", f.extra.get("city", "") or "", f.extra.get("street", "") or "", f.value if f.metric == "address" else ""])
    h = set(tokenize(hay))
    return w <= h


def _pick_url(pages: Dict[str, dict], paths: List[str]) -> Optional[str]:
    for p in paths:
        for url in pages:
            if url_key(url).endswith(p.rstrip("/").lower()) or url_key(url).endswith(p.lower()):
                return url
    return None
