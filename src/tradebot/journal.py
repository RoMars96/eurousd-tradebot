"""Persistent trade journal.

Every closed trade (paper or live) is appended here as one JSON line. This
is the substrate the bot uses to judge itself over a large sample rather
than reacting to any single trade -- see PHILOSOPHY.md.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class JournalEntry:
    time: str  # ISO8601 UTC
    direction: str
    lots: float
    entry_price: float
    exit_price: float
    initial_stop: float
    pnl: float
    r_multiple: float
    mode: str  # "paper" or "live"


class TradeJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def record(self, entry: JournalEntry) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def load_all(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        entries = []
        with open(self.path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(JournalEntry(**json.loads(line)))
        return entries

    def count(self) -> int:
        return len(self.load_all())
