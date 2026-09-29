"""Persistent record of every strategy configuration ever tested.

Test 20 configurations and one will look significant at p < 0.05 by pure
chance. The fix (Bonferroni) is to divide the significance threshold by
the number of tests -- which only works if the count is honest across
*every* research session, not just today's run. This log is that count.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from tradebot.research.evaluation import Summary


class ResearchLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    @staticmethod
    def _key(hypothesis: str, params: dict, data_label: str) -> str:
        return json.dumps([hypothesis, params, data_label], sort_keys=True)

    def record(self, hypothesis: str, params: dict, data_label: str, summary: Summary) -> None:
        entry = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "key": self._key(hypothesis, params, data_label),
            "hypothesis": hypothesis,
            "params": params,
            "data": data_label,
            "summary": asdict(summary),
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def record_event(self, event: str, detail: dict) -> None:
        entry = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "event": event, **detail}
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _entries(self) -> list[dict]:
        with open(self.path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def unique_configs(self) -> int:
        return len({e["key"] for e in self._entries() if "key" in e})

    def holdout_revealed(self, hypothesis: str, data_label: str) -> bool:
        return any(
            e.get("event") == "holdout_revealed"
            and e.get("hypothesis") == hypothesis
            and e.get("data") == data_label
            for e in self._entries()
        )
