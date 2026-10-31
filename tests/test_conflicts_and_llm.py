"""Conflict detection and the strict LLM merge (no API calls: the merge is pure)."""
from datetime import date

from ks.conflicts import find_conflicts
from ks.model import Fact
from ks.query import merge_llm, needs_llm, parse_rules
from ks.store import FactStore


def mortgage(sid, url, amount_hi, rate, authority, purpose="purchase"):
    return Fact(family="mortgage", product=f"Purchase: 30-Year Fixed Conventional ${amount_hi:,} or less", metric="rate",
                value=rate, url=url, snapshot_id=sid, authority=authority, term_months=360, amount=(0.0, float(amount_hi)),
                purpose=purpose, quote="row")


def entity(sid, url, value, when):
    return Fact(family="entity", product="branch count", metric="count", value=value, url=url, snapshot_id=sid,
                authority=60, article_date=when, label="number of branches")


def test_within_snapshot_tiers_merge_and_cross_snapshot_change_is_reported():
    s = FactStore()
    s.add_snapshot("01", date(2026, 5, 12))
    s.add_snapshot("02", date(2026, 9, 28))
    for sid in ("01", "02"):
        for u in ("https://x.test/rates", "https://x.test/promo"):
            s.add_page(sid, u)
    for hi, old, new in ((100000, "5.750%", "7.13%"), (300000, "6.000%", "7.25%")):
        s.add(mortgage("01", "https://x.test/rates", hi, old, 100))
        s.add(mortgage("02", "https://x.test/rates", hi, new, 100))
        s.add(mortgage("02", "https://x.test/promo", hi, old, 40))         # stale copy still live
    s.add(Fact(family="certificate", product="12 Month Certificate", metric="apy", value="2.90%", url="https://x.test/rates",
               snapshot_id="01", authority=100, term_months=12, quote="r"))
    s.add(Fact(family="certificate", product="12 Month Certificate", metric="apy", value="3.40%", url="https://x.test/rates",
               snapshot_id="02", authority=100, term_months=12, quote="r"))
    s.add(entity("02", "https://x.test/news/old", "24", date(2024, 1, 1)))
    s.add(entity("02", "https://x.test/news/new", "22", date(2026, 5, 1)))

    out = find_conflicts(s)
    topics = {e["topic"]: e for e in out}
    merged = [t for t in topics if "30-Year" in t]
    assert len(merged) == 1 and "(all tiers)" in merged[0]                 # two tiers, one entry
    e = topics[merged[0]]
    assert set(e["values"]) == {"7.13%", "7.25%", "5.750%", "6.000%"}
    assert "7.25%" in e["resolution"] and "7.13%" in e["resolution"]      # every current tier value
    cert = topics["12-month certificate APY"]
    assert cert["values"] == ["3.40%", "2.90%"] and cert["resolution"] == "3.40%"
    branches = topics["number of branches"]
    assert branches["resolution"] == "22" and set(branches["values"]) == {"22", "24"}


def test_needs_llm_only_when_rules_find_nothing():
    assert not needs_llm(parse_rules("What's the APR for a 60-month auto loan?"))
    assert not needs_llm(parse_rules("What is your routing number?"))
    assert needs_llm(parse_rules("Rate on a used pickup from 2019, 5 year loan?"))


def test_merge_llm_fills_gaps_but_never_overrides_rules():
    q = parse_rules("Rate on a used pickup from 2019, 5 year loan?")
    q = merge_llm(q, {"intent": "fact", "family": "auto", "metric": "apr", "model_year": 2019, "term_months": 60})
    assert (q.family, q.model_year, q.term_months, q.from_llm) == ("auto", 2019, 60, True)

    q = parse_rules("What was the 10-month jumbo special APY as of May 2026?")
    before = (q.intent, q.family, q.term_months)
    q = merge_llm(q, {"intent": "change", "family": "savings", "term_months": 12})
    assert (q.intent, q.family, q.term_months) == before                   # rules recognised it: LLM ignored

    q = parse_rules("Where can members of the shuttered Riverside location go?")
    assert needs_llm(q)
    q = merge_llm(q, {"intent": "status", "entity": "address", "branch": "Riverside"})
    assert q.intent != "status" and q.entity is None                       # unsafe intent/entity not accepted
