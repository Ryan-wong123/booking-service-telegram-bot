"""All datetimes are stored as naive UTC and shown/entered in APP_TIMEZONE."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(tz())


def local_to_utc(d: date, t: time) -> datetime:
    local = datetime.combine(d, t).replace(tzinfo=tz())
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def local_today() -> date:
    return to_local(utcnow()).date()


def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    start = local_to_utc(date(year, month, 1), time(0, 0))
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = local_to_utc(date(ny, nm, 1), time(0, 0))
    return start, end


def parse_month(raw: str | None) -> tuple[int, int]:
    """Parse 'YYYY-MM'; fall back to the current month on missing/bad input."""
    if raw:
        try:
            parsed = datetime.strptime(raw, "%Y-%m")
            return parsed.year, parsed.month
        except ValueError:
            pass
    today = local_today()
    return today.year, today.month


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)
