"""Question -> structured Query. Rules first; an optional LLM fills what the rules could not decide."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import FrozenSet, List, Optional

from .text import MONTHS, tokenize

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20, "thirty": 30,
                "forty": 40, "sixty": 60}

FAMILY_PATTERNS = [
    ("ira", r"\biras?\b|\broth\b|\btraditional ira\b|retirement account"),
    ("certificate", r"\bcds?\b|certificate|term[- ]share|share cert|\bjumbo\b"),
    ("money_market", r"money market|investor'?s choice"),
    ("hsa", r"health savings|\bhsa\b"),
    ("checking", r"checking|1st rate|first rate"),
    ("heloc", r"\bheloc\b|home equity line|line of credit"),
    ("home_equity_loan", r"home equity loan|home equity"),
    ("home_improvement", r"home improvement"),
    ("mortgage", r"mortgage|home loan|house loan|\barm\b|adjustable[- ]rate|fixed[- ]rate|conventional|refinanc|\b(?:15|20|30)[- ]year"),
    ("construction", r"construction loan|construction"),
    ("student_loan", r"student loan|student|college loan|university"),
    ("personal_loan", r"personal loan|signature loan|unsecured loan"),
    ("credit_card", r"credit card|\bvisa\b|platinum|rewards card"),
    ("credit_card?", r"\bcards?\b"),
    ("boat_rv", r"\bboat\b|\brv\b|camper|recreational"),
    ("atv", r"\batv\b|snowmobile|jet ski|\butv\b"),
    ("auto", r"\bauto\b|\bcar\b|\bvehicle\b|\btruck\b|motorcycle|model[- ]year"),
    ("savings", r"savings|share account|bright|you[- ]name[- ]it|holiday club|launchpad|high[- ]yield"),
]

PRODUCT_PATTERNS = [
    (r"share savings", "Share Savings"), (r"bright savings|\bbright\b", "Bright Savings"),
    (r"you[- ]name[- ]it", "You Name It Savings"), (r"holiday club", "Holiday Club Savings"),
    (r"launchpad", "Launchpad Savings"), (r"high[- ]yield", "High-Yield Savings"),
    (r"investor'?s choice|money market", "Investor's Choice Money Market"),
    (r"1st rate|first rate", "1st Rate Checking"), (r"free checking", "Free Checking"),
    (r"health savings|\bhsa\b", "Health Savings Account"),
    (r"business platinum", "Business Platinum Visa"), (r"business rewards", "Business Rewards Visa"),
    (r"platinum", "Platinum Visa"), (r"rewards visa|rewards card|\brewards\b", "Rewards Visa"),
]

ENTITY_PATTERNS = [
    ("routing", r"routing (?:number|#|no)|\baba\b"),
    ("phone", r"\b(phone|telephone|call you|contact number|customer service number|member service number)\b"),
    ("branch_count", r"how many (?:\w+ ){0,2}(?:branch|location|office)|number of (?:branch|location)"),
    ("employee_count", r"how many (?:\w+ ){0,2}(?:employees|staff|people)(?:\s+(?:does|do|work|are|at|in)\b|\s*\?|\s*$)|number of employees|how many people work"),
    ("member_count", r"how many members|number of members|membership (?:size|count)"),
    ("assets", r"total assets|assets (?:under|of)|how (?:big|large) is"),
    ("forbes", r"\bforbes\b"),
    ("eligibility", r"\beligib\w*|\bwho can (?:join|become|open)|\bqualif\w* (?:for|to) (?:join|member)|\bhow (?:do|can) i (?:join|become a member)|\brequirements? (?:to|for) (?:join|member)|\bmembership requirements?"),
    ("account_howto", r"\b(update|change|edit|correct)\b.{0,30}\b(contact information|contact info|address|phone number|email address|e-mail|name|beneficiar)"),
    ("hours_driveup", r"drive[- ]?(?:up|thru|through)"),
    ("closure", r"still open|\bclos(?:e|es|ed|ing|ure)\b|shut(?:ting)? down"),
    ("hours_lobby", r"\blobby\b|\bhours\b|open (?:on|at|until)|what time|when (?:do|does|are) .* (?:open|close)"),
    ("address", r"\baddress\b|where is (?:the|your)|located"),
]

LINK_RE = re.compile(r"\b(link|url|web ?page|web ?site|what page|which page|where (?:can|do|should) i (?:go|find|see|view|look)|point me|navigate)\b", re.I)
ACTION_RE = re.compile(r"\b(join|become a member|sign up|enroll|apply|open an? account)\b.*\bonline\b|\bonline\b.*\b(join|sign up|apply|open)\b", re.I)
CHANGE_RE = re.compile(r"\b(chang(?:e|ed|es|ing)|before|previous(?:ly)?|used to|went (?:up|down)|increas|decreas|\brose\b|\brisen\b|\bfell\b|\bdrop|history|over time|compared|differ(?:ent|ence) (?:from|than|between)|since (?:may|june|july|august|april|march|last))\b", re.I)
AGGREGATE_RE = re.compile(r"\b(all|every|each)\s+(?:\w+\s+)?branch|same (?:lobby |drive[- ]up )?hours|hours (?:vary|differ)|(?:vary|differ) by branch", re.I)
LIST_RE = re.compile(r"\b(what|which)\b.*\b(do you (?:offer|have)|are (?:there|available|offered)|options|types|kinds)\b|\b(all|list|every)\b.*\b(rate|certificate|card|term|account|loan)s?\b|\brates? for (?:the|your|all) (?:certificate|cd|credit card|card|checking|savings)s?\b|\b(?:certificate|cd|credit card|card|checking|savings) (?:account )?rates?\b", re.I)
DESCRIBE_RE = re.compile(r"^\s*(tell me about|what is|what's|whats|describe|explain|what are the (?:benefits|features)|how does .* work)\b", re.I)
SUPERLATIVE_RE = re.compile(r"\b(highest|best|top|maximum|max|most|lowest|minimum|cheapest)\b", re.I)
VERIFY_RE = re.compile(r"^\s*(do|does|is|are|can|did|will|has|have)\b", re.I)
REPEAT_RE = re.compile(r"\b(repeat|again|one more time|once more)\b", re.I)
FEE_RE = re.compile(r"\b(fees?|charges?|cost|costs|surcharge|penalt(?:y|ies))\b|how much (?:is|are|does|do you charge|for|to|will)", re.I)
AS_OF_RE = re.compile(r"\b(?:as of|back in|in|during|on)\s+(?:(\d{1,2})\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{1,2}))?,?\s+(20\d\d)\b", re.I)
PCT_IN_Q_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
MONEY_IN_Q_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(k)?\b", re.I)


DEPOSIT_FAMILIES = {"certificate", "ira", "savings", "money_market", "hsa", "checking"}
PRODUCT_FAMILY = {"Investor's Choice Money Market": "money_market", "Health Savings Account": "hsa",
                  "1st Rate Checking": "checking", "Free Checking": "checking", "Share Savings": "savings",
                  "Bright Savings": "savings", "You Name It Savings": "savings", "Holiday Club Savings": "savings",
                  "Launchpad Savings": "savings", "High-Yield Savings": "savings", "Platinum Visa": "credit_card",
                  "Rewards Visa": "credit_card", "Business Platinum Visa": "credit_card", "Business Rewards Visa": "credit_card"}


@dataclass
class Query:
    raw: str
    intent: str = "fact"           # fact | list | link | change | status | aggregate | verify | superlative | fee | describe | free
    family: Optional[str] = None
    product: Optional[str] = None
    metric: Optional[str] = None   # apy | dividend_rate | apr | rate | min_open | min_earn
    term_months: Optional[int] = None
    model_year: Optional[int] = None
    balance: Optional[float] = None
    amount: Optional[float] = None
    jumbo: Optional[bool] = None
    special: Optional[bool] = None
    ira_type: Optional[str] = None
    purpose: Optional[str] = None
    intro: Optional[bool] = None
    business: Optional[bool] = None
    newest_model: bool = False     # "brand new car": the newest model-year tier
    entity: Optional[str] = None
    branch: Optional[str] = None
    pct_value: Optional[float] = None
    as_of_text: Optional[date] = None
    superlative: Optional[str] = None   # max | min
    tokens: List[str] = field(default_factory=list)
    family_weak: bool = False      # family came from a generic word such as "card"
    from_llm: bool = False         # routing came from the LLM parser; a failed lookup falls back to free text


def _detect(patterns, text: str) -> Optional[str]:
    for name, pat in patterns:
        if re.search(pat, text, re.I):
            return name
    return None


def _parse_term(text: str) -> Optional[int]:
    t = text.lower()
    for w, n in NUMBER_WORDS.items():
        t = re.sub(rf"\b{w}[- ]", f"{n}-", t)
    m = re.search(r"(\d+)\s*[- ]?\s*(?:month|months|mo|mos)\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[- ]?\s*(?:year|years|yr|yrs)\b(?!\s*(?:old|model))", t)
    if m:
        return int(m.group(1)) * 12
    m = re.search(r"\b(\d+)/1\b", t)      # 7/1 ARM
    if m:
        return None
    return None


def _parse_model_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d\d)\b(?![-–]\d)", text)
    if m and re.search(r"model|vehicle|car|truck|auto|motorcycle|year", text, re.I):
        return int(m.group(1))
    return None


def _parse_money(text: str) -> Optional[float]:
    vals = []
    for m in MONEY_IN_Q_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if m.group(2):
            v *= 1000
        vals.append(v)
    if not vals:
        t = text.lower()
        for w, n in NUMBER_WORDS.items():
            t = re.sub(rf"\b{w}\b", str(n), t)
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(grand|thousand|k)\b", t)
        if m:
            vals.append(float(m.group(1)) * 1000)
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(million|mm)\b", t)
        if m:
            vals.append(float(m.group(1)) * 1_000_000)
    if not vals:
        m = re.search(r"\b(\d{1,3}(?:,\d{3})+)\b", text)
        if m:
            vals.append(float(m.group(1).replace(",", "")))
    return vals[0] if vals else None


def _parse_as_of(text: str) -> Optional[date]:
    m = AS_OF_RE.search(text)
    if not m:
        return None
    month = MONTHS[m.group(2).lower()]
    year = int(m.group(4))
    day = int(m.group(3) or m.group(1) or 0)
    if day:
        try:
            return date(year, month, day)
        except ValueError:
            pass
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


NOT_A_BRANCH = {"the", "a", "which", "what", "any", "each", "every", "all", "your", "nearest", "closest", "our", "my"}


def _branch(text: str, drop_tokens: FrozenSet[str] = frozenset()) -> Optional[str]:
    """'the Riverside Example CU branch' -> 'Riverside' (the institution's own name is dropped)."""
    m = re.search(r"\b(?:the\s+)?([A-Z][\w'.-]+(?:\s+(?:[A-Z][\w'.-]+|Avenue|Street|Ave\.?|St\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Blvd\.?))*)\s+[Bb]ranch(?:es)?\b", text)
    if m:
        words = [w for w in m.group(1).split() if w.lower() not in drop_tokens and w.lower() not in ("branch", "cu")]
        if words and words[0].lower() not in NOT_A_BRANCH:
            return " ".join(words)
    m = re.search(r"\b[Bb]ranch\s+(?:in|at|on)\s+([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)?)", text)
    if m:
        return m.group(1)
    return None


def parse_rules(question: str, drop_tokens: FrozenSet[str] = frozenset()) -> Query:
    """Deterministic question parser. `drop_tokens` holds the institution's own name, which carries no meaning."""
    q = Query(raw=question)
    text = question.strip()
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    q.tokens = [t for t in tokenize(REPEAT_RE.sub(" ", text)) if t not in drop_tokens]
    q.as_of_text = _parse_as_of(text)
    _detect_entity(q, text, low, drop_tokens)
    _detect_family_and_product(q, low)
    _detect_metric(q, low)
    _detect_qualifiers(q, text, low)
    _detect_fee(q, low)
    q.intent = _detect_intent(q, text, low)
    return q


def _detect_entity(q: Query, text: str, low: str, drop_tokens: FrozenSet[str] = frozenset()) -> None:
    q.entity = _detect(ENTITY_PATTERNS, low)
    if q.entity == "closure" and not re.search(r"\b(branch|location|office|lobby|store|atm)\b", low):
        q.entity = None                      # closing an account, not a branch
    if q.entity == "closure" and re.search(r"what time|\bhours\b|o'clock|tonight|each day|daily", low) and \
            not re.search(r"still open|shut|closure|permanently|for good", low):
        q.entity = "hours_lobby"
    if q.entity == "hours_lobby" and re.search(r"\bopen\b", low) and re.search(r"still|today|now", low):
        q.entity = "closure"
    if q.entity == "eligibility" and ACTION_RE.search(text):
        q.entity = None
    q.branch = _branch(text, drop_tokens)
    if q.entity == "address" and not q.branch and not re.search(r"\bbranch|office|location", low):
        q.entity = None


def _detect_family_and_product(q: Query, low: str) -> None:
    fam = _detect(FAMILY_PATTERNS, low)
    if fam and fam.endswith("?"):            # matched only a generic word such as "card"
        fam, q.family_weak = fam[:-1], True
    q.family = fam
    if q.entity and q.entity != "forbes" and q.family in ("credit_card", "savings", "checking") and \
            re.search(r"hours|address|routing|branch", low):
        q.family = None                      # "savings" in "branch hours for the savings center" is noise
    for pat, name in PRODUCT_PATTERNS:
        if re.search(pat, low):
            q.product = name
            break
    if q.product:
        q.family = PRODUCT_FAMILY.get(q.product, q.family)


MIN_OPEN_RE = re.compile(r"minimum (?:\w+ ){0,2}to open|minimum (?:opening )?(?:deposit|amount)|opening (?:deposit|balance)|"
                         r"how much (?:do i need|does it take|is (?:needed|required)|money) to open|(?:need|required) to open")
MIN_EARN_RE = re.compile(r"minimum (?:\w+ ){0,2}to earn|minimum balance|balance (?:required|needed|do i need) to earn")
TOP_RATE_RE = re.compile(r"\b(top|highest|best|maximum|lowest) (?:\w+ ){0,2}(rate|apy|apr|tier|yield)")


def _detect_metric(q: Query, low: str) -> None:
    if MIN_OPEN_RE.search(low) and not TOP_RATE_RE.search(low):
        q.metric = "min_open"
        return
    if MIN_EARN_RE.search(low) and not TOP_RATE_RE.search(low):
        q.metric = "min_earn"
        return
    if re.search(r"\bapy\b|yield", low):
        q.metric = "apy"
    elif re.search(r"dividend rate", low):
        q.metric = "dividend_rate"
    elif re.search(r"\bapr\b", low):
        q.metric = "apr"
    elif re.search(r"\brates?\b|interest|percent|pay|earn|how much", low):
        q.metric = "rate"
    if q.metric == "rate" and q.family:      # "rate" means APY for deposits and APR for loans
        q.metric = "apy" if q.family in DEPOSIT_FAMILIES else ("rate" if q.family == "mortgage" else "apr")


def _detect_qualifiers(q: Query, text: str, low: str) -> None:
    q.term_months = _parse_term(text)
    q.model_year = _parse_model_year(text) if q.family in ("auto", "atv", "boat_rv", None) else None
    if q.family in ("auto", "atv") and q.model_year is None and re.search(r"\b(brand[- ]new|new|newest|latest|current[- ]year)\b", low):
        q.newest_model = True
    money = _parse_money(text)
    if money is not None:
        if q.family in DEPOSIT_FAMILIES:
            q.balance = money
        elif q.family in ("mortgage", "home_improvement", "boat_rv", "auto", "personal_loan"):
            q.amount = money
    certificate_like = q.family in ("certificate", "ira")
    if re.search(r"\bjumbo\b", low):
        q.jumbo = True
    elif certificate_like and re.search(r"\b(regular|standard|non[- ]jumbo)\b", low):
        q.jumbo = False
    if re.search(r"\bspecial\b", low):
        q.special = True
    elif certificate_like and re.search(r"\bregular\b", low):
        q.special = False
    if re.search(r"\broth\b", low):
        q.ira_type = "roth"
    elif re.search(r"\btraditional\b", low):
        q.ira_type = "traditional"
    if re.search(r"refinanc", low):
        q.purpose = "refinance"
    elif q.family == "mortgage" and re.search(r"\bpurchase\b|\bbuy\b|buying", low):
        q.purpose = "purchase"
    if re.search(r"intro(?:ductory)?|balance transfer", low):
        q.intro = True
    elif q.family == "credit_card" and re.search(r"standard|purchase apr|regular apr|ongoing", low):
        q.intro = False
    if re.search(r"\bbusiness\b|commercial", low):
        q.business = True
    elif q.family and re.search(r"\bpersonal\b", low):
        q.business = False
    m = PCT_IN_Q_RE.search(text)
    if m:
        q.pct_value = float(m.group(1))
    # "minimum balance to earn the top rate" asks for the top rate, not the minimum one
    sup_text = re.sub(r"\b(minimum|lowest|smallest|least)\s+(balance|deposit|amount|opening|to open|to earn|required)", " ", low)
    sups = [m.group(1) for m in SUPERLATIVE_RE.finditer(sup_text)]
    if sups:
        q.superlative = "min" if all(w in ("lowest", "minimum", "cheapest", "least") for w in sups) else "max"


def _detect_fee(q: Query, low: str) -> None:
    """A fee question keeps the product family it names (for the free-text fallback) but is answered as a fee."""
    if not FEE_RE.search(low) or re.search(r"\b(apy|apr|dividend|interest rate|yield)\b", low) or q.metric in ("min_open", "min_earn"):
        return
    if q.family is None or q.family_weak or q.family == "credit_card" and re.search(r"debit|replace|lost|rush", low):
        q.family, q.family_weak = "fee", False
    q.metric = "fee"


def _is_list_question(q: Query, text: str, low: str) -> bool:
    if not q.family or q.term_months or q.product:
        return False
    if LIST_RE.search(text) and q.balance is None and q.model_year is None:
        return True
    # "certificate rates" / "credit card rates" with no term or card named: read them all back
    return q.family in ("certificate", "credit_card") and q.jumbo is None and q.special is None and q.ira_type is None \
        and bool(re.search(r"\brates?\b|\bapr|\bapy|offer|options|available", low)) \
        and not re.search(r"\b(highest|lowest)\b", low)


def _detect_intent(q: Query, text: str, low: str) -> str:
    if q.metric == "fee" and not q.entity:
        return "fee"
    if LINK_RE.search(text) or ACTION_RE.search(text):
        return "link"
    if q.entity == "closure" or (q.entity == "hours_lobby" and q.branch and re.search(r"still open|open today", low)):
        return "status"
    if q.entity in ("hours_lobby", "hours_driveup") and AGGREGATE_RE.search(text):
        return "aggregate"
    if q.entity:
        return "fact"
    if CHANGE_RE.search(text) and q.family and not q.as_of_text:
        return "change"
    if q.pct_value is not None and q.family and VERIFY_RE.match(text):
        return "verify"
    if q.superlative and q.family:
        return "superlative"
    if _is_list_question(q, text, low):
        return "list"
    if q.family and q.metric:
        return "fact"
    if q.family and DESCRIBE_RE.search(text) and not (q.term_months or q.model_year or q.balance is not None):
        return "describe"                    # "tell me about Launchpad Savings" wants the description
    if q.family and (q.term_months or q.product or q.model_year or q.balance is not None):
        return "fact"
    return "free"


def needs_llm(q: Query) -> bool:
    """Only questions the rules could not place are worth an LLM call."""
    return (q.family is None or q.family_weak) and q.entity is None and q.intent in ("free", "fact", "describe")


def merge_llm(rules: Query, llm: Optional[dict]) -> Query:
    """Strict gap filling: the LLM may name a family, product or entity the rules missed. It never overrides a
    rule decision and never switches to the time-sensitive intents (change, status, verify, aggregate)."""
    if not llm or not needs_llm(rules):
        return rules
    q = rules
    fam = llm.get("family")
    if fam and fam in FAMILIES and (q.family is None or q.family_weak):
        q.family, q.family_weak, q.from_llm = fam, False, True
    for key in ("product", "metric", "ira_type", "purpose"):
        if getattr(q, key) is None and llm.get(key):
            setattr(q, key, llm[key])
    if q.entity is None and llm.get("entity") in SAFE_LLM_ENTITIES:
        q.entity, q.from_llm = llm["entity"], True
        if q.branch is None and llm.get("branch"):
            q.branch = llm["branch"]
    for key in ("term_months", "model_year", "balance", "amount"):
        if getattr(q, key) is None and isinstance(llm.get(key), (int, float)) and not isinstance(llm.get(key), bool):
            setattr(q, key, llm[key])
    for key in ("jumbo", "special", "intro", "business"):
        if getattr(q, key) is None and isinstance(llm.get(key), bool):
            setattr(q, key, llm[key])
    intent = llm.get("intent")
    if q.intent == "free" and intent in ("fact", "list", "link", "superlative", "fee"):
        if intent == "fee":
            q.family, q.metric, q.intent = "fee", "fee", "fee"
        elif q.family or intent == "link":
            q.intent = intent
    if q.intent == "fact" and not q.family and not q.entity:
        q.intent = "free"
    return q


FAMILIES = {"certificate", "ira", "savings", "money_market", "hsa", "checking", "auto", "mortgage", "heloc",
            "home_equity_loan", "home_improvement", "personal_loan", "credit_card", "boat_rv", "atv", "student_loan",
            "construction", "fee"}
SAFE_LLM_ENTITIES = {"routing", "phone", "branch_count", "member_count", "assets", "forbes", "hours_lobby",
                     "hours_driveup", "closure"}
