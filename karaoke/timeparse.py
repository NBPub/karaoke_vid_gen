from __future__ import annotations


def parse_time(s: str) -> float:
    """'66', '66.5', or 'm:ss(.f)' -> seconds."""
    s = s.strip()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)
