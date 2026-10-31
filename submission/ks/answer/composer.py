"""Routes a parsed query to the handler that owns its intent."""
from __future__ import annotations

from datetime import date

from .draft import REFUSE_BRANCH, Draft
from .entity import EntityAnswers
from .facts import FactAnswers
from .fees import FeeAnswers
from .retrieval import TextAnswers

BRANCH_ENTITIES = {"hours_lobby", "hours_driveup", "address", "closure"}


class Composer(EntityAnswers, FactAnswers, FeeAnswers, TextAnswers):
    def compose(self, q, sid: str, ref_date: date) -> Draft:
        draft = self._dispatch(q, sid, ref_date)
        if q.from_llm and not draft.confident and q.intent != "fee":
            # The LLM's routing found nothing; the deterministic free-text path is the safer fallback.
            free = self.answer_free(q, sid)
            return free if free.confident else draft
        return draft

    def _dispatch(self, q, sid: str, ref_date: date) -> Draft:
        if q.entity and q.intent in ("fact", "status", "aggregate", "free"):
            draft = self.answer_entity(q, sid, ref_date)
            if draft:
                return draft
            if q.entity in BRANCH_ENTITIES and q.branch:
                return Draft.refuse(REFUSE_BRANCH, what="that information", branch=q.branch, org=self.org)
        if q.intent == "link":
            return self.answer_link(q, sid)
        if q.intent == "fee":
            return self.answer_fee(q, sid)
        if q.intent == "list" and q.family:
            return self.answer_list(q, sid)
        if q.intent == "verify" and q.family and q.pct_value is not None:
            return self.answer_verify(q, sid)
        if q.intent == "change" and q.family:
            return self.answer_change(q, sid)
        if q.intent in ("fact", "superlative") and q.family:
            if q.metric is None and not (q.term_months or q.product or q.model_year or q.balance is not None):
                return self.answer_free(q, sid)      # "do you have student loans?" is a description, not a rate
            return self.answer_fact(q, sid)
        return self.answer_free(q, sid)
