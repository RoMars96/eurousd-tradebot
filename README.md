# eurousd-tradebot

A EUR/USD liquidity-sweep (stop-hunt reversal) trading bot for MetaTrader 5.

**Read this before connecting to a real account.** This project targets a
well-known discretionary price-action concept (session/liquidity sweeps,
rejection, displacement). It is fully backtestable and the code here is
built to be rigorous about risk, but no automated EUR/USD strategy is
guaranteed to be profitable against real institutional flow. Treat this as
an engineering + research project first, and validate thoroughly (backtest
-> demo paper trading for weeks -> small live size) before trusting it with
real money.

## Strategy

1. **Range** -- the Asian session (00:00-07:00 UTC) high/low, and/or
   clusters of equal swing-pivot highs/lows on the entry timeframe.
2. **Sweep** -- a candle's wick pierces the level by more than
   `sweep.min_pierce_pips`.
3. **Rejection** -- within `sweep.rejection_max_bars`, a candle closes back
   inside the range.
4. **Displacement** -- within `displacement.max_bars_after_rejection` bars,
   a candle's body is >= `displacement.body_atr_multiplier` * ATR14 in the
   reversal direction.
5. **Entry** at the displacement candle's close, **stop** beyond the
   sweep's extreme wick, **take-profit** at a fixed R multiple, with an
   optional breakeven + ATR trailing stop afterward.

All parameters live in `config/strategy.yaml`.

## Project layout

```
config/strategy.yaml          strategy & risk parameters
src/tradebot/
  data/loader.py               historical OHLC CSV loader
  data/mt5_feed.py              live MT5 candle feed (Windows/MT5-terminal only)
  strategy/                     sessions, swing pivots, ATR, signal generation
  risk/                         position sizing, trailing stop, daily-loss guard
  backtest/                     bar-by-bar simulator + performance metrics
  execution/                    broker interface, paper broker, MT5 order execution
  bot.py                        live/paper trading loop
scripts/
  run_backtest.py                CLI: backtest a CSV of historical data
  run_live.py                    CLI: run live/paper against a running MT5 terminal
tests/                          pytest suite (synthetic data, no MT5 required)
```

## Important: where each part actually runs

- **Backtesting, strategy logic, tests** -- runs anywhere (this repo, CI,
  your laptop), no MT5 required.
- **Live/paper execution (`scripts/run_live.py`)** -- the `MetaTrader5`
  Python package only talks to a MetaTrader 5 terminal running on the
  *same machine* over local IPC. It cannot connect to a broker remotely.
  This means the bot must run on a Windows PC or Windows VPS that has the
  MT5 terminal installed, running, and logged in to your account. A
  cloud dev container (like the one this was built in) cannot execute
  trades.

## Getting started

```bash
pip install -e ".[dev]"          # backtesting + tests
pip install -e ".[mt5]"          # only on the Windows machine that runs MT5

pytest                           # run the test suite
```

### Get historical data (free, no Dukascopy needed)

You don't need a third-party tick-data provider. Your own broker's MT5
history is free and plenty -- most brokers carry many years of M15/M1 data
for a major pair like EURUSD. On the Windows machine with MT5 installed
and logged in to a (demo is fine) account:

```bash
python scripts/fetch_mt5_history.py --login <login> --password *** \
    --server "YourBroker-Demo" --symbol EURUSD --timeframe M15 \
    --start 2015-01-01 --end 2026-01-01 --out eurusd_m15.csv
```

This writes a CSV directly in the format `run_backtest.py` expects. (You
can also do this manually: MT5 -> View -> History Center -> EURUSD -> M15
-> Download, then right-click the chart -> "Save As".)

### Backtest against historical data

Once you have a CSV (columns `time,open,high,low,close`) -- from the script
above, an MT5 export, or any other source:

```bash
python scripts/run_backtest.py --csv path/to/eurusd_m15.csv --trades-out trades.csv
```

### Paper-trade live (no real orders)

On the Windows machine with MT5 running and logged in to a **demo**
account:

```bash
python scripts/run_live.py --mode paper --login <demo_login> --password *** \
    --server "YourBroker-Demo"
```

### Go live (real funds)

Only after you're satisfied with backtest results and a real-time paper
run:

```bash
python scripts/run_live.py --mode live --login <live_login> --password *** \
    --server "YourBroker-Live"
```

You'll be asked to type a confirmation phrase before any real order can be
placed.

## Risk defaults

- 0.5% equity risk per trade
- 1 concurrent position max
- -2% daily loss limit halts trading for the rest of the day
- Fixed 2R take-profit, breakeven stop at +1R, then ATR trailing

Tune these in `config/strategy.yaml` -- nothing here is a recommendation to
run with different (larger) numbers on a live account.
