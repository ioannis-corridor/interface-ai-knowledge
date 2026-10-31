"""Fee questions answered from fee-schedule facts. Every content word of the question must appear in the fee
label (through a small synonym table), otherwise the system refuses rather than naming a neighbouring fee."""
from __future__ import annotations

import re
from typing import List, Set

from ..text import tokenize
from .base import AnswerBase
from .draft import REFUSE_FEE, Draft

FEE_NOISE = {"fee", "cost", "charge", "price", "much", "pay", "account", "service", "member", "non-member", "per", "item",
             "each", "month", "what", "there", "any", "money", "penalty", "send", "sending", "get", "do", "you", "use",
             "using"}
FEE_SYNONYMS = {
    "lost": {"lost", "replacement", "replace", "reissue"}, "replacement": {"replacement", "replace", "reissue", "lost"},
    "wire": {"wire"}, "incoming": {"incoming", "inbound"}, "outgoing": {"outgoing", "domestic", "outbound"},
    "overdraft": {"overdraft", "nsf", "insufficient"}, "bounced": {"overdraft", "nsf", "returned"},
    "cashier": {"official", "cashier", "certified"}, "official": {"official"}, "check": {"check", "draft"},
    "foreign": {"foreign", "international"}, "international": {"international", "foreign"},
    "overseas": {"international", "foreign"}, "abroad": {"international", "foreign"},
    "return": {"returned", "return"}, "returned": {"returned", "return"},
    "inactive": {"inactive", "dormant"}, "dormant": {"inactive", "dormant"},
    "closing": {"closed", "closing"}, "closed": {"closed", "closing"}, "early": {"prior", "early"},
}
LEADING_WORDS = re.compile(r"^(what's|what|how much|is|are|the|a|an|does|do|you|charge|for|cost|of|fee|fees|there|it|much|will)\b\s*",
                           re.I)


def _alternatives(token: str) -> Set[str]:
    return FEE_SYNONYMS.get(token) or FEE_SYNONYMS.get(token + "s") or {token}


def _subject(question: str) -> str:
    thing = question.strip(" ?.")
    for _ in range(6):
        thing = LEADING_WORDS.sub("", thing)
    return thing or "that"


class FeeAnswers(AnswerBase):
    def answer_fee(self, q, sid: str) -> Draft:
        fees = self.facts(sid, "fee")
        thing = _subject(q.raw)
        keys: List[str] = [t for t in q.tokens if t not in FEE_NOISE and not t.isdigit()]
        if not fees or not keys:
            return Draft.refuse(REFUSE_FEE, thing=thing, org=self.org)
        matches = []
        for f in fees:
            label_tokens = set(tokenize(f.product))
            if all(_alternatives(k) & label_tokens for k in keys):
                extra = len(label_tokens - {t for k in keys for t in _alternatives(k)})
                matches.append((-extra, f.authority, f))        # the most specific label wins
        if not matches:
            return Draft.refuse(REFUSE_FEE, thing=thing, org=self.org)
        matches.sort(key=lambda t: (t[0], t[1]), reverse=True)
        best = matches[0][2]
        win, agree, note = self.resolve([f for f in fees if f.product == best.product])
        label = win.product[0].lower() + win.product[1:]
        if win.value.lower().startswith(("free", "no charge")):
            text = f"{win.product} is free of charge."
        else:
            text = f"The fee for {label} is {win.value}."
        return Draft(text, agree, self.sources(agree, 2), conflict_note=note)
