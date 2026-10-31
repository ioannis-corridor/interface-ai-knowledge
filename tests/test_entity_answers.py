"""Entity answers (hours, addresses, closures, counts, awards, eligibility, how-to) on a synthetic site."""
import contract

from ks.system import KnowledgeSystem
from ks.text import numbers_in

CONTACT = """# Contact | Example CU
We’re so glad you’re here! For general questions, use our form. Have a specific account question? Use the "Contact Us"
tab inside Shine Online or Mobile Banking. Or if you have an urgent need, please call 800-555-0100.

**Phone:** 800-555-0100

**Routing Number:** 123456789

### Example CU

Example CU Branch

11375 Example Ln., Riverton, IL, 60001

Closed

Example CU Branch

1465 Maple St., Lakeview, IA, 50001
"""
RELEASE_A = """
2 min read

[Jane Doe](https://x.test/newsroom/author/jane) June 20, 2025

# Example CU plans Riverside branch closure

This location will close March 31, 2026. “Members who frequent the Riverside branch already can access the same
services at full-service branches at Elm Street and Maple Avenue,” said the CEO.

ABOUT EXAMPLE CU: It has nearly 700 employees and 23 branch office locations. It was the fourth time Forbes recognized Example CU.
"""
RELEASE_B = """
2 min read

[Jane Doe](https://x.test/newsroom/author/jane) May 05, 2026

# Example CU celebrates a new Hilltop branch

The Hilltop Example CU branch is located at 1100 E. Business Highway 151. Branch hours are:

**Lobby**

Monday-Thursday: 8:30 a.m.-5 p.m.

Friday: 8:30 a.m.-5:30 p.m.

Saturday: 9 a.m.-noon

**Drive-up**

Monday-Friday: 8 a.m.-6 p.m.

ABOUT EXAMPLE CU: It has over 600 employees and 22 branch office locations. This was the fifth time Forbes recognized Example CU.
"""
RELEASE_C = """
2 min read

[Jane Doe](https://x.test/newsroom/author/jane) April 06, 2026

# Example CU finishes the Oakdale branch

The Oakdale Example CU branch is located at 200 Main St. Branch hours are:

**Lobby**

Monday-Friday: 8:30 a.m.-5:30 p.m.

Saturday: 8:30 a.m.-12:30 p.m.
"""
JOIN = """# Join | Example CU
##### WHO CAN JOIN

## You're Eligible to Join If Any of These Sound Like You

- You live or work within our charter area.
- You have an immediate family member who’s a member.

Local Service: You can find us in Iowa, Illinois and Wisconsin.
"""


def build():
    ks = KnowledgeSystem(contract, use_llm=False)
    pages = [("https://x.test/contact", "Contact | Example CU", CONTACT),
             ("https://x.test/newsroom/riverside-closure", "Riverside closure | Example CU", RELEASE_A),
             ("https://x.test/newsroom/hilltop", "Hilltop | Example CU", RELEASE_B),
             ("https://x.test/newsroom/oakdale", "Oakdale | Example CU", RELEASE_C),
             ("https://x.test/about/join", "Join | Example CU", JOIN)]
    ks.ingest(contract.Snapshot("01_2026-09-28", "2026-09-28",
                                [contract.Page(url=u, title=t, markdown=m, fetched_at="2026-09-28T00:00:00Z") for u, t, m in pages]))
    return ks


def test_newest_release_wins_for_counts_and_awards():
    ks = build()
    branches = ks.answer("How many branches does Example CU have?")
    assert "22" in branches.text and "23" not in branches.text and "23" in (branches.conflict_note or "")
    forbes = ks.answer("What recognition has Example CU received from Forbes?")
    assert "fifth" in forbes.text and "fourth" not in forbes.text


def test_hours_specific_general_and_unknown_branch():
    ks = build()
    specific = ks.answer("What are the lobby hours at the Hilltop branch?")
    assert "9 a.m.-noon" in specific.text and "12:30" not in specific.text
    general = ks.answer("What are your lobby hours?")
    assert "8:30" in general.text and "noon" in general.text and "12:30" in general.text
    assert any(s.url.endswith("/contact") for s in general.sources)
    drive = ks.answer("What are the drive-up hours?")
    assert "8 a.m.-6 p.m." in drive.text
    unknown = ks.answer("Can you give me the lobby hours for the Birch Avenue branch?")
    assert not unknown.confident and not numbers_in(unknown.text)


def test_address_prefers_the_locator_page():
    ks = build()
    a = ks.answer("What is the address of the Riverton branch?")
    assert "11375 Example" in a.text and "60001" in a.text
    b = ks.answer("Where is the Hilltop branch located?")
    assert "1100 E. Business Highway 151" in b.text


def test_closure_status_with_alternatives():
    ks = build()
    a = ks.answer("Is the Riverside branch still open today?")
    assert a.text.startswith("No.") and "March 31, 2026" in a.text and "Elm Street and Maple Avenue" in a.text
    b = ks.answer("When does the Riverside branch close?")
    assert "March 31, 2026" in b.text
    c = ks.answer("Is the Riverton branch closing?")
    assert not c.confident


def test_eligibility_contact_update_and_phone():
    ks = build()
    e = ks.answer("Who is eligible to become a member?")
    assert "live or work" in e.text and "Iowa, Illinois and Wisconsin" in e.text
    h = ks.answer("How can I update my contact information?")
    assert "Shine" in h.text and "800-555-0100" in h.text
    p = ks.answer("What is your phone number?")
    assert "800-555-0100" in p.text
