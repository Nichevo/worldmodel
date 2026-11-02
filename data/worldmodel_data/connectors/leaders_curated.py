"""Heads of government of the key countries (New Zealand, Australia, the United Kingdom and
the United States) since 1945, with their party, checked by hand.

Wikidata's leader lists are uneven: some countries list only the current leader, party
memberships often lack dates, and the full query can time out. For the key countries the
charts coloured by governing party use this list instead, for terms that began on or
before CURATED_UNTIL; terms Wikidata has that began after it are still added, so a new
leader shows up without a code change.

The US president is both head of state and head of government, so US rows count as both.
"""

from __future__ import annotations

from datetime import date

CURATED_UNTIL = date(2026, 6, 30)

PARTY_COLOURS = {
    ("NZL", "Labour"): "#D82A20", ("NZL", "National"): "#00529F",
    ("AUS", "Labor"): "#DE3533", ("AUS", "Liberal"): "#0047AB", ("AUS", "Country"): "#006644",
    ("GBR", "Labour"): "#E4003B", ("GBR", "Conservative"): "#0087DC",
    ("USA", "Democratic"): "#0015BC", ("USA", "Republican"): "#E9141D",
}

PARTY_NAMES = {
    ("NZL", "Labour"): "New Zealand Labour Party", ("NZL", "National"): "New Zealand National Party",
    ("AUS", "Labor"): "Australian Labor Party", ("AUS", "Liberal"): "Liberal Party of Australia",
    ("AUS", "Country"): "Country Party (Australia)",
    ("GBR", "Labour"): "Labour Party (UK)", ("GBR", "Conservative"): "Conservative Party (UK)",
    ("USA", "Democratic"): "Democratic Party", ("USA", "Republican"): "Republican Party",
}

# (country, leader, party, start, end or None while in office)
TERMS = [
    ("NZL", "Peter Fraser", "Labour", "1940-03-27", "1949-12-13"),
    ("NZL", "Sidney Holland", "National", "1949-12-13", "1957-09-20"),
    ("NZL", "Keith Holyoake", "National", "1957-09-20", "1957-12-12"),
    ("NZL", "Walter Nash", "Labour", "1957-12-12", "1960-12-12"),
    ("NZL", "Keith Holyoake", "National", "1960-12-12", "1972-02-07"),
    ("NZL", "Jack Marshall", "National", "1972-02-07", "1972-12-08"),
    ("NZL", "Norman Kirk", "Labour", "1972-12-08", "1974-08-31"),
    ("NZL", "Bill Rowling", "Labour", "1974-09-06", "1975-12-12"),
    ("NZL", "Robert Muldoon", "National", "1975-12-12", "1984-07-26"),
    ("NZL", "David Lange", "Labour", "1984-07-26", "1989-08-08"),
    ("NZL", "Geoffrey Palmer", "Labour", "1989-08-08", "1990-09-04"),
    ("NZL", "Mike Moore", "Labour", "1990-09-04", "1990-11-02"),
    ("NZL", "Jim Bolger", "National", "1990-11-02", "1997-12-08"),
    ("NZL", "Jenny Shipley", "National", "1997-12-08", "1999-12-10"),
    ("NZL", "Helen Clark", "Labour", "1999-12-10", "2008-11-19"),
    ("NZL", "John Key", "National", "2008-11-19", "2016-12-12"),
    ("NZL", "Bill English", "National", "2016-12-12", "2017-10-26"),
    ("NZL", "Jacinda Ardern", "Labour", "2017-10-26", "2023-01-25"),
    ("NZL", "Chris Hipkins", "Labour", "2023-01-25", "2023-11-27"),
    ("NZL", "Christopher Luxon", "National", "2023-11-27", None),

    ("AUS", "John Curtin", "Labor", "1941-10-07", "1945-07-05"),
    ("AUS", "Frank Forde", "Labor", "1945-07-06", "1945-07-13"),
    ("AUS", "Ben Chifley", "Labor", "1945-07-13", "1949-12-19"),
    ("AUS", "Robert Menzies", "Liberal", "1949-12-19", "1966-01-26"),
    ("AUS", "Harold Holt", "Liberal", "1966-01-26", "1967-12-19"),
    ("AUS", "John McEwen", "Country", "1967-12-19", "1968-01-10"),
    ("AUS", "John Gorton", "Liberal", "1968-01-10", "1971-03-10"),
    ("AUS", "William McMahon", "Liberal", "1971-03-10", "1972-12-05"),
    ("AUS", "Gough Whitlam", "Labor", "1972-12-05", "1975-11-11"),
    ("AUS", "Malcolm Fraser", "Liberal", "1975-11-11", "1983-03-11"),
    ("AUS", "Bob Hawke", "Labor", "1983-03-11", "1991-12-20"),
    ("AUS", "Paul Keating", "Labor", "1991-12-20", "1996-03-11"),
    ("AUS", "John Howard", "Liberal", "1996-03-11", "2007-12-03"),
    ("AUS", "Kevin Rudd", "Labor", "2007-12-03", "2010-06-24"),
    ("AUS", "Julia Gillard", "Labor", "2010-06-24", "2013-06-27"),
    ("AUS", "Kevin Rudd", "Labor", "2013-06-27", "2013-09-18"),
    ("AUS", "Tony Abbott", "Liberal", "2013-09-18", "2015-09-15"),
    ("AUS", "Malcolm Turnbull", "Liberal", "2015-09-15", "2018-08-24"),
    ("AUS", "Scott Morrison", "Liberal", "2018-08-24", "2022-05-23"),
    ("AUS", "Anthony Albanese", "Labor", "2022-05-23", None),

    ("GBR", "Winston Churchill", "Conservative", "1940-05-10", "1945-07-26"),
    ("GBR", "Clement Attlee", "Labour", "1945-07-26", "1951-10-26"),
    ("GBR", "Winston Churchill", "Conservative", "1951-10-26", "1955-04-05"),
    ("GBR", "Anthony Eden", "Conservative", "1955-04-06", "1957-01-09"),
    ("GBR", "Harold Macmillan", "Conservative", "1957-01-10", "1963-10-18"),
    ("GBR", "Alec Douglas-Home", "Conservative", "1963-10-19", "1964-10-16"),
    ("GBR", "Harold Wilson", "Labour", "1964-10-16", "1970-06-19"),
    ("GBR", "Edward Heath", "Conservative", "1970-06-19", "1974-03-04"),
    ("GBR", "Harold Wilson", "Labour", "1974-03-04", "1976-04-05"),
    ("GBR", "James Callaghan", "Labour", "1976-04-05", "1979-05-04"),
    ("GBR", "Margaret Thatcher", "Conservative", "1979-05-04", "1990-11-28"),
    ("GBR", "John Major", "Conservative", "1990-11-28", "1997-05-02"),
    ("GBR", "Tony Blair", "Labour", "1997-05-02", "2007-06-27"),
    ("GBR", "Gordon Brown", "Labour", "2007-06-27", "2010-05-11"),
    ("GBR", "David Cameron", "Conservative", "2010-05-11", "2016-07-13"),
    ("GBR", "Theresa May", "Conservative", "2016-07-13", "2019-07-24"),
    ("GBR", "Boris Johnson", "Conservative", "2019-07-24", "2022-09-06"),
    ("GBR", "Liz Truss", "Conservative", "2022-09-06", "2022-10-25"),
    ("GBR", "Rishi Sunak", "Conservative", "2022-10-25", "2024-07-05"),
    ("GBR", "Keir Starmer", "Labour", "2024-07-05", None),

    ("USA", "Franklin D. Roosevelt", "Democratic", "1933-03-04", "1945-04-12"),
    ("USA", "Harry S. Truman", "Democratic", "1945-04-12", "1953-01-20"),
    ("USA", "Dwight D. Eisenhower", "Republican", "1953-01-20", "1961-01-20"),
    ("USA", "John F. Kennedy", "Democratic", "1961-01-20", "1963-11-22"),
    ("USA", "Lyndon B. Johnson", "Democratic", "1963-11-22", "1969-01-20"),
    ("USA", "Richard Nixon", "Republican", "1969-01-20", "1974-08-09"),
    ("USA", "Gerald Ford", "Republican", "1974-08-09", "1977-01-20"),
    ("USA", "Jimmy Carter", "Democratic", "1977-01-20", "1981-01-20"),
    ("USA", "Ronald Reagan", "Republican", "1981-01-20", "1989-01-20"),
    ("USA", "George H. W. Bush", "Republican", "1989-01-20", "1993-01-20"),
    ("USA", "Bill Clinton", "Democratic", "1993-01-20", "2001-01-20"),
    ("USA", "George W. Bush", "Republican", "2001-01-20", "2009-01-20"),
    ("USA", "Barack Obama", "Democratic", "2009-01-20", "2017-01-20"),
    ("USA", "Donald Trump", "Republican", "2017-01-20", "2021-01-20"),
    ("USA", "Joe Biden", "Democratic", "2021-01-20", "2025-01-20"),
    ("USA", "Donald Trump", "Republican", "2025-01-20", None),
]

COUNTRIES = {t[0] for t in TERMS}


def offices(iso3: str) -> tuple[str, ...]:
    return ("head of government", "head of state") if iso3 == "USA" else ("head of government",)


def curated_events() -> list[tuple]:
    """Leader event rows in the same shape as the Wikidata reader's."""
    out = []
    for iso3, name, party, start, end in TERMS:
        s, e = date.fromisoformat(start), date.fromisoformat(end) if end else None
        slug = name.lower().replace(" ", "_").replace(".", "")
        for office in offices(iso3):
            out.append((iso3, f"leader:{iso3}:{'hos' if 'state' in office else 'hog'}:curated:{slug}:{start}", "leader",
                        office, f"{name} ({office})", s, e, "day", None, None, None, None,
                        PARTY_NAMES[(iso3, party)], PARTY_COLOURS[(iso3, party)]))
    return out


def merge(events: list[tuple]) -> list[tuple]:
    """Wikidata's leader rows with the key countries' terms up to CURATED_UNTIL replaced by the curated ones."""
    def curated_here(e: tuple) -> bool:
        return (e[2] == "leader" and e[0] in COUNTRIES and e[3] in offices(e[0])
                and (e[5] is None or e[5] <= CURATED_UNTIL))
    return [e for e in events if not curated_here(e)] + curated_events()
