# Philosophy

This project treats Mark Douglas's *Trading in the Zone* as its governing
reference. Not as decoration -- as the standard every design decision here
gets checked against. If a future feature request would violate one of the
principles below, that's a reason to push back on the request, not just
build it.

## The Five Fundamental Truths, and how this codebase enforces them

Douglas's claim is that consistent trading requires believing (deeply
enough to act on) five things simultaneously. A discretionary trader has to
*hold* these beliefs under pressure. A mechanical bot doesn't need to hold
a belief -- it just needs to be built so it can't violate the truth even
when "tempted" to. Here's the mapping:

| Truth | What it rules out | Where this codebase enforces it |
|---|---|---|
| **Anything can happen.** | Assuming a setup that looks right *must* work, or that a loss means something was wrong. | Every trade is sized so a loss is a routine, pre-accepted cost (`risk/position_sizing.py`), never a surprise. No code path treats a single loss as diagnostic. |
| **You don't need to know what's going to happen next to make money.** | Adding discretionary filters, news-reading, "gut feel" entries. | `strategy/liquidity_sweep.py` is 100% rule-based: sweep, rejection, displacement, or no trade. There is no code path for a human hunch to enter. |
| **There is a random distribution between wins and losses for any given set of variables that defines an edge.** | Judging the strategy from a handful of trades in either direction. | `backtest/metrics.py`'s `sufficient_sample` flag and `risk/edge_guard.py`'s `min_sample_size` gate: nothing here draws a conclusion below a configured trade count (default 30). |
| **An edge is nothing more than a higher probability of one outcome over another.** | Position sizing or risk limits that assume a trade will win. | Stops are placed and sized *before* entry (`config/strategy.yaml`'s `entry.stop_buffer_pips`, `risk.risk_per_trade_pct`) -- the system is built assuming any single trade might be the loss. |
| **Every moment in the market is unique.** | Curve-fitting to a specific historical sequence, or assuming next week repeats last week. | The strategy's parameters are levels/ATR-relative, not fitted to specific price levels or dates; nothing in the codebase hardcodes a historical outcome as a rule. |

## Rules of engagement

These are the operating rules that follow from the truths above. They're
enforced in code where practical, and stated plainly where they can't be:

1. **Judge the system over a large sample, never a single trade.**
   `EdgeConfidenceGuard` (`risk/edge_guard.py`) will not halt trading below
   `edge_guard.min_sample_size` closed trades, in either direction. A
   losing streak inside that window is not evidence of anything -- it's
   exactly what a random distribution predicts.

2. **Risk is defined before entry and never renegotiated mid-trade.**
   Once a position is open, the only thing allowed to move its stop is the
   pre-configured trailing-stop rule (`risk/trailing_stop.py`). There is no
   manual "close early" or "move the stop because I'm nervous" code path in
   the live bot -- a trade runs to its predefined stop or take-profit.

3. **The bot governs its own graduation, not a gut feeling.**
   `scripts/run_live.py --mode live` will not start until the paper trading
   journal shows `edge_guard.min_paper_trades_before_live` closed trades.
   This is a hard gate with no override flag. "I feel ready" is not a
   parameter this system accepts.

4. **A degraded edge pauses new entries automatically, and un-pauses
   automatically.** If the trailing-window average R-multiple drops below
   `edge_guard.degradation_threshold_r`, the bot stops opening new trades
   on its own. It resumes on its own once the trailing window recovers. No
   person decides either transition.

5. **Impulsive parameter changes can't silently slip through.**
   `config/strategy.yaml`'s `safety_ceilings` section is checked at config
   load time (`config.py`'s `validate_safety_ceilings`); exceeding a
   ceiling raises `UnsafeConfigError` rather than starting the bot. Loosening
   a ceiling requires deliberately editing the ceiling itself -- not just
   the parameter it caps -- which is meant to add friction to exactly the
   kind of decision that gets made in a bad moment.

6. **Backtest and live metrics always report sample size alongside the
   numbers.** A win rate or expectancy figure without its trade count is
   close to meaningless per truth #3 above; `run_backtest.py` prints an
   explicit warning whenever `total_trades < min_sample_size`.

## What this does *not* claim

Trading in the Zone is a book about trading psychology, not a guarantee of
profitability. Encoding its principles into this bot's guardrails makes the
system *consistent* -- it removes the ways a human would sabotage a valid
edge through fear, hope, or impatience. It does not make the underlying
liquidity-sweep strategy profitable by itself. That's still an empirical
question the backtests (over a sufficient sample) have to answer.
