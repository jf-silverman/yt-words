"""Assertions for names_agree() — the ticker/company mismatch detector.

Run:  python3 code/test_names_agree.py

Every case here is one we actually hit. The pairs that must NOT agree are the
point of the whole function: a wrong ticker attaches a call to a real, unrelated
company and silently inherits its price history, so a false "agree" is the
expensive direction. The pairs that MUST agree exist to keep the review queue
from filling with noise nobody will ever act on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import names_agree, _name_aliases  # noqa: E402

# (yahoo_name, our_stored_name)
AGREE = [
    # Legal-suffix and punctuation noise
    ("Lam Research Corporation", "Lam Research"),
    ("Abbott Laboratories", "Abbott Labs"),
    ("Elanco Animal Health Incorporated", "Elanco Animal Health"),
    ("Paychex, Inc.", "Paychex"),
    ("Deckers Outdoor Corporation", "Deckers Outdoor"),
    ("XPO, Inc.", "XPO"),
    ("DuPont de Nemours, Inc.", "DuPont de Nemours"),
    # Our stored name is the distinctive word; Yahoo adds a generic one. This is
    # why the Jaccard branch has no >=2-word guard — see the note in names_agree.
    ("Amazon.com, Inc.", "Amazon"),
    ("Cisco Systems, Inc.", "Cisco"),
    ("Ford Motor Company", "Ford"),
    ("Coinbase Global, Inc.", "Coinbase"),
    # Spelling / spacing variants of the same name
    ("JPMorgan Chase & Co.", "JP Morgan Chase"),
    ("UnitedHealth Group Incorporated", "United Health"),
    ("Symbotic Inc.", "Symbiotic"),
    ("Timken Company (The)", "Timken"),
    # Renames — the reason _name_aliases exists
    ("Strategy Inc", "Strategy (formerly MicroStrategy)"),
    ("Strategy Inc", "MicroStrategy (now Strategy)"),
    ("Meta Platforms, Inc.", "Meta Platforms (formerly Facebook)"),
    ("Alphabet Inc.", "Alphabet (fka Google)"),
    # Bare parentheticals used as an alias
    ("RH", "RH (Restoration Hardware)"),
    ("BXP, Inc.", "BXP (Boston Properties)"),
    # Missing data must never cry wolf
    ("Nvidia Corporation", ""),
    ("", "Nvidia"),
    ("Nvidia Corporation", None),
]

# These are different companies. Every one is a confusion we made or nearly made.
DISAGREE = [
    ("Blackstone Inc.", "BlackRock"),          # 0.74 on difflib — the canonical trap
    ("BlackRock, Inc.", "Blackstone"),
    ("Marriott International, Inc.", "Marriott Vacations Worldwide"),
    ("Lumen Technologies, Inc.", "Lite-On Technology"),
    ("Synopsys, Inc.", "SanDisk"),
    ("Nucor Corporation", "Newell Brands"),
    ("Eli Lilly and Company", "Lam Research"),
    ("AECOM", "Acuity Electronics"),
    ("Cadence Design Systems, Inc.", "CoreWeave"),
    ("Abacus Global Management, Inc.", "Barrick Gold"),
    ("Chesapeake Utilities Corporation", "Campbell Soup Company"),
    ("Bank of New York Mellon Corp", "Bob Evans Farms"),
    ("Brandywine Realty Trust", "Blackstone"),
    ("Immatics N.V.", "Immunity Bio"),
    ("Inspire Medical Systems, Inc.", "Inspira Technologies"),
    ("Kinross Gold Corporation", "Kagra"),
    ("MIND Technology, Inc.", "Biphenium Therapeutics"),
    ("Ur Energy Inc", "United States Rare Earth"),
    ("Liberty All-Star Equity Fund", "USA Rare Earth"),
    ("Vanguard Developed Markets ex-US", "Verdiv"),
    ("Tempo Automation Holdings, Inc.", "Tempest AI"),
    # An alias clause must not become a backdoor: neither half matches here.
    ("Petroleo Brasileiro S.A.", "Polar Beverage (formerly Polar Bear)"),
]

ALIASES = [
    ("Strategy (formerly MicroStrategy)", ["Strategy", "MicroStrategy"]),
    ("RH (Restoration Hardware)", ["RH", "Restoration Hardware"]),
    ("Nvidia", ["Nvidia"]),
    ("", []),
]


def main() -> int:
    failures = []

    for a, b in AGREE:
        if not names_agree(a, b):
            failures.append(f"should AGREE but did not: {a!r} vs {b!r}")

    for a, b in DISAGREE:
        if names_agree(a, b):
            failures.append(f"should DISAGREE but agreed: {a!r} vs {b!r}")
        # The check must be symmetric — it is called with both orderings.
        if names_agree(b, a):
            failures.append(f"should DISAGREE (reversed) but agreed: {b!r} vs {a!r}")

    for raw, expected in ALIASES:
        got = _name_aliases(raw)
        if got != expected:
            failures.append(f"_name_aliases({raw!r}) -> {got!r}, expected {expected!r}")

    total = len(AGREE) + len(DISAGREE) * 2 + len(ALIASES)
    if failures:
        print(f"FAIL — {len(failures)} of {total} assertions failed:\n")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"PASS — {total} assertions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
