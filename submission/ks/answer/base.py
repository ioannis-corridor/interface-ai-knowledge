"""Shared state and helpers for the answer handlers."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..index import ChunkIndex
from ..model import Fact
from ..pages import url_key
from ..store import FactStore, best_of, group_values
from ..text import tokenize

DEPOSIT = {"certificate", "ira", "savings", "money_market", "hsa", "checking"}
PRIMARY_METRIC = {**dict.fromkeys(DEPOSIT, "apy"), "mortgage": "rate", "credit_card": "apr"}


class AnswerBase:
    def __init__(self, store: FactStore, index: ChunkIndex, pages: Dict[str, Dict[str, dict]]):
        self.store = store
        self.index = index
        self.pages = pages                  # snapshot_id -> url -> {"title", "class", "links", "text", "date"}
        self.org = "the credit union"       # replaced with the institution's name found in page titles

    def facts(self, sid: str, family: str) -> List[Fact]:
        return self.store.find(sid, family)

    def companion(self, sid: str, f: Fact, metric: str) -> Optional[Fact]:
        """The same table row read for another metric (dividend rate next to an APY, APR next to a rate)."""
        for g in self.store.find(sid, f.family):
            if g.metric == metric and g.url == f.url and g.quote == f.quote:
                return g
        return None

    @staticmethod
    def sources(facts: List[Fact], limit: int = 4) -> List[Tuple[str, str]]:
        """Distinct pages behind these facts, most authoritative first."""
        seen, out = set(), []
        for f in sorted(facts, key=lambda x: (-x.authority, x.url)):
            key = url_key(f.url)
            if key in seen:
                continue
            seen.add(key)
            out.append((f.url, f.quote[:200]))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def resolve(facts: List[Fact]) -> Tuple[Optional[Fact], List[Fact], Optional[str]]:
        """Pick the winning copy of ONE fact; report the lower-authority copies that disagree."""
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

    def page_url(self, sid: str, paths: List[str]) -> Optional[str]:
        """The first page in this snapshot whose path ends with one of `paths`."""
        pages = self.pages.get(sid, {})
        for p in paths:
            for url in pages:
                if url_key(url).endswith(p.rstrip("/").lower()):
                    return url
        return None


BRANCH_NOISE = {"branch", "avenue", "ave", "street", "st", "road", "rd", "drive", "dr", "lane", "ln", "blvd"}


def branch_match(wanted: str, f: Fact) -> bool:
    """Does fact `f` (hours, address, closure) belong to the branch the question names?"""
    want = {t for t in tokenize(wanted) if t not in BRANCH_NOISE}
    if not want:
        return False
    hay = " ".join([f.product, f.extra.get("branch") or "", f.extra.get("city") or "", f.extra.get("street") or "",
                    f.value if f.metric == "address" else ""])
    return want <= set(tokenize(hay))


def product_match(wanted: str, actual: str) -> bool:
    w, a = wanted.lower(), actual.lower()
    if w == a or w in a:
        return True
    want = {t for t in tokenize(w) if t not in ("account", "visa", "card")}
    return bool(want) and want <= set(tokenize(a))
