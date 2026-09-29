"""Common broker interface implemented by PaperBroker and MT5Broker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Position:
    id: str
    direction: str  # "long" or "short"
    lots: float
    entry_price: float
    stop_price: float
    take_profit_price: float


@dataclass
class ClosedTrade:
    """A completed trade, reported by a broker for journaling.

    `initial_stop` (the stop as placed, before any trailing) is what the
    journal needs to compute an R-multiple -- `Position.stop_price` may have
    since moved.
    """

    position_id: str
    direction: str
    lots: float
    entry_price: float
    exit_price: float
    initial_stop: float


class Broker(Protocol):
    def get_equity(self) -> float: ...

    def get_open_positions(self) -> list[Position]: ...

    def open_position(
        self,
        direction: str,
        lots: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
    ) -> Position: ...

    def modify_stop(self, position_id: str, new_stop_price: float) -> None: ...

    def close_position(self, position_id: str, exit_price: float) -> None: ...
