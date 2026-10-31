"""Answers that come from page text rather than from a fact: links to pages, and extractive free-text answers."""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Tuple

from ..format import tidy
from ..index import Chunk
from ..pages import OTHER
from ..text import pct_values, sentences, tokenize
from .base import AnswerBase
from .draft import REFUSE_GENERIC, REFUSE_RATE, Draft

MIN_HIT_SCORE = 4.0
LINK_TARGETS = {
    "certificate": ["/personal/savings-account", "/rates"], "savings": ["/personal/savings-account", "/rates"],
    "money_market": ["/personal/savings-account", "/rates"], "hsa": ["/personal/savings-account", "/rates"],
    "ira": ["/personal/retirement", "/rates"], "checking": ["/personal/checking-accounts", "/rates"],
    "auto": ["/personal/loans/auto-motorcycle-loans", "/personal/loans/auto-loans", "/rates"],
    "mortgage": ["/personal/loans/home-loans", "/rates"], "credit_card": ["/personal/credit-cards", "/rates"],
    "personal_loan": ["/personal/loans/personal-loans", "/rates"],
    "heloc": ["/personal/loans/home-equity-line-of-credit", "/rates"], "student_loan": ["/personal/loans/student-loans"],
}
BUSINESS_LINK_TARGETS = {"certificate": "/business/savings-accounts", "savings": "/business/savings-accounts",
                         "checking": "/business/checking-accounts", "credit_card": "/business/credit-cards"}
DEFINITIONAL_RE = re.compile(r"^\s*(what is|what's|whats|tell me about|describe|explain|what does .* (?:do|mean|offer))\b", re.I)
WANTS_NUMBER_RE = re.compile(r"how many|how much|what (?:is|was) the (?:number|amount|cost|fee)", re.I)
Hit = Tuple[float, Chunk, str]


class TextAnswers(AnswerBase):
    # ------------------------------------------------------------------ links
    def answer_link(self, q, sid: str) -> Draft:
        pages = self.pages.get(sid, {})
        low = q.raw.lower()
        if re.search(r"\b(join|become a member|sign up|enroll|open an? account)\b", low):
            counts: Counter = Counter()
            for meta in pages.values():
                for link in meta.get("links", []):
                    if "join." in link.lower() or "/join" in link.lower():
                        counts[link.split("?")[0].rstrip("/") + "/"] += 1
            if counts:
                target = counts.most_common(1)[0][0]
                return Draft(f"You can join {self.org} online at {target}", urls=[(target, "")])
        if re.search(r"locator|branch|atm|location|contact|phone", low):
            u = self.page_url(sid, ["/contact"])
            if u:
                return Draft(f"{self.org}'s branch and ATM locator is on the contact page: {u}", urls=[(u, "")])
        if q.family in LINK_TARGETS:
            if q.business:
                u = self.page_url(sid, [BUSINESS_LINK_TARGETS.get(q.family, "/business-rates"), "/business-rates"])
            else:
                u = self.page_url(sid, LINK_TARGETS[q.family])
            if u:
                frag = "#rates" if re.search(r"\brates?\b|apy|apr", low) and "/rates" not in u else ""
                return Draft(f"You can find that on the website at {u}{frag}", urls=[(u, "")])
        if re.search(r"\brates?\b", low):
            u = self.page_url(sid, ["/rates"])
            if u:
                return Draft(f"The rates page is {u}", urls=[(u, "")])
        hits = self.index.search(q.tokens, sid, k=5, url_filter=lambda u: pages.get(u, {}).get("class", 0) >= 60,
                                 url_source=self.store.url_source(sid))
        if hits:
            return Draft(f"The relevant page is {hits[0][2]}", urls=[(hits[0][2], hits[0][1].text[:160])])
        return Draft.refuse(REFUSE_GENERIC, org=self.org)

    # ------------------------------------------------------------------ free text
    def answer_free(self, q, sid: str) -> Draft:
        """One or two sentences from the best chunk; never a whole chunk, never an unverifiable rate."""
        toks = q.tokens
        pages = self.pages.get(sid, {})
        hits = [h for h in self.index.search(toks, sid, k=12, url_source=self.store.url_source(sid))
                if pages.get(h[2], {}).get("class", 0) > OTHER] if toks else []
        if not hits or hits[0][0] < MIN_HIT_SCORE:
            return Draft.refuse(REFUSE_GENERIC, org=self.org)
        qset = set(toks)
        hits = self._rank(hits, qset, definitional=bool(DEFINITIONAL_RE.search(q.raw)))
        wants_number = bool(WANTS_NUMBER_RE.search(q.raw))
        definitional = bool(DEFINITIONAL_RE.search(q.raw))
        for _, chunk, url in hits[:6]:
            if chunk.is_table:
                continue
            sents = sentences(chunk.text)
            picked, lead = self._pick_sentences(sents, qset, wants_number, definitional)
            if not picked:
                continue
            text = self._scrub_stale_rates(" ".join(picked), sid)
            if not text.strip():
                continue
            if q.family is None and re.search(r"\b(rate|apr|apy|interest)\b", q.raw, re.I) and re.search(r"\d+(?:\.\d+)?\s?%", text):
                return Draft.refuse(REFUSE_RATE, thing="that", org=self.org)
            return Draft(tidy(text[:600]), urls=[(url, lead[:200])])
        _, chunk, url = hits[0]
        return Draft(tidy(chunk.text[:400]), urls=[(url, chunk.text[:200])])

    @staticmethod
    def _rank(hits: List[Hit], qset: set, definitional: bool) -> List[Hit]:
        """BM25 order, boosted when the URL slug names what the question asks about; for 'what is X' questions the
        lead paragraph of the best page comes first because quotes further down only mention X."""
        def slug_boost(h: Hit) -> float:
            slug = set(tokenize(re.sub(r"[/_?=&.-]+", " ", h[2].split("//")[-1].split("/", 1)[-1])))
            return h[0] * (1 + 0.15 * len(qset & slug))
        hits = sorted(hits, key=slug_boost, reverse=True)
        if definitional:
            top_url = hits[0][2]
            same = sorted([h for h in hits[:8] if h[2] == top_url and not h[1].is_table],
                          key=lambda h: h[1].pos.get(top_url, 1 << 30))
            if len(same) > 1:
                hits = same + [h for h in hits if h not in same]
        return hits

    @staticmethod
    def _pick_sentences(sents: List[str], qset: set, wants_number: bool, definitional: bool) -> Tuple[List[str], str]:
        scored = []
        for i, s in enumerate(sents):
            overlap = len(qset & set(tokenize(s)))
            if overlap:
                bonus = 0.6 if (wants_number and re.search(r"\d", s)) else 0.0
                scored.append((overlap + bonus - (0.4 if len(s) > 320 else 0.0), i))
        if not scored:
            return [], ""
        scored.sort(key=lambda t: (-t[0], t[1]))            # ties go to the earlier sentence
        i = scored[0][1]
        lead = sents[i]
        if lead.rstrip().endswith("?") and i + 1 < len(sents):   # FAQ layout: question, then the answer
            return sents[i + 1:i + 3], lead
        picked = [lead]
        if i + 1 < len(sents) and len(sents[i + 1]) < 260 and (
                definitional or wants_number or (len(lead) < 160 and set(tokenize(sents[i + 1])) & qset)):
            picked.append(sents[i + 1])
        return picked, lead

    def _scrub_stale_rates(self, text: str, sid: str) -> str:
        """Drop a sentence that quotes a rate the current rate tables do not contain."""
        current = {v for f in self.store.facts[sid] if f.metric in ("apy", "apr", "rate", "dividend_rate")
                   for v in pct_values(f.value)}
        keep = [s for s in (sentences(text) or [text])
                if not (pct_values(s) and current and any(v not in current for v in pct_values(s)))]
        return " ".join(keep) if keep else text
