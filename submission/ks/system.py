"""KnowledgeSystem: the object the harness talks to."""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Dict, Optional

from .answer import Composer, Draft, _plain
from .conflicts import find_conflicts
from .entities import extract_entities, extract_prose_facts
from .index import ChunkIndex
from .pages import BoilerplateFilter, article_date, classify
from .query import merge_llm, parse_rules
from .store import FactStore
from .tables import parse_tables, rename_generic_products, table_to_facts
from .text import numbers_in, parse_iso, strip_markdown

URL_IN_TEXT = re.compile(r"https?://[^\s)\]>\"']+")


def _org_name(pages) -> Optional[str]:
    """The institution's name, from the most common '| Name' suffix in page titles."""
    from collections import Counter
    c: Counter = Counter()
    for p in pages:
        m = re.search(r"\|\s*([A-Z][\w&' .-]{1,40})\s*$", p.title or "")
        if m:
            c[m.group(1).strip()] += 1
    if not c:
        return None
    name, n = c.most_common(1)[0]
    return name if n >= 10 else None


class KnowledgeSystem:
    def __init__(self, contract_module, use_llm: Optional[bool] = None):
        self.c = contract_module
        self.store = FactStore()
        self.index = ChunkIndex()
        self.pages: Dict[str, Dict[str, dict]] = {}
        self.composer = Composer(self.store, self.index, self.pages)
        self._cache: Dict[tuple, object] = {}
        self._conflicts = None
        self.llm = None
        if use_llm is None:
            use_llm = os.environ.get("KS_DISABLE_LLM", "") == "" and bool(os.environ.get("ANTHROPIC_API_KEY"))
        if use_llm:
            try:
                from .llm import LLMParser
                self.llm = LLMParser()
            except Exception:
                self.llm = None

    # ------------------------------------------------------------------ ingest
    def ingest(self, snapshot) -> None:
        sid = snapshot.snapshot_id
        taken = parse_iso(snapshot.taken_on) or date.today()
        self.store.add_snapshot(sid, taken)
        boiler = BoilerplateFilter(snapshot.pages)
        pages: Dict[str, dict] = {}
        table_facts = []
        for p in snapshot.pages:
            cls = classify(p.url, p.title)
            md = p.markdown or ""
            self.store.add_page(sid, p.url)
            pdate = article_date(md) if cls in (60, 50) else None
            fetched = parse_iso(p.fetched_at)
            tables = parse_tables(md)
            for t in tables:
                table_facts += table_to_facts(t, p.url, sid, cls, pdate, fetched)
            for f in extract_entities(md, p.url, p.title or "", sid, cls, pdate, fetched):
                self.store.add(f)
            table_facts += extract_prose_facts(md, p.url, p.title or "", sid, cls, pdate, fetched, taken)
            cleaned = boiler.clean(md)
            self.index.add_page(cleaned, p.url, sid, cls)
            pages[p.url] = {"title": p.title or "", "class": cls, "links": URL_IN_TEXT.findall(md)[:400],
                            "text": strip_markdown(cleaned)[:20000], "date": pdate}
        rename_generic_products(table_facts)
        for f in table_facts:
            self.store.add(f)
        # Pages missing from this crawl stay known from the last crawl that had them.
        for prev_sid in [s for s, _ in self.store.snapshots if s != sid]:
            for url, meta in self.pages.get(prev_sid, {}).items():
                if url not in pages and self.store.url_source(sid).get(url) == prev_sid:
                    pages[url] = {**meta, "class": max(0, meta["class"] - 10), "carried_from": prev_sid}
        self.pages[sid] = pages
        self.composer.org = _org_name(snapshot.pages) or self.composer.org
        self._cache.clear()
        self._conflicts = None

    # ------------------------------------------------------------------ answer
    def answer(self, question: str, as_of: Optional[str] = None):
        key = (re.sub(r"\s+", " ", (question or "").strip().lower()), as_of or "")
        if key in self._cache:
            return self._cache[key]
        ans = self._answer(question or "", as_of)
        self._cache[key] = ans
        return ans

    def _answer(self, question: str, as_of: Optional[str]):
        q = parse_rules(question)
        if self.llm is not None:
            try:
                q = merge_llm(q, self.llm.parse(question))
            except Exception:
                pass
        as_of_date = parse_iso(as_of) or q.as_of_text
        sid, exact = self.store.select(as_of_date)
        ref_date = max(as_of_date or date.min, self.store.taken_on(sid))
        if as_of_date is None and re.search(r"\b(20\d\d)\b", question):
            m = re.search(r"\b(20\d\d)\b", question)
            ref_date = max(ref_date, date(int(m.group(1)), 12, 31)) if not re.search(r"model|vehicle|car", question, re.I) else ref_date
        draft = self.composer.compose(q, sid, exact, ref_date)
        return self._finalize(draft, q, sid, question)

    def _finalize(self, d: Draft, q, sid: str, question: str):
        text = _plain(d.text)
        if not d.confident:
            qnums = numbers_in(question)
            if numbers_in(text) - qnums:
                text = "I don't know; the website doesn't say. Please contact Dupaco for details."
        sources = [self.c.Source(url=u, snapshot_id=sid, quote=(quote or None)) for u, quote in d.urls]
        if not sources and d.facts:
            seen = set()
            for f in sorted(d.facts, key=lambda x: -x.authority):
                if f.url in seen:
                    continue
                seen.add(f.url)
                sources.append(self.c.Source(url=f.url, snapshot_id=sid, quote=f.quote[:200] or None))
                if len(sources) >= 3:
                    break
        return self.c.Answer(text=text, sources=sources, confident=bool(d.confident), conflict_note=d.conflict_note)

    # ------------------------------------------------------------------ conflicts
    def conflicts(self):
        if self._conflicts is None:
            entries = find_conflicts(self.store)
            self._conflicts = [
                self.c.Conflict(
                    topic=e["topic"], values=e["values"],
                    sources=[self.c.Source(url=s["url"], snapshot_id=s["snapshot_id"], quote=s["quote"] or None) for s in e["sources"]],
                    resolution=e["resolution"], reason=e["reason"],
                ) for e in entries
            ]
        return self._conflicts
