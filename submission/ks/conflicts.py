"""Find places where the website contradicts itself and decide which value wins."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Dict, List, Tuple

from .model import Fact
from .pages import url_key
from .store import FactStore, best_of

MAX_CONFLICTS = 80


def _topic(f: Fact) -> str:
    from .answer import _product_name, _term_text, _tier_phrase
    bits = []
    if f.family == "entity":
        return f.label or f.product
    term = _term_text(f.term_months) if f.term_months and not re.search(r"month|year", f.product, re.I) else ""
    name = _product_name(f)
    tier = _tier_phrase(f)
    metric = {"apy": "APY", "dividend_rate": "dividend rate", "apr": "APR", "rate": "rate"}.get(f.metric, f.metric)
    if f.family in ("auto", "atv", "boat_rv"):
        from .model import FAMILY_NAMES
        name = FAMILY_NAMES[f.family]
    bits = [term, name, f"({tier})" if tier else "", metric]
    if f.business:
        bits.insert(0, "business")
    return " ".join(b for b in bits if b)


def _why(win: Fact, losers: List[Fact], cross: bool) -> str:
    wk = url_key(win.url)
    pages = sorted({url_key(l.url) for l in losers})
    cls = "rate page" if win.authority >= 100 else "product page" if win.authority >= 85 else "newest release"
    eff = f" effective {win.effective.strftime('%m/%d/%Y')}" if win.effective else ""
    if cross:
        return (f"{wk} is the authoritative {cls}{eff} and shows the current value; older values appeared in earlier "
                f"snapshots and still show on {', '.join(pages)}.")
    kinds = []
    for p in pages:
        if "calculator" in p:
            kinds.append("calculator")
        elif p.endswith("-lp") or "switch-and-earn" in p or "homebuying" in p or "earn-more" in p:
            kinds.append("promo landing page")
        elif "newsroom" in p or "learn" in p:
            kinds.append("article")
        else:
            kinds.append("secondary page")
    return (f"{wk} is the authoritative {cls}{eff}; {', '.join(pages)} ({', '.join(sorted(set(kinds)))}) "
            f"still show an older or different value.")


def find_conflicts(store: FactStore) -> List[dict]:
    latest = store.latest
    out: List[dict] = []
    seen_keys = set()

    # 1. Within the latest snapshot: same fact, different values on different pages.
    groups: Dict[tuple, List[Fact]] = defaultdict(list)
    for f in store.facts[latest]:
        if f.metric in ("apy", "apr", "rate", "dividend_rate") or f.family == "entity":
            groups[_group_key(f)].append(f)
    for key, fs in groups.items():
        values = {f.value for f in fs}
        if len(values) < 2:
            continue
        if key[0] == "entity" and key[1] not in ("branch count", "Forbes recognition", "routing number"):
            continue
        win = best_of(fs) if key[0] != "entity" else max(fs, key=lambda f: (f.article_date or date.min, f.authority))
        losers = [f for f in fs if f.value != win.value]
        seen_keys.add(key)
        out.append(_entry(win, fs, losers, cross=False, salience=3 + (win.authority >= 100)))

    # 2. Across snapshots: the authoritative value moved. Include the old value's pages.
    hist: Dict[tuple, Dict[str, List[Fact]]] = defaultdict(lambda: defaultdict(list))
    for sid, _ in store.snapshots:
        for f in store.facts[sid]:
            if f.metric in ("apy", "apr", "rate") and f.authority >= 85 and not f.business:
                hist[_group_key(f)][sid].append(f)
    for key, by_sid in hist.items():
        if key in seen_keys or latest not in by_sid:
            continue
        series = [(sid, best_of(fs)) for sid, _ in store.snapshots for fs in [by_sid.get(sid)] if fs]
        values = [w.value for _, w in series]
        if len(set(values)) < 2:
            continue
        win = series[-1][1]
        losers = [w for _, w in series if w.value != win.value]
        out.append(_entry(win, [w for _, w in series], losers, cross=True, salience=1 + (len(set(values)) > 2)))

    out.sort(key=lambda e: -e["salience"])
    dedup, seen_topics = [], set()
    for e in out:
        t = e["topic"].lower()
        if t in seen_topics:
            continue
        seen_topics.add(t)
        dedup.append(e)
    return dedup[:MAX_CONFLICTS]


def _group_key(f: Fact) -> tuple:
    """Like soft_key but tier labels that drift over time (model years) collapse by term."""
    k = list(f.soft_key())
    if f.family in ("auto", "atv") and f.model_years:
        k[5] = "newest" if f.model_years[1] >= 2026 else f.model_years
    return tuple(k)


def _entry(win: Fact, all_facts: List[Fact], losers: List[Fact], cross: bool, salience: int) -> dict:
    values = []
    for f in sorted(all_facts, key=lambda x: (x.snapshot_id, -x.authority)):
        if f.value not in values:
            values.append(f.value)
    values.sort(key=lambda v: v != win.value)       # winner first
    sources = []
    seen = set()
    for f in sorted(all_facts, key=lambda x: (x.value != win.value, -x.authority, x.snapshot_id)):
        k = (url_key(f.url), f.value)
        if k in seen:
            continue
        seen.add(k)
        sources.append({"url": f.url, "snapshot_id": f.snapshot_id, "quote": f.quote[:160]})
        if len(sources) >= 6:
            break
    return {
        "topic": _topic(win),
        "values": values,
        "sources": sources,
        "resolution": win.value,
        "reason": _why(win, losers, cross),
        "salience": salience,
    }
