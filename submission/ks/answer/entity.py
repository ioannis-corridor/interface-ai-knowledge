"""Answers built from prose facts: counts, routing number, phone, hours, addresses, closures, eligibility."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import List, Optional

from ..model import Fact
from ..pages import url_key
from ..store import best_of
from ..text import parse_long_date
from .base import AnswerBase, branch_match
from .draft import REFUSE_BRANCH, Draft

COUNT_ENTITIES = {
    "branch_count": ("branch count", "branch office locations", ""),
    "employee_count": ("employee count", "employees", ""),
    "member_count": ("member count", "members", "more than "),
    "assets": ("total assets", "in assets", "more than "),
}
US_STATES = ("Iowa|Illinois|Wisconsin|Minnesota|Missouri|Nebraska|South Dakota|North Dakota|Kansas|Indiana|Michigan|"
             "Ohio|Kentucky|Arizona|Texas|California|Florida|New York|Colorado")
STATES_RE = re.compile(rf"((?:{US_STATES}),?\s+(?:and\s+)?(?:{US_STATES})(?:,?\s+(?:and\s+)?(?:{US_STATES}))+)")
TIME_RE = re.compile(r"\d{1,2}(?::\d{2})? ?[ap]\.m\.|noon|midnight", re.I)


def newest(facts: List[Fact]) -> Fact:
    """For prose facts the newest release wins; authority only breaks ties."""
    return max(facts, key=lambda f: (f.article_date or date.min, f.authority))


class EntityAnswers(AnswerBase):
    def answer_entity(self, q, sid: str, ref_date: date) -> Optional[Draft]:
        """Returns None when the entity type has no facts in this snapshot, so the caller can fall back."""
        ent = q.entity
        facts = self.facts(sid, "entity")
        if ent == "routing":
            fs = [f for f in facts if f.metric == "id"]
            win = best_of(fs)
            return Draft(f"{self.org}'s routing number is {win.value}.", [win], self.sources(fs)) if win else None
        if ent in COUNT_ENTITIES:
            return self._count(ent, facts)
        if ent == "forbes":
            fs = [f for f in facts if f.product == "Forbes recognition"]
            if not fs:
                return None
            win = newest(fs)
            text = (f"Forbes has named {self.org} one of the best credit unions in its state; the most recent "
                    f"announcement says this was the {win.value} time Forbes recognized {self.org}.")
            return Draft(text, [win], self.sources([win]))
        if ent in ("hours_lobby", "hours_driveup"):
            return self._hours(q, sid, ent, facts)
        if ent == "address":
            return self._address(q, sid, facts)
        if ent == "closure":
            return self._closure(q, sid, facts, ref_date)
        if ent == "eligibility":
            return self._eligibility(sid)
        if ent == "account_howto":
            return self._account_howto(q, sid)
        if ent == "phone":
            return self._phone(sid)
        return None

    # ------------------------------------------------------------------ handlers
    def _count(self, ent: str, facts: List[Fact]) -> Optional[Draft]:
        product, noun, lead = COUNT_ENTITIES[ent]
        fs = [f for f in facts if f.product == product]
        if not fs:
            return None
        win = newest(fs)
        same = [f for f in fs if f.value == win.value]
        others = sorted({f.value for f in fs if f.value != win.value})
        note = f"Older releases quote {', '.join(others[:4])}; the newest release is used." if others else None
        text = f"{self.org} has {lead}{win.value} {noun}, according to its most recent news release."
        return Draft(text, same, self.sources(same, 3), conflict_note=note)

    def _hours(self, q, sid: str, ent: str, facts: List[Fact]) -> Optional[Draft]:
        kind = "lobby" if ent == "hours_lobby" else "drive-up"
        fs = [f for f in facts if f.metric == ent]
        if q.branch:
            mine = [f for f in fs if branch_match(q.branch, f)]
            if not mine:
                return Draft.refuse(REFUSE_BRANCH, what=f"{kind} hours", branch=q.branch, org=self.org)
            win = newest(mine)
            return Draft(f"{q.branch} branch {kind} hours: {win.value}.", [win], self.sources(mine, 2))
        if not fs:
            return None
        # No branch named: give the common schedules, adding a schedule only when it brings a new time.
        top, seen_times = [], set()
        for value, _ in Counter(f.value for f in fs).most_common():
            times = set(TIME_RE.findall(value))
            if not top or (times - seen_times):
                top.append(value)
                seen_times |= times
            if len(top) >= 4:
                break
        lead = f"No, {kind} hours vary by branch. " if q.intent == "aggregate" else f"{kind.capitalize()} hours vary by branch. "
        lines = [f"Most branches: {top[0]}"] + [f"Some branches: {v}" for v in top[1:]]
        used = [f for f in fs if f.value in top]
        urls = self.sources(used, 3)
        contact = self.page_url(sid, ["/contact"])
        if contact:
            urls.insert(0, (contact, "Branch locator"))
        return Draft(lead + "; ".join(lines) + ". Which branch are you asking about?", used, urls)

    def _address(self, q, sid: str, facts: List[Fact]) -> Optional[Draft]:
        if not q.branch:
            return None
        mine = [f for f in facts if f.metric == "address" and branch_match(q.branch, f)]
        if not mine:
            return Draft.refuse(REFUSE_BRANCH, what="an address", branch=q.branch, org=self.org)
        win = max(mine, key=lambda f: (f.authority, f.article_date or date.min, len(f.value)))
        urls = self.sources(mine, 2)
        contact = self.page_url(sid, ["/contact"])
        if contact and all(url_key(u) != url_key(contact) for u, _ in urls):
            urls.append((contact, "Branch locator"))
        return Draft(f"The {q.branch} branch is at {win.value}.", [win], urls)

    def _closure(self, q, sid: str, facts: List[Fact], ref_date: date) -> Optional[Draft]:
        if not q.branch:
            return None
        mine = [f for f in facts if f.metric == "close_date" and branch_match(q.branch, f)]
        if not mine:
            return Draft(f"The website doesn't mention a closing for the {q.branch} branch. "
                         f"Please contact {self.org} to confirm.", confident=False)
        win = newest(mine)
        when = parse_long_date(win.value)
        asks_if_open = re.search(r"still open|open today|is it open|remain open", q.raw, re.I)
        if asks_if_open and when and when <= ref_date:
            text = f"No. The {q.branch} branch was scheduled to close {win.value}."
        elif asks_if_open:
            text = f"The {q.branch} branch is scheduled to close {win.value}."
        else:
            text = f"The {q.branch} branch was scheduled to close {win.value}."
        alt = self._closure_alternatives(sid, win)
        if alt:
            text += f" Members can use the {alt} branches instead."
        return Draft(text, [win], self.sources([win]))

    def _closure_alternatives(self, sid: str, f: Fact) -> Optional[str]:
        page = self.pages.get(sid, {}).get(f.url)
        if not page:
            return None
        m = re.search(r"full-service branches at ([A-Z][\w ]+?) and ([A-Z][\w ]+?)[,.”\"]", page.get("text", ""))
        return f"{m.group(1).strip()} and {m.group(2).strip()}" if m else None

    def _eligibility(self, sid: str) -> Optional[Draft]:
        """The 'who can join' bullets plus the states served, from the join or membership page."""
        best = None
        for url, meta in self.pages.get(sid, {}).items():
            text = meta.get("text", "")
            m = re.search(r"(?:eligible to join|who can join|eligible for membership|membership eligibility)(.{0,900})",
                          text, re.I)
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
        states = STATES_RE.search(text)
        parts = []
        if bullets:
            parts.append(f"You're eligible to join {self.org} if " + "; or ".join(b[0].lower() + b[1:] for b in bullets) + ".")
        if states:
            parts.append(f"{self.org}'s charter area covers counties in {states.group(1).strip()}.")
        return Draft(" ".join(parts), urls=[(url, tail[:200])]) if parts else None

    def _account_howto(self, q, sid: str) -> Optional[Draft]:
        """Account maintenance: online banking plus the member phone line, both read from the contact page."""
        contact = self.page_url(sid, ["/contact"])
        if not contact:
            return None
        text = self.pages[sid][contact].get("text", "")
        phone = re.search(r"\b8\d\d-\d{3}-\d{4}\b", text)
        shine = re.search(r"(Shine (?:Online|Mobile)[^.]{0,80}\.)", text)
        what = re.search(r"(contact information|contact info|address|phone number|email address|e-mail|name|beneficiar\w+)",
                         q.raw, re.I)
        thing = what.group(1).lower() if what else "account details"
        bits = [f"You can update your {thing} by logging in to Shine Online or Mobile Banking"]
        if shine:
            bits[0] += " (use the Contact Us tab for account-specific requests)"
        if phone:
            bits.append(f"or by calling {self.org} at {phone.group(0)}")
        return Draft(", ".join(bits) + ".", urls=[(contact, shine.group(1) if shine else text[:160])])

    def _phone(self, sid: str) -> Optional[Draft]:
        contact = self.page_url(sid, ["/contact"])
        if not contact:
            return None
        text = self.pages[sid][contact].get("text", "")
        m = re.search(r"Phone:?\s*(\d{3}-\d{3}-\d{4})", text) or re.search(r"\b(8\d\d-\d{3}-\d{4})\b", text)
        return Draft(f"You can reach {self.org} at {m.group(1)}.", urls=[(contact, m.group(0))]) if m else None
