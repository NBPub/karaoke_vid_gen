from __future__ import annotations
import csv
from datetime import datetime

COLUMNS = ["timestamp", "op", "model", "seed", "source", "whisper_params",
           "timing_mtime", "render_mode", "encoder", "duration", "notes"]

PROV_FIELDS = ("model", "seed", "source", "whisper_params")

_MUTATING_OPS = ("align", "nudge", "split", "ab-keep")


def _pristine_align(rows):
    """The (model, seed) of a pristine alignment: the most recent mutating op must
    be an `align` (returning its model and recorded first-line seed). Any
    nudge/split/ab-keep after it, or no align at all, returns (None, ""). Renders
    are non-mutating and ignored."""
    for row in reversed(rows):
        if row.get("op") in _MUTATING_OPS:
            if row.get("op") == "align":
                return (row.get("model") or None), (row.get("seed") or "")
            return None, ""
    return None, ""


def _pristine_align_model(rows):
    """The model of a pristine alignment (see `_pristine_align`); None otherwise."""
    return _pristine_align(rows)[0]


def pristine_align(sp):
    """Read the song's history.csv and apply `_pristine_align`. (None, "") when
    history is missing/disabled. The seed lets callers tell a cold align from a
    `--first-line`-seeded one so A/B reuse doesn't silently ignore the hint."""
    path = sp.history_csv
    if not path.exists():
        return None, ""
    with path.open(newline="", encoding="utf-8") as f:
        return _pristine_align(list(csv.DictReader(f)))


def pristine_align_model(sp):
    """The model of a pristine alignment (see `pristine_align`); None otherwise."""
    return pristine_align(sp)[0]


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"


def _stamp(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts) if ts is not None else datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M")


def append_row(sp, cfg, op, *, duration_s=None, model="", seed="", source="",
               whisper_params="", render_mode="", encoder="", notes="") -> None:
    """Append one row to the song's history.csv. No-op when history is disabled.
    Call only after the operation's real work has run."""
    if not cfg.history.enabled:
        return
    path = sp.history_csv
    tmtime = _stamp(sp.timing_json.stat().st_mtime) if sp.timing_json.exists() else ""
    row = {
        "timestamp": _stamp(), "op": op, "model": model, "seed": seed,
        "source": source, "whisper_params": whisper_params, "timing_mtime": tmtime,
        "render_mode": render_mode, "encoder": encoder,
        "duration": format_duration(duration_s) if duration_s is not None else "",
        "notes": notes,
    }
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def current_provenance(sp, model: str | None = None) -> dict:
    """Provenance coherent with a single model's rows. With ``model=None`` the
    most recently recorded model is used. The other fields (seed, source,
    whisper_params) take their most recent non-empty value FROM ROWS OF THAT
    MODEL ONLY — so switching aligners (e.g. whisper -> mms via ab-keep) never
    leaks the old model's Whisper params onto the new model's rows (MMS_FA has
    none). Empty when the file is missing or the model never appears."""
    out = {k: "" for k in PROV_FIELDS}
    path = sp.history_csv
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if model is None:
        for row in rows:                       # latest non-empty model wins
            if row.get("model"):
                model = row["model"]
    out["model"] = model or ""
    for row in rows:                           # earliest -> latest; later wins
        if model and row.get("model") == model:
            for k in ("seed", "source", "whisper_params"):
                if row.get(k):
                    out[k] = row[k]
    return out
