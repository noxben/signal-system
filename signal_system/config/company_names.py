# signal_system/config/company_names.py
"""
Company name -> ticker lookup for matching spaCy ORG entities against
the watchlist. spaCy recognizes "Nvidia" or "Pfizer" as an organization
but the entity text won't equal the ticker symbol on its own — this
table bridges that gap.

Not exhaustive. Extend as misses are found during news_worker review.
Keys are uppercased for direct comparison against uppercased entity text.
"""

COMPANY_TO_TICKER: dict[str, str] = {
    # Big Tech
    "NVIDIA": "NVDA",
    "MICROSOFT": "MSFT",
    "AMAZON": "AMZN",
    "GOOGLE": "GOOG",
    "ALPHABET": "GOOG",
    "META": "META",
    "FACEBOOK": "META",

    # Defense
    "LOCKHEED": "LMT",
    "LOCKHEED MARTIN": "LMT",
    "RAYTHEON": "RTX",
    "RTX CORPORATION": "RTX",
    "NORTHROP": "NOC",
    "NORTHROP GRUMMAN": "NOC",
    "GENERAL DYNAMICS": "GD",
    "L3HARRIS": "LHX",
    "L3 HARRIS": "LHX",

    # Industrials
    "BOEING": "BA",
    "GENERAL ELECTRIC": "GE",
    "GE AEROSPACE": "GE",
    "CATERPILLAR": "CAT",
    "DEERE": "DE",
    "JOHN DEERE": "DE",

    # Energy
    "EXXON": "XOM",
    "EXXONMOBIL": "XOM",
    "EXXON MOBIL": "XOM",
    "CHEVRON": "CVX",
    "CONOCOPHILLIPS": "COP",
    "CONOCO PHILLIPS": "COP",
    "SCHLUMBERGER": "SLB",

    # Pharma
    "PFIZER": "PFE",
    "MERCK": "MRK",
    "ELI LILLY": "LLY",
    "LILLY": "LLY",
    "ABBVIE": "ABBV",
    # NOTE: "JOHNSON" intentionally omitted — too many false positives
    # (Johnson Controls, Johnson & Johnson articles not about JNJ stock,
    # generic "Johnson" surnames). Match on "JOHNSON & JOHNSON" instead.
    "JOHNSON & JOHNSON": "JNJ",

    # Semiconductors
    "BROADCOM": "AVGO",
    "QUALCOMM": "QCOM",
    "ADVANCED MICRO DEVICES": "AMD",
    "MICRON": "MU",
    "MICRON TECHNOLOGY": "MU",
    "INTEL": "INTC",
}
