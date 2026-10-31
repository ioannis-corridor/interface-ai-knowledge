"""Section chunks + a small BM25 index. One index for all snapshots; each chunk knows where it appeared."""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .text import strip_markdown, tokenize

MAX_CHUNK = 900


@dataclass
class Chunk:
    text: str                                   # cleaned, markdown stripped
    tokens: List[str]
    heading: str = ""
    occurrences: Set[Tuple[str, str]] = field(default_factory=set)   # (snapshot_id, url)
    authority: Dict[str, int] = field(default_factory=dict)          # url -> authority class
    pos: Dict[str, int] = field(default_factory=dict)                # url -> position of the chunk in that page
    is_table: bool = False


def split_chunks(markdown: str) -> List[Tuple[str, str, bool]]:
    """-> [(heading, text, is_table)] : tables stay whole, prose is grouped under its heading."""
    out, heading, buf = [], "", []
    lines = markdown.splitlines()
    i = 0

    def flush():
        if buf:
            txt = strip_markdown(" ".join(buf))
            if len(txt) > 25:
                out.append((heading, txt, False))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            label = next((strip_markdown(l) for l in reversed(lines[max(0, i - 12):i])
                          if l.strip() and not l.strip().startswith(("|", "![", "[", "-")) and len(l) < 80), "")
            rows = [strip_markdown(r.strip().strip("|").replace("|", " ; ")) for r in lines[i:j] if not set(r.strip()) <= set("|-: ")]
            out.append((heading, (label + ": " if label else "") + " / ".join(rows), True))
            i = j
            continue
        hm = re.match(r"^#{1,6}\s+(.*)$", s)
        if hm:
            flush()
            heading = strip_markdown(hm.group(1))
        elif not s:
            if sum(len(b) for b in buf) > MAX_CHUNK:
                flush()
            elif buf:
                buf.append("")
        else:
            buf.append(s)
            if sum(len(b) for b in buf) > MAX_CHUNK * 2:
                flush()
        i += 1
    flush()
    return out


class ChunkIndex:
    def __init__(self):
        self.chunks: List[Chunk] = []
        self._by_hash: Dict[str, int] = {}
        self._postings: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._len: List[int] = []
        self._avg = 0.0
        self._dirty = True

    def add_page(self, markdown: str, url: str, snapshot_id: str, authority: int) -> None:
        for pos, (heading, text, is_table) in enumerate(split_chunks(markdown)):
            key = hashlib.md5((heading + "\n" + text).encode("utf-8")).hexdigest()
            idx = self._by_hash.get(key)
            if idx is None:
                toks = tokenize(heading + " " + text)
                if not toks:
                    continue
                idx = len(self.chunks)
                self.chunks.append(Chunk(text=text, tokens=toks, heading=heading, is_table=is_table))
                self._by_hash[key] = idx
                self._len.append(len(toks))
                for t in toks:
                    self._postings[t][idx] = self._postings[t].get(idx, 0) + 1
                self._dirty = True
            ch = self.chunks[idx]
            ch.occurrences.add((snapshot_id, url))
            ch.authority[url] = max(ch.authority.get(url, 0), authority)
            ch.pos.setdefault(url, pos)

    def _finalize(self):
        if self._dirty:
            self._avg = (sum(self._len) / len(self._len)) if self._len else 1.0
            self._dirty = False

    def search(self, query_tokens: List[str], snapshot_id: str, k: int = 12, k1: float = 1.4, b: float = 0.6,
               url_filter: Optional[callable] = None, url_source: Optional[Dict[str, str]] = None
               ) -> List[Tuple[float, Chunk, str]]:
        """-> [(score, chunk, best_url)] restricted to chunks current in `snapshot_id`.

        `url_source` (url -> snapshot id) lets pages missing from this snapshot be served from an earlier crawl."""
        self._finalize()
        n = len(self.chunks)
        scores: Dict[int, float] = defaultdict(float)
        for t in set(query_tokens):
            post = self._postings.get(t)
            if not post:
                continue
            idf = math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
            for idx, tf in post.items():
                dl = self._len[idx]
                scores[idx] += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self._avg))
        out = []
        for idx, sc in scores.items():
            ch = self.chunks[idx]
            if url_source:
                urls = [u for (sid, u) in ch.occurrences if url_source.get(u) == sid]
            else:
                urls = [u for (sid, u) in ch.occurrences if sid == snapshot_id]
            if url_filter:
                urls = [u for u in urls if url_filter(u)]
            if not urls:
                continue
            best = max(urls, key=lambda u: ch.authority.get(u, 0))
            auth = ch.authority.get(best, 0)
            out.append((sc * (0.6 + auth / 150.0), ch, best))
        out.sort(key=lambda x: -x[0])
        return out[:k]
