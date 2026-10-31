"""FactStore: facts per snapshot, with lookups by family/qualifiers and a history across snapshots."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from .model import Fact


class FactStore:
    def __init__(self):
        self.snapshots: List[Tuple[str, date]] = []          # (snapshot_id, taken_on) oldest first
        self.facts: Dict[str, List[Fact]] = defaultdict(list)
        self.by_family: Dict[str, Dict[str, List[Fact]]] = defaultdict(lambda: defaultdict(list))
        self.page_urls: Dict[str, set] = defaultdict(set)
        self.page_links: Dict[str, Dict[str, List[str]]] = defaultdict(dict)   # sid -> url -> outbound links

    def add_snapshot(self, snapshot_id: str, taken_on: date) -> None:
        self.snapshots.append((snapshot_id, taken_on))
        self.snapshots.sort(key=lambda s: s[1])

    def add(self, fact: Fact) -> None:
        self.facts[fact.snapshot_id].append(fact)
        self.by_family[fact.snapshot_id][fact.family].append(fact)

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

    def find(self, sid: str, family: Optional[str] = None, pred: Optional[Callable[[Fact], bool]] = None) -> List[Fact]:
        pool = self.by_family[sid][family] if family else self.facts[sid]
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
