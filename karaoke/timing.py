from __future__ import annotations
import json
from dataclasses import dataclass, replace
from typing import List


@dataclass
class Word:
    text: str
    start: float
    end: float
    bg: bool = False

    def retimed(self, start: float, end: float) -> "Word":
        """A copy with new start/end, carrying every other field (text, bg).
        Use this for all retiming (shifts, reflows, onset snaps) instead of
        rebuilding `Word(w.text, ...)` by hand — the manual form silently drops
        fields when new ones are added (the wrap/bg render bugs). One place to
        keep correct as Word grows."""
        return replace(self, start=start, end=end)


@dataclass
class Line:
    words: List[Word]
    wrap: bool = False

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def start(self) -> float:
        nb = [w for w in self.words if not w.bg]
        return min((w.start for w in nb), default=self.words[0].start)

    @property
    def end(self) -> float:
        nb = [w for w in self.words if not w.bg]
        return max((w.end for w in nb), default=self.words[-1].end)


@dataclass
class Timing:
    lines: List[Line]

    def to_json(self) -> str:
        def w2d(w):
            d = {"text": w.text, "start": w.start, "end": w.end}
            if w.bg:
                d["bg"] = True
            return d
        def l2d(ln):
            d = {"words": [w2d(w) for w in ln.words]}
            if ln.wrap:
                d["wrap"] = True
            return d
        return json.dumps({"lines": [l2d(ln) for ln in self.lines]}, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "Timing":
        data = json.loads(s)
        lines = [
            Line(words=[Word(w["text"], float(w["start"]), float(w["end"]),
                             bg=bool(w.get("bg", False)))
                        for w in ln["words"]],
                 wrap=bool(ln.get("wrap", False)))
            for ln in data["lines"]
        ]
        return cls(lines=lines)
