"""
US Stock Market Calendar - NYSE holidays and trading hours.
"""
from datetime import date, datetime, time, timedelta
from typing import Optional
import pytz

# US Eastern timezone (NYSE operates in ET)
EASTERN = pytz.timezone("US/Eastern")

# Market hours (Eastern Time)
MARKET_OPEN = time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET
EARLY_CLOSE = time(13, 0)   # 1:00 PM ET for early close days

# 2025 NYSE Holidays (market fully closed)
HOLIDAYS_2025 = frozenset([
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # Martin Luther King Jr. Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 20),   # Juneteenth (observed - Friday)
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving Day
    date(2025, 12, 25),  # Christmas Day
])

# 2025 Early Close Days (1:00 PM ET close)
EARLY_CLOSE_DAYS_2025 = frozenset([
    date(2025, 7, 3),    # Day before Independence Day
    date(2025, 11, 28),  # Day after Thanksgiving
    date(2025, 12, 24),  # Christmas Eve
])

# 2026 holidays (for year-end trading)
HOLIDAYS_2026 = frozenset([
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed - Friday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving Day
    date(2026, 12, 25),  # Christmas Day
])

ALL_HOLIDAYS = HOLIDAYS_2025 | HOLIDAYS_2026


def get_current_et_time() -> datetime:
    """Get current time in US Eastern timezone."""
    return datetime.now(EASTERN)


def is_weekend(dt: datetime) -> bool:
    """Check if date is a weekend (Saturday=5, Sunday=6)."""
    return dt.weekday() >= 5


def is_holiday(dt: datetime) -> bool:
    """Check if date is a market holiday."""
    return dt.date() in ALL_HOLIDAYS


def is_early_close_day(dt: datetime) -> bool:
    """Check if today is an early close day (1:00 PM close)."""
    return dt.date() in EARLY_CLOSE_DAYS_2025


def get_market_close_time(dt: datetime) -> time:
    """Get the market close time for a given date."""
    if is_early_close_day(dt):
        return EARLY_CLOSE
    return MARKET_CLOSE


def is_market_open(dt: Optional[datetime] = None) -> bool:
    """
    Check if the US stock market is currently open.
    
    Args:
        dt: Optional datetime to check. If None, uses current time.
        
    Returns:
        True if market is open, False otherwise.
    """
    if dt is None:
        dt = get_current_et_time()
    elif dt.tzinfo is None:
        dt = EASTERN.localize(dt)
    else:
        dt = dt.astimezone(EASTERN)
    
    # Check weekend
    if is_weekend(dt):
        return False
    
    # Check holiday
    if is_holiday(dt):
        return False
    
    # Check time
    current_time = dt.time()
    close_time = get_market_close_time(dt)
    
    return MARKET_OPEN <= current_time < close_time


def next_market_open(from_dt: Optional[datetime] = None) -> datetime:
    """
    Calculate the next market open time.
    
    Args:
        from_dt: Starting datetime. If None, uses current time.
        
    Returns:
        Datetime of next market open in Eastern time.
    """
    if from_dt is None:
        from_dt = get_current_et_time()
    elif from_dt.tzinfo is None:
        from_dt = EASTERN.localize(from_dt)
    else:
        from_dt = from_dt.astimezone(EASTERN)
    
    # Start checking from today or tomorrow based on current time
    check_date = from_dt.date()
    
    # If we're past market open today, start checking tomorrow
    if from_dt.time() >= MARKET_OPEN:
        check_date += timedelta(days=1)
    
    # Find next trading day (skip weekends and holidays)
    while True:
        check_dt = EASTERN.localize(datetime.combine(check_date, MARKET_OPEN))
        
        if not is_weekend(check_dt) and not is_holiday(check_dt):
            return check_dt
        
        check_date += timedelta(days=1)
        
        # Safety: don't loop forever
        if check_date > from_dt.date() + timedelta(days=14):
            raise RuntimeError("Could not find next trading day within 14 days")


def seconds_until_market_open(from_dt: Optional[datetime] = None) -> int:
    """
    Calculate seconds until next market open.
    
    Returns:
        Number of seconds until market opens. Returns 0 if market is currently open.
    """
    if from_dt is None:
        from_dt = get_current_et_time()
    
    if is_market_open(from_dt):
        return 0
    
    next_open = next_market_open(from_dt)
    delta = next_open - from_dt
    return max(0, int(delta.total_seconds()))


def seconds_until_market_close(from_dt: Optional[datetime] = None) -> int:
    """
    Calculate seconds until market close.
    
    Returns:
        Number of seconds until market closes. Returns 0 if market is closed.
    """
    if from_dt is None:
        from_dt = get_current_et_time()
    elif from_dt.tzinfo is None:
        from_dt = EASTERN.localize(from_dt)
    else:
        from_dt = from_dt.astimezone(EASTERN)
    
    if not is_market_open(from_dt):
        return 0
    
    close_time = get_market_close_time(from_dt)
    close_dt = EASTERN.localize(datetime.combine(from_dt.date(), close_time))
    
    delta = close_dt - from_dt
    return max(0, int(delta.total_seconds()))


def get_market_status() -> dict:
    """
    Get current market status information.
    
    Returns:
        Dictionary with market status details.
    """
    now = get_current_et_time()
    is_open = is_market_open(now)
    
    return {
        "current_time_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "is_open": is_open,
        "is_holiday": is_holiday(now),
        "is_weekend": is_weekend(now),
        "is_early_close": is_early_close_day(now),
        "market_close_time": get_market_close_time(now).strftime("%H:%M"),
        "seconds_until_open": seconds_until_market_open(now) if not is_open else 0,
        "seconds_until_close": seconds_until_market_close(now) if is_open else 0,
        "next_open": next_market_open(now).strftime("%Y-%m-%d %H:%M:%S %Z") if not is_open else None,
    }


if __name__ == "__main__":
    # Quick test
    status = get_market_status()
    print("Market Status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
