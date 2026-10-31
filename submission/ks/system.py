"""KnowledgeSystem: the object the harness drives through ingest / answer / conflicts."""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date
from typing import Dict, List, Optional

from .answer import Composer, Draft
from .conflicts import find_conflicts
from .entities import extract_entities, extract_prose_facts
from .format import plain_text
from .index import ChunkIndex
from .pages import LEARN, NEWSROOM, BoilerplateFilter, article_date, classify
from .query import merge_llm, needs_llm, parse_rules
from .store import FactStore
from .tables import parse_tables, rename_generic_products, table_to_facts
from .text import numbers_in, parse_iso, strip_markdown, tokenize

log = logging.getLogger("ks")
URL_IN_TEXT = re.compile(r"https?://[^\s)\]>\"']+")
CARRIED_PAGE_PENALTY = 10
NUMBERLESS_REFUSAL = "I don't know; the website doesn't say. Please contact {org} for details."


class KnowledgeSystem:
    def __init__(self, contract_module, use_llm: Optional[bool] = None):
        self.c = contract_module
        self.store = FactStore()
        self.index = ChunkIndex()
        self.pages: Dict[str, Dict[str, dict]] = {}
        self.composer = Composer(self.store, self.index, self.pages)
        self._cache: Dict[tuple, object] = {}
        self._conflicts = None
        self.llm = self._make_llm(use_llm)

    @staticmethod
    def _make_llm(use_llm: Optional[bool]):
        if use_llm is None:
            use_llm = not os.environ.get("KS_DISABLE_LLM") and bool(os.environ.get("ANTHROPIC_API_KEY"))
        if not use_llm:
            return None
        try:
            from .llm import LLMParser
            return LLMParser()
        except Exception as exc:  # the SDK is optional; the rules parser covers everything
            log.warning("LLM parser unavailable (%s); using the rules parser only", exc)
            return None

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
            pdate = article_date(md) if cls in (NEWSROOM, LEARN) else None
            fetched = parse_iso(p.fetched_at)
            for t in parse_tables(md):
                table_facts += table_to_facts(t, p.url, sid, cls, pdate, fetched)
            table_facts += extract_prose_facts(md, p.url, p.title or "", sid, cls, pdate, fetched)
            for f in extract_entities(md, p.url, p.title or "", sid, cls, pdate, fetched):
                self.store.add(f)
            cleaned = boiler.clean(md)
            self.index.add_page(cleaned, p.url, sid, cls)
            pages[p.url] = {"title": p.title or "", "class": cls, "links": URL_IN_TEXT.findall(md)[:400],
                            "text": strip_markdown(cleaned)[:20000], "date": pdate}
        rename_generic_products(table_facts)
        for f in table_facts:
            self.store.add(f)
        # Pages missing from this crawl stay known from the last crawl that had them.
        source = self.store.url_source(sid)
        for prev_sid in [s for s, _ in self.store.snapshots if s != sid]:
            for url, meta in self.pages.get(prev_sid, {}).items():
                if url not in pages and source.get(url) == prev_sid:
                    pages[url] = {**meta, "class": max(0, meta["class"] - CARRIED_PAGE_PENALTY), "carried_from": prev_sid}
        self.pages[sid] = pages
        self.composer.org = institution_name(snapshot.pages) or self.composer.org
        self._cache.clear()
        self._conflicts = None
        log.info("ingested %s: %d pages, %d facts", sid, len(snapshot.pages), len(self.store.facts[sid]))

    # ------------------------------------------------------------------ answer
    def answer(self, question: str, as_of: Optional[str] = None):
        key = (re.sub(r"\s+", " ", (question or "").strip().lower()), as_of or "")
        if key not in self._cache:
            try:
                self._cache[key] = self._answer(question or "", as_of)
            except Exception:  # a bug must not turn into a crash; an honest refusal is the safe output
                log.exception("answer() failed for %r", question)
                self._cache[key] = self.c.Answer(text=NUMBERLESS_REFUSAL.format(org=self.composer.org), confident=False)
        return self._cache[key]

    def _answer(self, question: str, as_of: Optional[str]):
        if not self.store.snapshots:
            return self.c.Answer(text="I don't know; no website snapshots have been loaded yet.", confident=False)
        q = parse_rules(question, drop_tokens=frozenset(tokenize(self.composer.org)))
        if self.llm is not None and needs_llm(q):
            q = merge_llm(q, self.llm.parse(question))
        as_of_date = parse_iso(as_of) or q.as_of_text
        sid, _ = self.store.select(as_of_date)
        draft = self.composer.compose(q, sid, self._reference_date(question, as_of_date, sid))
        return self._finalize(draft, sid, question)

    def _reference_date(self, question: str, as_of_date: Optional[date], sid: str) -> date:
        """'Today' for status questions: the as_of date, the snapshot date, or a year named in the question."""
        ref = max(as_of_date or date.min, self.store.taken_on(sid))
        year = re.search(r"\b(20\d\d)\b", question)
        if as_of_date is None and year and not re.search(r"model|vehicle|car", question, re.I):
            ref = max(ref, date(int(year.group(1)), 12, 31))
        return ref

    def _finalize(self, d: Draft, sid: str, question: str):
        """Draft -> harness Answer: plain text, digit-free refusals, sources with quotes."""
        text = plain_text(d.text)
        if not d.confident and numbers_in(text) - numbers_in(question):
            text = NUMBERLESS_REFUSAL.format(org=self.composer.org)
        sources = [self.c.Source(url=u, snapshot_id=sid, quote=(quote or None)) for u, quote in d.urls]
        if not sources:
            seen = set()
            for f in sorted(d.facts, key=lambda x: -x.authority):
                if f.url not in seen:
                    seen.add(f.url)
                    sources.append(self.c.Source(url=f.url, snapshot_id=sid, quote=f.quote[:200] or None))
                if len(sources) >= 3:
                    break
        return self.c.Answer(text=text, sources=sources, confident=bool(d.confident), conflict_note=d.conflict_note)

    # ------------------------------------------------------------------ conflicts
    def conflicts(self):
        if not self.store.snapshots:
            return []
        if self._conflicts is None:
            self._conflicts = [
                self.c.Conflict(
                    topic=e["topic"], values=e["values"],
                    sources=[self.c.Source(url=s["url"], snapshot_id=s["snapshot_id"], quote=s["quote"] or None)
                             for s in e["sources"]],
                    resolution=e["resolution"], reason=e["reason"],
                ) for e in find_conflicts(self.store)
            ]
        return self._conflicts


def institution_name(pages: List) -> Optional[str]:
    """The institution's name, from the most common '| Name' suffix in page titles."""
    counts: Counter = Counter()
    for p in pages:
        m = re.search(r"\|\s*([A-Z][\w&' .-]{1,40})\s*$", p.title or "")
        if m:
            counts[m.group(1).strip()] += 1
    if not counts:
        return None
    name, n = counts.most_common(1)[0]
    return name if n >= 10 else None
