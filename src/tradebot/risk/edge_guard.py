"""Self-governing, sample-size-aware circuit breaker.

Mark Douglas's "Trading in the Zone" is explicit that wins and losses are
randomly distributed across any given edge's trades, and that you cannot
draw a valid conclusion about an edge from a small number of them. This
guard encodes that directly:

- Below `min_sample_size` closed trades, it NEVER halts trading. A losing
  streak within that window is not evidence the edge is broken -- it's
  exactly what "anything can happen" predicts. Panicking here would be the
  discretionary-trader mistake this bot exists to avoid.
- Once there's a large enough trailing sample, it watches the *average
  R-multiple over the most recent `min_sample_size` trades*. If that drops
  below `degradation_threshold_r`, new entries are paused -- but any
  already-open trade is left alone to hit its predefined stop or
  take-profit, never closed early out of reaction.
- It re-evaluates every loop and resumes automatically once the trailing
  window recovers, with no human toggle either way.

This is a heuristic, not a rigorous statistical hypothesis test -- it's
intentionally simple so its behavior is easy to reason about and audit.
"""
from __future__ import annotations

from dataclasses import dataclass

from tradebot.journal import JournalEntry


@dataclass
class EdgeStatus:
    can_trade: bool
    sample_size: int
    trailing_avg_r: float | None
    reason: str


class EdgeConfidenceGuard:
    def __init__(
        self,
        min_sample_size: int = 30,
        degradation_threshold_r: float = 0.0,
    ) -> None:
        self.min_sample_size = min_sample_size
        self.degradation_threshold_r = degradation_threshold_r

    def evaluate(self, journal_entries: list[JournalEntry]) -> EdgeStatus:
        sample_size = len(journal_entries)

        if sample_size < self.min_sample_size:
            return EdgeStatus(
                can_trade=True,
                sample_size=sample_size,
                trailing_avg_r=None,
                reason=(
                    f"sample size {sample_size} < {self.min_sample_size}: "
                    "too small to judge, trusting the backtested edge"
                ),
            )

        window = journal_entries[-self.min_sample_size :]
        trailing_avg_r = sum(e.r_multiple for e in window) / len(window)

        if trailing_avg_r < self.degradation_threshold_r:
            return EdgeStatus(
                can_trade=False,
                sample_size=sample_size,
                trailing_avg_r=trailing_avg_r,
                reason=(
                    f"trailing {self.min_sample_size}-trade avg R "
                    f"({trailing_avg_r:.2f}) below threshold "
                    f"({self.degradation_threshold_r:.2f}): pausing new entries"
                ),
            )

        return EdgeStatus(
            can_trade=True,
            sample_size=sample_size,
            trailing_avg_r=trailing_avg_r,
            reason=f"trailing {self.min_sample_size}-trade avg R = {trailing_avg_r:.2f}: within expectation",
        )
