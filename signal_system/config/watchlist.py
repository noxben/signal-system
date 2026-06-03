# signal_system/config/watchlist.py
"""
Static watchlist — 37 tickers, sector-mapped.
§3: Do not modify at runtime. No expansion beyond 50 before filter validation.
"""

WATCHLIST: dict[str, list[str]] = {
    "defense":        ["LMT", "RTX", "NOC", "GD", "LHX"],
    "semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU"],
    "energy":         ["XOM", "CVX", "COP", "SLB", "EOG"],
    "pharma":         ["LLY", "PFE", "MRK", "JNJ", "ABBV"],
    "industrials":    ["CAT", "DE", "BA", "GE"],
    "big_tech":       ["MSFT", "AMZN", "GOOG", "META"],
}

# Flat list for iteration
ALL_TICKERS: list[str] = [t for tickers in WATCHLIST.values() for t in tickers]

# Reverse map: ticker -> sector
TICKER_SECTOR: dict[str, str] = {
    ticker: sector
    for sector, tickers in WATCHLIST.items()
    for ticker in tickers
}


def get_sector(ticker: str) -> str | None:
    return TICKER_SECTOR.get(ticker.upper())
