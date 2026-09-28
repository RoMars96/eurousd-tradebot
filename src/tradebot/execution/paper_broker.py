"""In-memory paper-trading broker for dry-running the bot against a live feed
without touching a real account.
"""
from __future__ import annotations

import itertools

import pandas as pd

from tradebot.execution.broker import Position


class PaperBroker:
    def __init__(self, starting_equity: float) -> None:
        self._equity = starting_equity
        self._positions: dict[str, Position] = {}
        self._id_counter = itertools.count(1)

    def get_equity(self) -> float:
        return self._equity

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def open_position(
        self,
        direction: str,
        lots: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
    ) -> Position:
        pos_id = str(next(self._id_counter))
        position = Position(pos_id, direction, lots, entry_price, stop_price, take_profit_price)
        self._positions[pos_id] = position
        return position

    def modify_stop(self, position_id: str, new_stop_price: float) -> None:
        if position_id in self._positions:
            self._positions[position_id].stop_price = new_stop_price

    def close_position(self, position_id: str, exit_price: float, pip_size: float = 0.0001,
                        pip_value_per_standard_lot: float = 10.0) -> None:
        position = self._positions.pop(position_id, None)
        if position is None:
            return
        pip_diff = (
            (exit_price - position.entry_price) / pip_size
            if position.direction == "long"
            else (position.entry_price - exit_price) / pip_size
        )
        self._equity += pip_diff * pip_value_per_standard_lot * position.lots

    def check_exits(self, bar: pd.Series) -> None:
        """Close any position whose stop or take-profit was hit by this bar.

        No broker-side order book exists in paper mode, so exits must be
        simulated here. Same conservative stop-first-if-both-hit assumption
        as the backtest engine.
        """
        for position_id, position in list(self._positions.items()):
            if position.direction == "long":
                if bar["low"] <= position.stop_price:
                    self.close_position(position_id, position.stop_price)
                elif bar["high"] >= position.take_profit_price:
                    self.close_position(position_id, position.take_profit_price)
            else:
                if bar["high"] >= position.stop_price:
                    self.close_position(position_id, position.stop_price)
                elif bar["low"] <= position.take_profit_price:
                    self.close_position(position_id, position.take_profit_price)
