"""Find places where the website contradicts itself and decide which value wins."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Dict, List

from .format import product_name, term_text, tier_phrase
from .model import FAMILY_NAMES, Fact
from .pages import url_key
from .store import FactStore, best_of

MAX_CONFLICTS = 60
ENTITY_TOPICS = {"branch count", "forbes recognition", "routing number", "employee count"}


def _topic(f: Fact, drop_tier: bool = False) -> str:
    if f.family == "entity":
        return f.label or f.product
    metric = {"apy": "APY", "dividend_rate": "dividend rate", "apr": "APR", "rate": "rate"}.get(f.metric, f.metric)
    fam = FAMILY_NAMES.get(f.family, f.family)
    name = product_name(f)
    if f.family in ("auto", "atv", "boat_rv"):
        name = ""
    if f.family == "mortgage":
        name = re.sub(r"\s*\$[\d,]+ or less", "", name)
    term = term_text(f.term_months) if f.term_months and not re.search(r"month|year", name, re.I) else ""
    tier = "" if drop_tier else tier_phrase(f)
    bits = ["business" if f.business else "", fam if fam.lower() not in name.lower() else "", term, name,
            f"({tier})" if tier else ("(all tiers)" if drop_tier else ""), metric]
    return " ".join(b for b in bits if b)


def _why(win: Fact, losers: List[Fact], cross: bool) -> str:
    wk = url_key(win.url)
    pages = sorted({url_key(f.url) for f in losers})
    cls = "rate page" if win.authority >= 100 else "product page" if win.authority >= 85 else "newest release"
    eff = f" effective {win.effective.strftime('%m/%d/%Y')}" if win.effective else ""
    if cross:
        return (f"{wk} is the authoritative {cls}{eff} and shows the current value; the other values are from earlier "
                f"snapshots of {', '.join(pages)} and are superseded.")
    kinds = set()
    for p in pages:
        if "calculator" in p:
            kinds.add("calculator")
        elif p.endswith("-lp") or "switch-and-earn" in p or "homebuying" in p or "earn-more" in p or "refi" in p:
            kinds.add("promo landing page")
        elif "newsroom" in p or "learn" in p:
            kinds.add("article")
        else:
            kinds.add("secondary page")
    return (f"{wk} is the authoritative {cls}{eff}; {', '.join(pages)} ({', '.join(sorted(kinds))}) "
            f"still show an older or different value.")


def find_conflicts(store: FactStore) -> List[dict]:
    latest = store.latest
    out: List[dict] = []
    seen_keys = set()

    # 1. Within the latest snapshot: same fact, different values on different pages.
    groups: Dict[tuple, List[Fact]] = defaultdict(list)
    for f in store.facts[latest]:
        if f.metric in ("apy", "apr", "rate", "dividend_rate") or f.family == "entity":
            groups[f.group_key()].append(f)
    for key, fs in groups.items():
        values = {f.value for f in fs}
        if len(values) < 2:
            continue
        if key[0] == "entity":
            if key[2] not in ENTITY_TOPICS:
                continue
            win = max(fs, key=lambda f: (f.article_date or date.min, f.authority))
        else:
            win = best_of(fs)
        losers = [f for f in fs if f.value != win.value]
        seen_keys.add(key)
        out.append(_entry(win, fs, losers, cross=False, salience=3 + (win.authority >= 100), key=key))

    # 2. Across snapshots: the authoritative value moved.
    hist: Dict[tuple, Dict[str, List[Fact]]] = defaultdict(lambda: defaultdict(list))
    for sid, _ in store.snapshots:
        for f in store.facts[sid]:
            if f.metric in ("apy", "apr", "rate") and f.authority >= 85 and not f.business:
                hist[f.group_key()][sid].append(f)
    for key, by_sid in hist.items():
        if key in seen_keys or latest not in by_sid:
            continue
        series = [(sid, best_of(fs)) for sid, _ in store.snapshots for fs in [by_sid.get(sid)] if fs]
        values = [w.value for _, w in series]
        if len(set(values)) < 2:
            continue
        win = series[-1][1]
        losers = [w for _, w in series if w.value != win.value]
        out.append(_entry(win, [w for _, w in series], losers, cross=True, salience=1 + (len(set(values)) > 2), key=key))

    out = _merge_tiers(out)
    out = _drop_ira_duplicates(out)
    out.sort(key=lambda e: (-e["salience"], e["topic"]))
    dedup, seen_topics = [], set()
    for e in out:
        t = e["topic"].lower()
        if t in seen_topics:
            continue
        seen_topics.add(t)
        dedup.append(e)
    return dedup[:MAX_CONFLICTS]


def _tierless(key: tuple) -> tuple:
    """Group key without the balance / loan-amount tier, used to merge sibling tiers of one product."""
    k = list(key)
    k[6] = None   # balance
    k[7] = None   # amount
    return tuple(k)


def _merge_tiers(entries: List[dict]) -> List[dict]:
    """Twelve mortgage tiers that all went stale on the same page are one contradiction, not twelve."""
    by: Dict[tuple, List[dict]] = defaultdict(list)
    for e in entries:
        by[_tierless(e["key"])].append(e)
    merged: List[dict] = []
    for key, es in by.items():
        if len(es) == 1 or key[0] in ("auto", "atv", "entity"):
            merged.extend(es)
            continue
        base = max(es, key=lambda e: e["salience"])
        values, sources, seen = [], [], set()
        for e in sorted(es, key=lambda e: e["values"][0] != base["values"][0]):
            for v in e["values"]:
                if v not in values:
                    values.append(v)
            for s in e["sources"]:
                k = (url_key(s["url"]), s["snapshot_id"])
                if k not in seen and len(sources) < 8:
                    seen.add(k)
                    sources.append(s)
        per_tier, seen_res = [], set()
        for e in sorted(es, key=lambda e: -(e["win"].amount or e["win"].balance or (0, 0))[1]):
            if e["resolution"] in seen_res:
                continue
            seen_res.add(e["resolution"])
            tier = tier_phrase(e["win"])
            per_tier.append(f"{e['resolution']} ({tier})" if tier and len(es) > 1 else e["resolution"])
        resolution = base["resolution"] if len(per_tier) == 1 else "; ".join(per_tier)
        merged.append({**base, "topic": _topic(base["win"], drop_tier=True), "values": values, "sources": sources,
                       "resolution": resolution})
    return merged


def _drop_ira_duplicates(entries: List[dict]) -> List[dict]:
    cert = {(e["key"][4], e["key"][8], e["key"][9], e["key"][3], tuple(sorted(e["values"]))) for e in entries if e["key"][0] == "certificate"}
    out = []
    for e in entries:
        k = e["key"]
        if k[0] == "ira" and (k[4], k[8], k[9], k[3], tuple(sorted(e["values"]))) in cert:
            continue
        out.append(e)
    return out


def _entry(win: Fact, all_facts: List[Fact], losers: List[Fact], cross: bool, salience: int, key: tuple) -> dict:
    values = []
    for f in sorted(all_facts, key=lambda x: (x.snapshot_id, -x.authority)):
        if f.value not in values:
            values.append(f.value)
    values.sort(key=lambda v: v != win.value)       # winner first
    sources, seen = [], set()
    for f in sorted(all_facts, key=lambda x: (x.value != win.value, -x.authority, x.snapshot_id)):
        k = (url_key(f.url), f.value)
        if k in seen:
            continue
        seen.add(k)
        sources.append({"url": f.url, "snapshot_id": f.snapshot_id, "quote": f.quote[:160]})
        if len(sources) >= 6:
            break
    return {
        "topic": _topic(win), "values": values, "sources": sources, "resolution": win.value,
        "reason": _why(win, losers, cross), "salience": salience, "key": key, "win": win,
    }
