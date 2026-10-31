"""FactStore: facts per snapshot, with lookups by family/qualifiers and a history across snapshots.

Snapshots are cumulative crawls, so a URL that is missing from snapshot S is *carried forward* from the newest earlier
snapshot that had it (at reduced authority). That keeps history without letting a vanished promo page outrank the
live rate sheet.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Callable, Dict, List, Optional, Set, Tuple

from .model import Fact

CARRY_PENALTY = 10


class FactStore:
    def __init__(self):
        self.snapshots: List[Tuple[str, date]] = []          # (snapshot_id, taken_on) oldest first
        self.facts: Dict[str, List[Fact]] = defaultdict(list)   # own facts per snapshot
        self.page_urls: Dict[str, Set[str]] = defaultdict(set)
        self._effective: Dict[str, List[Fact]] = {}
        self._by_family: Dict[str, Dict[str, List[Fact]]] = {}
        self._url_source: Dict[str, Dict[str, str]] = {}

    def add_snapshot(self, snapshot_id: str, taken_on: date) -> None:
        self.snapshots.append((snapshot_id, taken_on))
        self.snapshots.sort(key=lambda s: s[1])
        self._effective.clear()
        self._by_family.clear()
        self._url_source.clear()

    def add(self, fact: Fact) -> None:
        self.facts[fact.snapshot_id].append(fact)
        self._effective.pop(fact.snapshot_id, None)
        self._by_family.pop(fact.snapshot_id, None)

    def add_page(self, snapshot_id: str, url: str) -> None:
        self.page_urls[snapshot_id].add(url)

    @property
    def latest(self) -> str:
        return self.snapshots[-1][0]

    def select(self, as_of: Optional[date]) -> Tuple[str, bool]:
        """Newest snapshot taken on or before as_of. -> (snapshot_id, exact) ; exact=False when as_of predates all."""
        if as_of is None:
            return self.latest, True
        chosen = None
        for sid, taken in self.snapshots:
            if taken <= as_of:
                chosen = sid
        if chosen is None:
            return self.snapshots[0][0], False
        return chosen, True

    def taken_on(self, sid: str) -> date:
        return next(t for s, t in self.snapshots if s == sid)

    def url_source(self, sid: str) -> Dict[str, str]:
        """For snapshot `sid`: url -> the snapshot whose copy of that url is current (itself, or a carried one)."""
        if sid not in self._url_source:
            src: Dict[str, str] = {}
            for s, _ in self.snapshots:
                for u in self.page_urls[s]:
                    src[u] = s
                if s == sid:
                    break
            self._url_source[sid] = src
        return self._url_source[sid]

    def effective(self, sid: str) -> List[Fact]:
        if sid not in self._effective:
            src = self.url_source(sid)
            own = self.facts[sid]
            carried = []
            for s, _ in self.snapshots:
                if s == sid:
                    break
                for f in self.facts[s]:
                    if src.get(f.url) == s:
                        carried.append(replace(f, authority=f.authority - CARRY_PENALTY, extra={**f.extra, "carried_from": s}))
            self._effective[sid] = own + carried
            fam: Dict[str, List[Fact]] = defaultdict(list)
            for f in self._effective[sid]:
                fam[f.family].append(f)
            self._by_family[sid] = fam
        return self._effective[sid]

    def find(self, sid: str, family: Optional[str] = None, pred: Optional[Callable[[Fact], bool]] = None) -> List[Fact]:
        self.effective(sid)
        pool = self._by_family[sid].get(family, []) if family else self._effective[sid]
        return [f for f in pool if pred is None or pred(f)]

    def history(self, pred: Callable[[Fact], bool]) -> List[Tuple[str, date, List[Fact]]]:
        return [(sid, taken, [f for f in self.facts[sid] if pred(f)]) for sid, taken in self.snapshots]


def best_of(facts: List[Fact]) -> Optional[Fact]:
    """Authority first, then newest effective date, then newest article date, then newest fetch."""
    if not facts:
        return None
    return max(facts, key=lambda f: (f.authority, f.effective or date.min, f.article_date or date.min,
                                     f.fetched_at or date.min, -len(f.url)))


def group_values(facts: List[Fact]) -> Dict[str, List[Fact]]:
    out: Dict[str, List[Fact]] = defaultdict(list)
    for f in facts:
        out[f.value].append(f)
    return out
