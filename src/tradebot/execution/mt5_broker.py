"""Live order execution against a real (or demo) MT5 account.

Like `tradebot.data.mt5_feed`, this only works when run on the machine where
the MT5 terminal is installed, running, and logged in -- it cannot be used
from this repository's dev container or CI. Test everything against a DEMO
account first; nothing here should touch a live account until the
backtester's results and paper-broker dry runs give you confidence.
"""
from __future__ import annotations

from tradebot.execution.broker import Position

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
        return Position(
            id=str(result.order),
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
