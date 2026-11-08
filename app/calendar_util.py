"""Month grid built with the stdlib `calendar` module.

Fixes the old template maths: December rolled into January of the same year, and
Monday-first weekday numbers were laid under a Sunday-first header.
"""
import calendar

from .timeutils import local_today, month_str, shift_month


def month_grid(year: int, month: int, day_info: dict | None = None) -> dict:
    """Sunday-first grid. `day_info` maps 'YYYY-MM-DD' -> any dict to attach to that cell."""
    day_info = day_info or {}
    today = local_today().isoformat()
    weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(None)
                continue
            key = f"{year:04d}-{month:02d}-{day:02d}"
            row.append({"day": day, "date": key, "is_today": key == today, "info": day_info.get(key)})
        weeks.append(row)
    py, pm = shift_month(year, month, -1)
    ny, nm = shift_month(year, month, 1)
    return {
        "weeks": weeks,
        "title": f"{calendar.month_name[month]} {year}",
        "month": month_str(year, month),
        "prev": month_str(py, pm),
        "next": month_str(ny, nm),
    }
