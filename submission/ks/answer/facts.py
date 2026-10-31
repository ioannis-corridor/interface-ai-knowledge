"""Answers built from rate-table facts: one value, a tier list, a superlative, a yes/no check, or a change history."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..format import has_term_words, metric_word, month_text, product_name, term_text, tidy, tier_phrase
from ..model import FAMILY_NAMES, Fact
from ..pages import url_key
from ..store import best_of
from ..text import pct_values
from .base import DEPOSIT, PRIMARY_METRIC, AnswerBase, product_match
from .draft import GONE, NOT_ON_SHEET, NOT_YET, REFUSE_RATE, Draft

NO_RATE_FAMILIES = {"construction", "student_loan"}
GENERIC_LOAN_FAMILIES = {"auto", "atv", "boat_rv", "personal_loan", "home_improvement", "home_equity_loan"}
RATE_METRICS = ("apy", "dividend_rate", "apr", "rate")
AUTHORITATIVE = 85          # rate sheets and product pages
SECONDARY = 60              # below this: promo landing pages, calculators, files, carried copies
MIN_METRICS = ("min_open", "min_earn")
MAX_TIERS_LISTED = 14
GENERIC_PRODUCT_RE = re.compile(r"\b(IRAs|Certificates|Accounts|Loans|Rates)$", re.I)
Tiers = Dict[tuple, List[Fact]]


@dataclass
class Candidates:
    facts: List[Fact]
    metric: str
    dropped: List[Fact] = field(default_factory=list)   # low-authority copies set aside (calculators, promos)

    def tiers(self) -> Tiers:
        out: Tiers = defaultdict(list)
        for f in self.facts:
            out[f.soft_key()].append(f)
        return out


class FactAnswers(AnswerBase):
    # ------------------------------------------------------------------ selection
    def candidates(self, q, sid: str) -> Candidates:
        """Facts of the snapshot that satisfy every qualifier the question gives."""
        fam = q.family
        pool = self.facts(sid, fam)
        available = {f.metric for f in pool}
        metric = q.metric if q.metric in RATE_METRICS + MIN_METRICS else None
        if metric in MIN_METRICS and metric not in available:
            other = "min_earn" if metric == "min_open" else "min_open"    # certificates list only a minimum to earn
            metric = other if other in available else None
        elif metric not in available:
            prim = PRIMARY_METRIC.get(fam, "apr")
            metric = prim if prim in available else next((m for m in ("apy", "apr", "rate") if m in available), None)
        if metric is None:
            return Candidates([], PRIMARY_METRIC.get(fam, "apr"))
        c = [f for f in pool if f.metric == metric]
        wants_business = q.business is True
        c = [f for f in c if f.business == wants_business] or c
        if q.product:
            c = [f for f in c if product_match(q.product, f.product)]
        if fam == "mortgage":
            wants_arm = re.search(r"\barm\b|adjustable", q.raw, re.I)
            c = [f for f in c if bool(re.search(r"\barm\b|adjustable", f.product, re.I)) == bool(wants_arm)]
            if q.purpose:
                c = [f for f in c if f.purpose == q.purpose]
            elif any(f.purpose == "purchase" for f in c):
                c = [f for f in c if f.purpose in ("purchase", None)]
        if q.term_months is not None:
            c = [f for f in c if f.term_months == q.term_months]
        if q.model_year is not None:
            c = [f for f in c if f.model_years and f.model_years[0] <= q.model_year <= f.model_years[1]]
        elif q.newest_model and any(f.model_years for f in c):
            newest = max(f.model_years[1] for f in c if f.model_years)
            c = [f for f in c if f.model_years and f.model_years[1] == newest]
        if q.balance is not None:
            c = [f for f in c if f.balance and f.balance[0] <= q.balance <= f.balance[1]]
        if q.amount is not None and any(f.amount for f in c):
            inside = [f for f in c if f.amount and f.amount[0] <= q.amount <= f.amount[1]]
            if inside:                                   # nested "or less" tiers: the tightest one applies
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
        dropped: List[Fact] = []
        if any(f.authority >= 85 for f in c):            # calculators and promo pages only count when nothing better exists
            dropped = [f for f in c if f.authority < 60]
            c = [f for f in c if f.authority >= 60]
        return Candidates(c, metric, dropped)

    def _only_secondary(self, cands: Candidates, sid: str) -> bool:
        """True when every match is a promo/calculator/carried copy while an authoritative page covers the family."""
        if max(f.authority for f in cands.facts) >= SECONDARY:
            return False
        return any(f.authority >= AUTHORITATIVE and f.metric == cands.metric for f in self.facts(sid, cands.facts[0].family))

    @staticmethod
    def authoritative_only(facts: List[Fact]) -> List[Fact]:
        """Drop promo/calculator copies when an authoritative page covers the same family."""
        if any(f.authority >= AUTHORITATIVE for f in facts):
            return [f for f in facts if f.authority >= SECONDARY]
        return facts

    @staticmethod
    def stale_note(win: Fact, dropped: List[Fact]) -> Optional[str]:
        stale = [f for f in dropped if f.value != win.value and f.term_months == win.term_months and f.metric == win.metric]
        if not stale:
            return None
        vals = sorted({f.value for f in stale})
        pages = sorted({url_key(f.url) for f in stale})
        return (f"Other pages ({', '.join(pages)}) still show {', '.join(vals)}; the rate page "
                f"({url_key(win.url)}) is authoritative and current.")

    # ------------------------------------------------------------------ one value
    def answer_fact(self, q, sid: str) -> Draft:
        fam = q.family
        if fam in NO_RATE_FAMILIES or fam is None:
            return Draft.refuse(REFUSE_RATE, thing=self.thing(q), org=self.org)
        cands = self.candidates(q, sid)
        if cands.facts and self._only_secondary(cands, sid):
            # The rate sheet covers this family but not this product: a promo or calculator page is all that is
            # left of it. "A promotion ends, but its page is never taken down" is the kit's headline failure mode.
            best = best_of(cands.facts)
            draft = Draft.refuse(NOT_ON_SHEET, thing=self.thing(q), org=self.org)
            draft.conflict_note = (f"Only {url_key(best.url)} (authority {best.authority}) still shows "
                                   f"{best.value} {metric_word(best.metric)}; the current rate sheet does not list it.")
            return draft
        if not cands.facts:
            if sid != self.store.latest and self.candidates(q, self.store.latest).facts:
                return Draft.refuse(NOT_YET, org=self.org)
            last = self._last_seen(q, sid)
            if last:
                seen_sid, seen = last
                draft = Draft.refuse(GONE, thing=self.thing(q), org=self.org)
                draft.conflict_note = (f"Last listed in the {month_text(self.store.taken_on(seen_sid))} crawl "
                                       f"({seen.value} {metric_word(seen.metric)} on {url_key(seen.url)}).")
                return draft
            return Draft.refuse(REFUSE_RATE, thing=self.thing(q), org=self.org)
        tiers = cands.tiers()
        pinned = q.model_year is not None or q.balance is not None or q.amount is not None
        if len(tiers) > 1 and pinned:
            # Several tier labels contain the asked value (model-year ranges drift between crawls): the most
            # authoritative copy decides, the others become a note.
            win = best_of(cands.facts)
            win, agree, note = self.resolve(tiers[win.soft_key()])
            losers = [f for f in cands.facts if f.soft_key() != win.soft_key() and f.value != win.value]
            if losers and not note:
                vals = sorted({f.value for f in losers})
                pages = sorted({url_key(f.url) for f in losers})
                note = (f"Other pages ({', '.join(pages)}) still show {', '.join(vals)} for an older tier table; "
                        f"the rate page is authoritative.")
            return self.single(sid, win, agree, note or self.stale_note(win, cands.dropped), cands.metric, q.metric_explicit)
        if len(tiers) == 1:
            win, agree, note = self.resolve(cands.facts)
            return self.single(sid, win, agree, note or self.stale_note(win, cands.dropped), cands.metric, q.metric_explicit)
        if q.superlative:
            return self.superlative(q, sid, tiers, cands.metric)
        return self.multi(sid, tiers, cands.metric)

    def _last_seen(self, q, sid: str):
        """The newest earlier snapshot that still had a matching fact (a product that was since dropped)."""
        for earlier, _ in reversed(self.store.snapshots):
            if self.store.taken_on(earlier) >= self.store.taken_on(sid):
                continue
            found = self.candidates(q, earlier).facts
            if found:
                return earlier, best_of(found)
        return None

    def single(self, sid: str, win: Fact, agree: List[Fact], note: Optional[str], metric: str,
               metric_explicit: bool = False) -> Draft:
        """One value. The companion metric (dividend rate next to an APY, APR next to a mortgage rate) is added
        only when the question did not name a metric; a second number is never free under this scorer."""
        name = product_name(win)
        tier = tier_phrase(win)
        term = term_text(win.term_months) if win.term_months and not has_term_words(name) else ""
        desc = " ".join(x for x in [term, name] if x)
        companion = None
        if metric_explicit:
            pass
        elif win.family in DEPOSIT and metric == "apy":
            companion = self.companion(sid, win, "dividend_rate")
        elif win.family in DEPOSIT and metric == "dividend_rate":
            companion = self.companion(sid, win, "apy")
        elif win.family == "mortgage" and metric == "rate":
            companion = self.companion(sid, win, "apr")
        extra = f" ({companion.value} {metric_word(companion.metric)})" if companion and companion.value != win.value else ""
        generic = bool(re.search(r"^\d+ months?$|^loan - |standard \(|^\d+ years?$", name, re.I)) or name.lower() == win.family
        loan_desc = " ".join(x for x in [term_text(win.term_months), FAMILY_NAMES.get(win.family, win.family)] if x) \
            if generic or win.family in GENERIC_LOAN_FAMILIES else desc
        for_tier = f" for {tier}" if tier else ""
        if metric in MIN_METRICS:
            text = f"The {metric_word(metric)} the {desc} is {win.value}{for_tier}."
        elif win.family in ("auto", "atv", "boat_rv"):
            text = f"The {loan_desc} APR{for_tier} is {win.value}."
        elif win.family == "credit_card":
            kind = "introductory balance-transfer" if win.intro else "standard"
            text = f"The {name} {kind} APR is {win.value}, based on creditworthiness."
        elif win.family in DEPOSIT:
            text = f"{desc} pays {win.value} {metric_word(metric)}{extra}{for_tier}."
        elif win.family == "mortgage":
            text = f"The {name} {metric_word(metric)} is {win.value}{extra}{for_tier}."
        else:
            text = f"The {loan_desc} {metric_word(metric)} is {win.value}{extra}{for_tier}."
        facts = agree + ([companion] if companion else [])
        return Draft(tidy(text), facts, self.sources(agree), conflict_note=note)

    def superlative(self, q, sid: str, tiers: Tiers, metric: str) -> Draft:
        rows = []
        for fs in tiers.values():
            win, agree, _ = self.resolve(fs)
            vals = pct_values(win.value)
            if vals:
                rows.append((max(vals) if q.superlative == "max" else min(vals), win, agree))
        if not rows:
            return self.multi(sid, tiers, metric)
        rows.sort(key=lambda r: r[0], reverse=(q.superlative == "max"))
        _, win, agree = rows[0]
        tier = tier_phrase(win)
        word = "highest" if q.superlative == "max" else "lowest"
        text = f"The {word} {product_name(win)} {metric_word(metric)} is {win.value}" + (f", for {tier}." if tier else ".")
        return Draft(tidy(text), agree, self.sources(agree))

    def multi(self, sid: str, tiers: Tiers, metric: str) -> Draft:
        """No tier was asked for: list every tier with its own value. Tiers are different facts, not conflicts."""
        items = [self.resolve(fs)[:2] for fs in tiers.values()]
        # A copy of the same product/value without tier detail (older page layout) is not another tier, and a
        # table labelled only "Variable IRAs" duplicates the Roth/Traditional rows that carry the same values.
        rich = {(w.product, w.value) for w, _ in items if w.balance or w.amount or w.model_years or w.term_months}
        items = [(w, a) for w, a in items
                 if (w.balance or w.amount or w.model_years or w.term_months) or (w.product, w.value) not in rich]
        specific = {(w.value, w.soft_key()[4:8]) for w, _ in items if not GENERIC_PRODUCT_RE.search(w.product)}
        items = [(w, a) for w, a in items
                 if not (GENERIC_PRODUCT_RE.search(w.product) and (w.value, w.soft_key()[4:8]) in specific)]
        items = sorted(items, key=lambda it: (it[0].business, it[0].intro, it[0].jumbo, -it[0].special, it[0].term_months or 0,
                                              -(it[0].balance[0] if it[0].balance else 0),
                                              (it[0].amount[1] if it[0].amount else 0),
                                              -(it[0].model_years[1] if it[0].model_years else 0)))[:MAX_TIERS_LISTED]
        fam = items[0][0].family
        facts = [f for _, agree in items for f in agree]
        if metric in MIN_METRICS:
            return self._minimums(items, fam, metric, facts)
        parts = []
        for win, _ in items:
            label = product_name(win)
            tier = tier_phrase(win)
            term = term_text(win.term_months) if win.term_months and not has_term_words(label) else ""
            show_label = fam not in GENERIC_LOAN_FAMILIES
            bits = " ".join(x for x in [term, label if show_label else ""] if x)
            bits = f"{bits} ({tier})" if tier and bits else (tier or bits)
            value = win.value
            if fam == "mortgage" and metric == "rate":
                companion = self.companion(sid, win, "apr")
                if companion:
                    value = f"{win.value} rate / {companion.value} APR"
            parts.append(f"{bits}: {value}" if bits else value)
        unit = "" if (fam == "mortgage" and metric == "rate") else metric_word(metric)
        text = f"Current {FAMILY_NAMES.get(fam, fam)} {unit} by tier: " + "; ".join(parts) + "."
        return Draft(tidy(text), facts, self.sources(facts))

    def _minimums(self, items, fam: str, metric: str, facts: List[Fact]) -> Draft:
        """Minimums are usually the same across tiers: say the value once, grouped by the products it applies to."""
        by_value: Dict[str, List[str]] = defaultdict(list)
        tiered = {w.product for w, _ in items if w.balance or w.amount}
        for win, _ in items:
            label = product_name(win) if fam not in GENERIC_LOAN_FAMILIES else tier_phrase(win)
            if win.product in tiered and (win.balance or win.amount) and len(items) > 1:
                label = f"{label} ({tier_phrase(win)})"
            if label not in by_value[win.value]:
                by_value[win.value].append(label)
        head = f"The {metric_word(metric)} {FAMILY_NAMES.get(fam, fam)}s"
        if len(by_value) == 1:
            value, labels = next(iter(by_value.items()))
            subject = labels[0].split(" (")[0] if len(labels) == 1 or len(tiered) == 1 else FAMILY_NAMES.get(fam, fam) + "s"
            return Draft(tidy(f"The {metric_word(metric)} {subject} is {value}."), facts, self.sources(facts))
        parts = []
        for value, labels in by_value.items():
            shown = ", ".join(labels[:5]) + (f" and {len(labels) - 5} more" if len(labels) > 5 else "")
            parts.append(f"{value} for {shown}")
        return Draft(tidy(head + ": " + "; ".join(parts) + "."), facts, self.sources(facts))

    # ------------------------------------------------------------------ lists
    def answer_list(self, q, sid: str) -> Draft:
        fam = q.family
        if fam == "credit_card":
            return self._list_cards(sid)
        if fam in ("certificate", "ira"):
            return self._list_certificates(q, sid, fam)
        cands = self.candidates(q, sid)
        if not cands.facts:
            return Draft.refuse(REFUSE_RATE, thing=self.thing(q), org=self.org)
        return self.multi(sid, cands.tiers(), cands.metric)

    def _list_cards(self, sid: str) -> Draft:
        """Personal and business cards together, intro offers left out."""
        by: Dict[str, List[Fact]] = defaultdict(list)
        for f in self.authoritative_only([f for f in self.facts(sid, "credit_card") if f.metric == "apr" and not f.intro]):
            by[f.product].append(f)
        parts, used = [], []
        for product in sorted(by, key=lambda p: (p.startswith("Business"), p)):
            win, agree, _ = self.resolve(by[product])
            parts.append(f"{product}: {win.value} APR" + (" (variable)" if win.business else ""))
            used += agree
        if not parts:
            return Draft.refuse(REFUSE_RATE, thing="credit cards", org=self.org)
        return Draft(f"{self.org} offers " + "; ".join(parts) + ".", used, self.sources(used, 4))

    def _list_certificates(self, q, sid: str, fam: str) -> Draft:
        pool = self.authoritative_only([f for f in self.facts(sid, fam) if f.metric == "apy"])
        fs = [f for f in pool if f.business == bool(q.business)] or pool
        if not fs:
            return Draft.refuse(REFUSE_RATE, thing=self.thing(q), org=self.org)
        tiers: Tiers = defaultdict(list)
        for f in fs:
            tiers[f.soft_key()].append(f)
        specials, regulars, used = [], [], []
        for group in tiers.values():
            win, agree, _ = self.resolve(group)
            used += agree
            (specials if win.special else regulars).append(win)
        specials.sort(key=lambda f: (-(f.term_months or 0), f.jumbo, f.ira_type or ""))
        regulars.sort(key=lambda f: (f.term_months or 0, f.ira_type or ""))
        parts = []
        if specials:
            parts.append("Specials: " + ", ".join(f"{product_name(f)} {f.value} APY" for f in specials))
        if regulars:
            label = (lambda f: term_text(f.term_months)) if fam == "certificate" else product_name
            parts.append("Regular terms: " + ", ".join(f"{label(f)} {f.value} APY" for f in regulars))
        head = "Certificate rates" if fam == "certificate" else "IRA certificate rates"
        return Draft(f"{head}: " + ". ".join(parts) + ".", used, self.sources(used, 3))

    # ------------------------------------------------------------------ verify / change
    def answer_verify(self, q, sid: str) -> Draft:
        """'Do any savings tiers pay 0.35%?' -> yes with the tier, or no with the real range."""
        if not q.product and q.family == "savings":
            q.product = "Share Savings"
        cands = self.candidates(q, sid)
        if not cands.facts:
            return self.answer_fact(q, sid)
        wins = [self.resolve(fs)[0] for fs in cands.tiers().values()]
        unit = metric_word(cands.metric)
        name = product_name(wins[0])
        hits = [w for w in wins if any(abs(v - q.pct_value) < 1e-9 for v in pct_values(w.value))]
        if hits:
            tier = tier_phrase(hits[0])
            text = f"Yes. {name} pays {hits[0].value} {unit}" + (f" for {tier}." if tier else ".")
            return Draft(tidy(text), hits, self.sources(hits))
        vals = sorted({v for w in wins for v in pct_values(w.value)})
        top = max(wins, key=lambda w: max(pct_values(w.value) or [0]))
        tier = tier_phrase(top)
        rng = f"{vals[0]:.2f}% to {vals[-1]:.2f}%" if len(vals) > 1 else f"{vals[0]:.2f}%"
        text = f"No. {name} pays {rng} {unit}; the highest tier" + (f" ({tier})" if tier else "") + f" earns {top.value} {unit}."
        return Draft(tidy(text), wins, self.sources(wins))

    def answer_change(self, q, sid: str) -> Draft:
        """How a fact moved across snapshots. Tier labels that drift (model years) are followed by group key."""
        cands = self.candidates(q, sid)
        if not cands.facts:
            return self.answer_fact(q, sid)
        tiers = cands.tiers()
        pinned = q.model_year is not None or q.balance is not None or q.amount is not None
        if len(tiers) > 1 and not pinned:
            return self.multi(sid, tiers, cands.metric)
        win = best_of(cands.facts)
        key = win.group_key()
        series = []
        for _, taken, fs in self.store.history(lambda f: f.group_key() == key and f.authority >= 50):
            if fs:
                series.append((taken, best_of(fs)))
        if not series:
            return self.single(sid, win, [win], None, cands.metric)
        changes = []
        for taken, w in series:
            if not changes or w.value != changes[-1][1].value:
                changes.append((taken, w))
        name = product_name(win)
        tier = tier_phrase(win)
        label = " ".join(x for x in [term_text(win.term_months) if not has_term_words(name) else "", name] if x)
        label = f"{label} ({tier})" if tier else label
        unit = metric_word(cands.metric)
        if len(changes) == 1:
            text = f"The {label} {unit} has been {win.value} in every snapshot since {month_text(changes[0][0])}."
        else:
            steps = [f"{w.value} (as of {month_text(t)})" for t, w in changes]
            text = (f"The {label} {unit} changed from " + ", then ".join(steps[:-1]) + f" to {steps[-1]}. "
                    f"The current value is {changes[-1][1].value}.")
        used = [w for _, w in series]
        return Draft(tidy(text), used, self.sources([changes[-1][1]] + used, 3))

    # ------------------------------------------------------------------ wording
    @staticmethod
    def thing(q) -> str:
        """What the refusal says the site does not list."""
        low = q.raw.lower()
        if re.search(r"\barm\b|adjustable", low):
            m = re.search(r"(\d+/\d+)", q.raw)
            return f"a {m.group(1)} adjustable-rate mortgage" if m else "an adjustable-rate mortgage"
        if q.family == "construction":
            return "construction loans"
        if q.family == "student_loan":
            return "student loans"
        name = q.product or FAMILY_NAMES.get(q.family, "that product")
        return f"a {term_text(q.term_months)} {name}" if q.term_months else name
