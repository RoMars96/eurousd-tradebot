"""Live order execution against a real (or demo) MT5 account.

Like `tradebot.data.mt5_feed`, this only works when run on the machine where
the MT5 terminal is installed, running, and logged in -- it cannot be used
from this repository's dev container or CI. Test everything against a DEMO
account first; nothing here should touch a live account until the
backtester's results and paper-broker dry runs give you confidence.
"""
from __future__ import annotations

from tradebot.execution.broker import ClosedTrade, Position

try:
    import MetaTrader5 as mt5
except ImportError as exc:  # pragma: no cover - exercised only off-Windows
    mt5 = None
    _import_error = exc
else:
    _import_error = None


def _require_mt5() -> None:
    if mt5 is None:
        raise ImportError(
            "MetaTrader5 package is not usable in this environment. It requires "
            "a running MT5 terminal on Windows (or Wine). Install with "
            "`pip install tradebot[mt5]` on the machine that runs the terminal."
        ) from _import_error


_DIRECTION_TO_ORDER_TYPE = {
    "long": "ORDER_TYPE_BUY",
    "short": "ORDER_TYPE_SELL",
}


class MT5Broker:
    def __init__(self, symbol: str, magic_number: int = 20260928) -> None:
        _require_mt5()
        self.symbol = symbol
        self.magic_number = magic_number
        # Positions we opened, keyed by ticket id, so a later disappearance
        # (broker-side SL/TP fill) can be reported to pop_recent_closes().
        self._tracked: dict[str, dict] = {}

    def get_equity(self) -> float:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
        return float(info.equity)

    def get_open_positions(self) -> list[Position]:
        positions = mt5.positions_get(symbol=self.symbol) or ()
        result = []
        for p in positions:
            direction = "long" if p.type == mt5.POSITION_TYPE_BUY else "short"
            result.append(
                Position(
                    id=str(p.ticket),
                    direction=direction,
                    lots=p.volume,
                    entry_price=p.price_open,
                    stop_price=p.sl,
                    take_profit_price=p.tp,
                )
            )
        return result

    def open_position(
        self,
        direction: str,
        lots: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
    ) -> Position:
        order_type = getattr(mt5, _DIRECTION_TO_ORDER_TYPE[direction])
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": lots,
            "type": order_type,
            "sl": stop_price,
            "tp": take_profit_price,
            "magic": self.magic_number,
            "comment": "liquidity-sweep-bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order_send failed: {result}")
        position_id = str(result.order)
        self._tracked[position_id] = {
            "direction": direction,
            "lots": lots,
            "entry_price": result.price,
            "initial_stop": stop_price,
        }
        return Position(
            id=position_id,
            direction=direction,
            lots=lots,
            entry_price=result.price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    def modify_stop(self, position_id: str, new_stop_price: float) -> None:
        positions = mt5.positions_get(ticket=int(position_id))
        if not positions:
            raise RuntimeError(f"MT5 position {position_id} not found")
        position = positions[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": position.ticket,
            "sl": new_stop_price,
            "tp": position.tp,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 SL/TP modify failed: {result}")

    def close_position(self, position_id: str, exit_price: float) -> None:
        positions = mt5.positions_get(ticket=int(position_id))
        if not positions:
            return
        position = positions[0]
        opposite_type = (
            mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": position.volume,
            "type": opposite_type,
            "position": position.ticket,
            "magic": self.magic_number,
            "comment": "liquidity-sweep-bot-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 close order failed: {result}")
        self._tracked.pop(position_id, None)

    def _lookup_exit_price(self, position_id: str) -> float | None:
        try:
            deals = mt5.history_deals_get(position=int(position_id))
        except Exception:
            return None
        if not deals:
            return None
        closing_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not closing_deals:
            return None
        return float(closing_deals[-1].price)

    def pop_recent_closes(self) -> list[ClosedTrade]:
        """Report trades this broker opened that are no longer open.

        Covers broker-side SL/TP fills, which happen without any call back
        into this class. Best-effort: if the closing deal can't be found in
        MT5's history (e.g. called too soon after the fill), the trade is
        skipped this round and picked up on a later poll once it appears.
        """
        current_ids = {p.id for p in self.get_open_positions()}
        closed_ids = [pid for pid in self._tracked if pid not in current_ids]

        closes: list[ClosedTrade] = []
        for position_id in closed_ids:
            exit_price = self._lookup_exit_price(position_id)
            if exit_price is None:
                continue
            info = self._tracked.pop(position_id)
            closes.append(
                ClosedTrade(
                    position_id=position_id,
                    direction=info["direction"],
                    lots=info["lots"],
                    entry_price=info["entry_price"],
                    exit_price=exit_price,
                    initial_stop=info["initial_stop"],
                )
            )
        return closes
