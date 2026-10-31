"""The internal answer shape and the refusal templates. Refusals never contain digits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..model import Fact

REFUSE_RATE = "The website doesn't list a rate for {thing}. Please contact {org} for current terms."
REFUSE_FEE = "The website's fee schedule doesn't list a fee for {thing}. Please contact {org} to confirm."
REFUSE_GENERIC = "I don't know; the website doesn't say. Please contact {org} for help with that."
REFUSE_BRANCH = ("The website doesn't list {what} for the {branch} branch. Please contact {org} or check the branch "
                 "locator on the contact page.")
NOT_YET = "That product isn't listed on the website as of that date. Please contact {org} for details."
GONE = "The website no longer lists {thing}; it appeared in an earlier crawl but not in the current one. Please contact {org} for details."


@dataclass
class Draft:
    text: str
    facts: List[Fact] = field(default_factory=list)          # facts the text was built from (become sources)
    urls: List[Tuple[str, str]] = field(default_factory=list)  # explicit (url, quote) sources, used first
    confident: bool = True
    conflict_note: Optional[str] = None

    @classmethod
    def refuse(cls, template: str, **kw) -> "Draft":
        return cls(template.format(**kw), confident=False)
