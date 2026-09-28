from __future__ import annotations
from datetime import time
from zoneinfo import ZoneInfo
import pandas as pd

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def _in_window(local_time: time, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    x = local_time.hour * 60 + local_time.minute
    return start_h * 60 + start_m <= x < end_h * 60 + end_m


def session_label(ts: pd.Timestamp) -> str:
    ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
    london = ts.tz_convert(LONDON)
    ny = ts.tz_convert(NEW_YORK)
    if _in_window(london.time(), 8, 0, 13, 0):
        return "LONDON"
    if _in_window(ny.time(), 8, 0, 13, 0):
        return "NEW_YORK"
    if _in_window(ny.time(), 13, 0, 16, 0):
        return "NEW_YORK_LATE"
    return "OTHER"


def session_state(index: pd.DatetimeIndex) -> pd.DataFrame:
    idx = pd.DatetimeIndex(index)
    idx = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    london = idx.tz_convert(LONDON)
    ny = idx.tz_convert(NEW_YORK)
    out = pd.DataFrame(index=idx)
    out["session"] = [session_label(x) for x in idx]
    out["london_open_window"] = [_in_window(x.time(), 8, 0, 10, 0) for x in london]
    out["new_york_open_window"] = [_in_window(x.time(), 9, 30, 11, 30) for x in ny]
    out["london_local_date"] = london.date
    out["new_york_local_date"] = ny.date
    return out
