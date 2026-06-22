# signal_system/config/intraday_curve.py
"""
Static placeholder for expected cumulative volume fraction by time of day.

WHY THIS EXISTS:
Alpaca's dailyBar.v is cumulative volume since market open. Comparing that
directly against a full 20-day average produces a ratio that mechanically
climbs from ~0 to ~1 over every trading session, regardless of whether
anything unusual is happening. A ticker can only ever cross a flat 2.5x
threshold late in the day. This curve lets us compare today's volume-so-far
against the volume we'd *expect* by this point in the session, so a spike
means the same thing at 10am as it does at 3:55pm.

TODO: replace with an empirically-derived curve once 20+ trading days are
logged in market_data — compute actual avg cumulative-volume-by-time-bucket
per ticker or sector from real intraday snapshots, rather than this hardcoded
estimate. Revisit at the same time as the §16 first calibration review
(after 30 logged signals).
"""

# (minutes_since_open, expected_cumulative_fraction_of_daily_volume)
# U-shaped: heavy at open, quiet midday, heavy at close.
# Market hours: 9:30-16:00 ET = 390 minutes.
INTRADAY_VOLUME_CURVE = [
    (0,   0.00),
    (15,  0.07),
    (30,  0.12),
    (60,  0.20),
    (90,  0.27),
    (120, 0.33),
    (150, 0.38),
    (180, 0.43),  # ~12:30pm ET, midday lull
    (210, 0.48),
    (240, 0.54),
    (270, 0.61),
    (300, 0.68),
    (330, 0.76),
    (360, 0.85),
    (390, 1.00),  # market close
]


def expected_volume_fraction(minutes_since_open: float) -> float:
    """
    Linear interpolation between curve points.
    Returns expected fraction (0.0-1.0) of daily volume that should have
    traded by this many minutes into the session.
    """
    minutes_since_open = max(0, min(390, minutes_since_open))
    points = INTRADAY_VOLUME_CURVE
    for i in range(len(points) - 1):
        t0, f0 = points[i]
        t1, f1 = points[i + 1]
        if t0 <= minutes_since_open <= t1:
            if t1 == t0:
                return f0
            ratio = (minutes_since_open - t0) / (t1 - t0)
            return f0 + ratio * (f1 - f0)
    return 1.0
