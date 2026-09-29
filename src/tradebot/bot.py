"""Live/paper trading loop.

Polls MT5 for newly completed candles, re-evaluates the liquidity-sweep
strategy over the trailing history window, opens positions through the
configured broker when a fresh signal appears, and maintains trailing stops
on open positions each loop iteration.

This must run on the machine with the MT5 terminal installed and logged in
(see tradebot.data.mt5_feed and tradebot.execution.mt5_broker). Start with
`mode="paper"` against a DEMO account for at least a few weeks before ever
switching to `mode="live"`.
"""
from __future__ import annotations

import datetime as dt
import logging
import time

import pandas as pd

from tradebot.config import StrategyConfig
from tradebot.data import mt5_feed
from tradebot.execution.broker import Broker, ClosedTrade
from tradebot.journal import JournalEntry, TradeJournal
from tradebot.news.blackout import NewsCalendarGuard
from tradebot.risk.edge_guard import EdgeConfidenceGuard
from tradebot.risk.guard import RiskGuard
from tradebot.risk.position_sizing import calculate_lots
from tradebot.risk.trailing_stop import update_trailing_stop
from tradebot.strategy import indicators
from tradebot.strategy.liquidity_sweep import generate_signals

log = logging.getLogger("tradebot")


def _to_journal_entry(
    trade: ClosedTrade, pip_size: float, pip_value_per_standard_lot: float, mode: str
) -> JournalEntry:
    pip_diff = (
        (trade.exit_price - trade.entry_price) / pip_size
        if trade.direction == "long"
        else (trade.entry_price - trade.exit_price) / pip_size
    )
    pnl = pip_diff * pip_value_per_standard_lot * trade.lots

    risk = abs(trade.entry_price - trade.initial_stop)
    realized = (
        trade.exit_price - trade.entry_price
        if trade.direction == "long"
        else trade.entry_price - trade.exit_price
    )
    r_multiple = realized / risk if risk > 0 else 0.0

    return JournalEntry(
        time=dt.datetime.now(dt.timezone.utc).isoformat(),
        direction=trade.direction,
        lots=trade.lots,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        initial_stop=trade.initial_stop,
        pnl=pnl,
        r_multiple=r_multiple,
        mode=mode,
    )


class TradingBot:
    def __init__(
        self,
        config: StrategyConfig,
        broker: Broker,
        journal_path: str,
        mode: str,
        history_bars: int = 500,
        poll_seconds: int = 30,
    ) -> None:
        self.config = config
        self.broker = broker
        self.mode = mode
        self.history_bars = history_bars
        self.poll_seconds = poll_seconds
        self.symbol = config["symbol"]
        self.timeframe = config["entry_timeframe"]

        self.guard = RiskGuard(
            config.get("risk", "daily_loss_limit_pct"),
            config.get("risk", "max_concurrent_positions"),
        )
        self.journal = TradeJournal(journal_path)
        self.edge_guard = EdgeConfidenceGuard(
            min_sample_size=config.get("edge_guard", "min_sample_size", default=30),
            degradation_threshold_r=config.get("edge_guard", "degradation_threshold_r", default=0.0),
        )
        self.news_guard = NewsCalendarGuard(config)
        self._acted_on: set[pd.Timestamp] = set()
        # position_id -> initial_stop, needed by the trailing-stop calculation
        self._initial_stops: dict[str, float] = {}
        self._best_price: dict[str, float] = {}

    def _fetch_history(self) -> pd.DataFrame:
        return mt5_feed.fetch_rates(self.symbol, self.timeframe, self.history_bars)

    def _manage_open_positions(self, df: pd.DataFrame) -> None:
        atr_period = self.config.get("displacement", "atr_period")
        atr_series = indicators.atr(df, atr_period)
        latest_atr = float(atr_series.iloc[-1])
        latest_bar = df.iloc[-1]

        # Paper broker has no broker-side SL/TP order book, so exits must be
        # simulated against the latest bar. A real MT5Broker enforces SL/TP
        # on the broker's side already, so this is a no-op there.
        if hasattr(self.broker, "check_exits"):
            self.broker.check_exits(latest_bar)

        self._record_closed_trades()

        be_trigger = self.config.get("trailing_stop", "breakeven_trigger_r")
        trail_mult = self.config.get("trailing_stop", "trail_atr_multiplier")
        trailing_enabled = self.config.get("trailing_stop", "enabled", default=True)
        if not trailing_enabled:
            return

        for pos in self.broker.get_open_positions():
            initial_stop = self._initial_stops.get(pos.id, pos.stop_price)
            if pos.direction == "long":
                best = max(self._best_price.get(pos.id, pos.entry_price), latest_bar["high"])
            else:
                best = min(self._best_price.get(pos.id, pos.entry_price), latest_bar["low"])
            self._best_price[pos.id] = best

            new_stop = update_trailing_stop(
                pos.direction,
                pos.entry_price,
                initial_stop,
                pos.stop_price,
                best,
                latest_atr,
                be_trigger,
                trail_mult,
            )
            if new_stop != pos.stop_price:
                log.info("Moving stop for position %s to %.5f", pos.id, new_stop)
                self.broker.modify_stop(pos.id, new_stop)

    def _record_closed_trades(self) -> None:
        """Journal any trade that closed since the last poll.

        Covers both a paper-broker fill against a bar (check_exits, above)
        and a real broker-side SL/TP fill on MT5Broker, which happens
        without this bot ever calling close_position() itself.
        """
        if not hasattr(self.broker, "pop_recent_closes"):
            return

        pip_size = self.config.get("risk", "pip_size")
        pip_value = self.config.get("risk", "pip_value_per_standard_lot")

        for ct in self.broker.pop_recent_closes():
            self._initial_stops.pop(ct.position_id, None)
            self._best_price.pop(ct.position_id, None)
            self.journal.record(_to_journal_entry(ct, pip_size, pip_value, self.mode))

    def _maybe_open_new_signal(self, df: pd.DataFrame) -> None:
        edge_status = self.edge_guard.evaluate(self.journal.load_all())
        if not edge_status.can_trade:
            log.warning("Edge confidence guard blocking new entries: %s", edge_status.reason)
            return

        news_status = self.news_guard.evaluate(dt.datetime.now(dt.timezone.utc))
        if news_status.in_blackout:
            log.info("News calendar guard blocking new entries: %s", news_status.reason)
            return

        signals = generate_signals(df, self.config)
        if not signals:
            return

        latest_signal = signals[-1]
        latest_bar_index = len(df) - 1
        if latest_signal.entry_index != latest_bar_index:
            return  # most recent signal isn't fresh (formed on an earlier bar)
        if latest_signal.time in self._acted_on:
            return

        self._acted_on.add(latest_signal.time)

        equity = self.broker.get_equity()
        self.guard.register_equity(latest_signal.time, equity)
        open_positions = self.broker.get_open_positions()
        if not self.guard.can_open_position(len(open_positions)):
            log.info("Risk guard blocked new position at %s", latest_signal.time)
            return

        pip_size = self.config.get("risk", "pip_size")
        pip_value = self.config.get("risk", "pip_value_per_standard_lot")
        risk_pct = self.config.get("risk", "risk_per_trade_pct")
        lots = calculate_lots(equity, risk_pct, latest_signal.risk, pip_size, pip_value)

        log.info(
            "Opening %s %s lots @ %.5f (SL %.5f, TP %.5f, source=%s)",
            latest_signal.direction,
            lots,
            latest_signal.entry_price,
            latest_signal.stop_price,
            latest_signal.take_profit_price,
            latest_signal.level_source,
        )
        position = self.broker.open_position(
            latest_signal.direction,
            lots,
            latest_signal.entry_price,
            latest_signal.stop_price,
            latest_signal.take_profit_price,
        )
        self._initial_stops[position.id] = latest_signal.stop_price
        self._best_price[position.id] = latest_signal.entry_price

    def run_once(self) -> None:
        df = self._fetch_history()
        self._manage_open_positions(df)
        self._maybe_open_new_signal(df)

    def run_forever(self) -> None:
        log.info("Starting trading bot for %s on %s", self.symbol, self.timeframe)
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Error in trading loop iteration")
            time.sleep(self.poll_seconds)
