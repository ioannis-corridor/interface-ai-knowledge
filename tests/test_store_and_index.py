"""FactStore selection and carry-forward; ChunkIndex search scoped to a snapshot."""
from datetime import date

from ks.index import ChunkIndex, split_chunks
from ks.model import Fact
from ks.store import FactStore, best_of
from ks.text import tokenize


def fact(sid, url, value, **kw):
    base = dict(family="certificate", product="6 Month Certificate", metric="apy", value=value, url=url,
                snapshot_id=sid, authority=100, term_months=6)
    base.update(kw)
    return Fact(**base)


def make_store():
    s = FactStore()
    s.add_snapshot("01", date(2026, 1, 5))
    s.add_snapshot("02", date(2026, 3, 1))
    for sid in ("01", "02"):
        s.add_page(sid, "https://x.test/rates")
    s.add_page("01", "https://x.test/fees")                  # vanishes in snapshot 02
    s.add(fact("01", "https://x.test/rates", "2.95%"))
    s.add(fact("02", "https://x.test/rates", "3.50%"))
    s.add(fact("01", "https://x.test/fees", "$2.50", family="fee", product="Lost card", metric="fee", term_months=None))
    return s


def test_select_snapshot_for_as_of():
    s = make_store()
    assert s.select(None) == ("02", True)
    assert s.select(date(2026, 1, 31)) == ("01", True)
    assert s.select(date(2026, 3, 1)) == ("02", True)
    assert s.select(date(2025, 12, 1)) == ("01", False)      # before every crawl: earliest, flagged inexact


def test_carry_forward_only_for_missing_urls():
    s = make_store()
    certs = s.find("02", "certificate")
    assert [f.value for f in certs] == ["3.50%"]              # the rates page exists in 02: no stale copy carried
    fees = s.find("02", "fee")
    assert len(fees) == 1 and fees[0].value == "$2.50" and fees[0].authority == 90   # carried, 10 points lower
    assert fees[0].extra["carried_from"] == "01"
    assert s.url_source("02") == {"https://x.test/rates": "02", "https://x.test/fees": "01"}


def test_best_of_prefers_authority_then_effective_date():
    a = fact("02", "https://x.test/promo", "2.95%", authority=40, effective=date(2026, 3, 1))
    b = fact("02", "https://x.test/rates", "3.50%", authority=100, effective=date(2026, 1, 1))
    c = fact("02", "https://x.test/rates2", "3.60%", authority=100, effective=date(2026, 2, 1))
    assert best_of([a, b, c]) is c
    assert best_of([a, b]) is b


def test_history_lists_each_snapshot():
    s = make_store()
    hist = s.history(lambda f: f.family == "certificate")
    assert [(sid, [f.value for f in fs]) for sid, _, fs in hist] == [("01", ["2.95%"]), ("02", ["3.50%"])]


def test_split_chunks_keeps_tables_whole():
    md = "# Rates\n\nIntro paragraph about savings.\n\nShare Savings\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nMore text.\n"
    chunks = split_chunks(md)
    tables = [c for c in chunks if c[2]]
    assert len(tables) == 1 and tables[0][1].startswith("Share Savings: ")
    assert any("Intro paragraph" in c[1] for c in chunks if not c[2])


def test_index_search_is_scoped_to_snapshot_and_carries_forward():
    idx = ChunkIndex()
    idx.add_page("Our debit cards work with Apple Pay and Google Pay.", "https://x.test/mobile", "01", 85)
    idx.add_page("Certificates pay 3.50% APY.", "https://x.test/rates", "01", 100)
    idx.add_page("Certificates pay 3.50% APY.", "https://x.test/rates", "02", 100)
    q = tokenize("mobile wallet apple pay")
    assert idx.search(q, "02") == []                                       # page absent from 02 ...
    carried = idx.search(q, "02", url_source={"https://x.test/mobile": "01", "https://x.test/rates": "02"})
    assert carried and carried[0][2] == "https://x.test/mobile"             # ... unless carried forward
    assert idx.search(q, "01")[0][2] == "https://x.test/mobile"
