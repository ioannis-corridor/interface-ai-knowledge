"""The LLM wrapper without network: response parsing, type cleaning, failure handling, caching."""
from ks.llm import LLMParser, _clean


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def create(self, **_kw):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Resp(reply)


def _parser(*replies):
    p = LLMParser.__new__(LLMParser)
    p.model, p._cache = "stub", {}
    p._client = type("C", (), {"messages": _Messages(replies)})()
    return p


def test_clean_normalises_types():
    out = _clean({"intent": "fact", "family": "auto", "product": "null", "term_months": 60.0, "balance": "lots",
                  "jumbo": "yes", "special": True, "model_year": True})
    assert out["intent"] == "fact" and out["product"] is None
    assert out["term_months"] == 60 and out["balance"] is None
    assert out["jumbo"] is None and out["special"] is True and out["model_year"] is None


def test_parse_reads_fenced_json_and_caches():
    p = _parser('```json\n{"intent": "fact", "family": "auto", "model_year": 2019, "term_months": 60}\n```')
    first = p.parse("Rate on a used pickup from 2019, 5 year loan?")
    assert first["family"] == "auto" and first["model_year"] == 2019
    assert p.parse("rate on a used pickup from 2019,  5 year loan?") is first      # normalised key, no second call
    assert p._client.messages.calls == 1


def test_parse_failure_returns_none():
    p = _parser(RuntimeError("boom"), "not json at all")
    assert p.parse("one") is None
    assert p.parse("two") is None
