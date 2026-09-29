"""Runs a hypothesis through the full validation gauntlet and renders a verdict.

Steps, in order:
1. Seal the last `holdout_fraction` of the data. Nothing below looks at it.
2. Evaluate every parameter combination on the research period and log
   each one to the research log (the multiple-testing count).
3. Walk-forward: pick parameters on the past, score on the future.
4. Significance: sign-flip test on the out-of-sample trades, plus a
   stricter test on the final configuration against a Bonferroni-corrected
   threshold (random-timing null for intraday hypotheses).
5. Robustness: does the idea work across neighbouring parameters, or only
   at one lucky setting?
6. Only if asked (--reveal-holdout): score the final configuration on the
   sealed data, once.

The verdict is PASS only if every check passes. Anything else is NO EDGE.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradebot.config import StrategyConfig
from tradebot.research import evaluation as ev
from tradebot.research.hypotheses import carry as carry_h
from tradebot.research.hypotheses import session_open as session_h
from tradebot.research.log import ResearchLog
from tradebot.research.walk_forward import Candidate, WalkForwardResult, select_best, walk_forward


@dataclass
class ResearchReport:
    hypothesis: str
    data_label: str
    research_start: pd.Timestamp
    holdout_start: pd.Timestamp
    grid: list[tuple[dict, ev.Summary]]
    configs_ever_tested: int
    bonferroni_alpha: float
    significance: float
    walk_forward: WalkForwardResult
    oos_summary: ev.Summary
    oos_p: float
    final_params: dict | None
    final_summary: ev.Summary | None
    final_p: float | None
    final_p_label: str
    family_fraction_positive: float | None
    checks: list[tuple[str, bool]] = field(default_factory=list)
    benchmark_summary: ev.Summary | None = None
    holdout_summary: ev.Summary | None = None
    holdout_p: float | None = None
    holdout_previously_revealed: bool = False

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok in self.checks)


def _split_time(index: pd.DatetimeIndex, holdout_fraction: float) -> pd.Timestamp:
    return index[int(len(index) * (1.0 - holdout_fraction))]


def _research_part(trades: pd.DataFrame, holdout_start: pd.Timestamp) -> pd.DataFrame:
    return trades.loc[trades["exit_time"] < holdout_start]


def _holdout_part(trades: pd.DataFrame, holdout_start: pd.Timestamp) -> pd.DataFrame:
    return trades.loc[trades.index >= holdout_start]


def _family_fraction_positive(grid: list[tuple[dict, ev.Summary]], final: dict, family_key: str) -> float | None:
    family = [s for p, s in grid if p.get(family_key) == final.get(family_key) and s.n > 0]
    if not family:
        return None
    return sum(1 for s in family if s.mean > 0) / len(family)


def _finish(
    *,
    hypothesis: str,
    data_label: str,
    candidates: list[Candidate],
    research_start: pd.Timestamp,
    holdout_start: pd.Timestamp,
    section: dict,
    research_cfg: StrategyConfig,
    log: ResearchLog,
    rng: np.random.Generator,
    final_p_fn,
    final_p_label: str,
    family_key: str,
    reveal_holdout: bool,
    benchmark: pd.DataFrame | None = None,
) -> ResearchReport:
    n_perm = research_cfg.get("research", "permutations", default=1000)
    significance = research_cfg.get("research", "significance", default=0.05)
    n_folds = research_cfg.get("research", "walk_forward_folds", default=5)
    min_trades = section.get("min_trades_per_fold", 20)

    research_candidates = [
        Candidate(c.params, _research_part(c.trades, holdout_start)) for c in candidates
    ]

    grid = []
    for c in research_candidates:
        s = ev.summarize(c.trades["ret"])
        grid.append((c.params, s))
        log.record(hypothesis, c.params, data_label, s)

    configs_ever_tested = max(1, log.unique_configs())
    bonferroni_alpha = significance / configs_ever_tested

    wf = walk_forward(research_candidates, research_start, holdout_start, n_folds, min_trades)
    oos_summary = ev.summarize(wf.oos_trades["ret"])
    oos_p = ev.sign_flip_pvalue(wf.oos_trades["ret"], n_perm, rng)

    best = select_best(research_candidates, research_start, holdout_start, min_trades)
    final_params = final_summary = final_p = family_fraction = None
    if best is not None:
        final_candidate, final_summary = best
        final_params = final_candidate.params
        # A permutation p-value can't go below 1/(n_perm+1); make sure the
        # corrected threshold is reachable at all.
        final_perms = max(n_perm, int(np.ceil(2.0 / bonferroni_alpha)))
        final_p = final_p_fn(final_candidate, final_perms)
        family_fraction = _family_fraction_positive(grid, final_params, family_key)

    checks = [
        (f"enough out-of-sample trades (>= {min_trades})", oos_summary.n >= min_trades),
        ("out-of-sample mean net return > 0", oos_summary.mean > 0),
        (f"out-of-sample p < {significance}", oos_p < significance),
        (
            f"final config {final_p_label} p < Bonferroni {bonferroni_alpha:.4g}"
            f" ({configs_ever_tested} configs ever tested)",
            final_p is not None and final_p < bonferroni_alpha,
        ),
        (
            "robust: >= 2/3 of neighbouring configs also profitable",
            family_fraction is not None and family_fraction >= 2 / 3,
        ),
    ]

    report = ResearchReport(
        hypothesis=hypothesis,
        data_label=data_label,
        research_start=research_start,
        holdout_start=holdout_start,
        grid=grid,
        configs_ever_tested=configs_ever_tested,
        bonferroni_alpha=bonferroni_alpha,
        significance=significance,
        walk_forward=wf,
        oos_summary=oos_summary,
        oos_p=oos_p,
        final_params=final_params,
        final_summary=final_summary,
        final_p=final_p,
        final_p_label=final_p_label,
        family_fraction_positive=family_fraction,
        checks=checks,
    )

    if benchmark is not None:
        report.benchmark_summary = ev.summarize(_research_part(benchmark, holdout_start)["ret"])

    if reveal_holdout and final_params is not None:
        report.holdout_previously_revealed = log.holdout_revealed(hypothesis, data_label)
        final_full = next(c for c in candidates if c.params == final_params)
        holdout = _holdout_part(final_full.trades, holdout_start)
        report.holdout_summary = ev.summarize(holdout["ret"])
        report.holdout_p = ev.sign_flip_pvalue(holdout["ret"], n_perm, rng)
        log.record_event(
            "holdout_revealed",
            {"hypothesis": hypothesis, "data": data_label, "params": final_params},
        )

    return report


def run_session_open(
    df: pd.DataFrame,
    config: StrategyConfig,
    data_label: str,
    log: ResearchLog,
    rng: np.random.Generator,
    reveal_holdout: bool = False,
) -> ResearchReport:
    section = config.get("research", "session_open", default={}) or {}
    pip_size = config.get("risk", "pip_size")
    cost = config.get("research", "cost_pips", default=0.0)
    asian = (config.get("sessions", "asian", "start_hour"), config.get("sessions", "asian", "end_hour"))
    london = (config.get("sessions", "london", "start_hour"), config.get("sessions", "london", "end_hour"))
    holdout_start = _split_time(df.index, config.get("research", "holdout_fraction", default=0.2))
    close = df["close"]

    candidates: list[Candidate] = []
    event_cache: dict[tuple, pd.Series] = {}
    for variant in section.get("variants", ["reversal", "breakout"]):
        for pierce in section.get("pierce_pips", [0, 5, 10]):
            events = session_h.london_open_events(df, variant, pierce, pip_size, asian, london)
            event_cache[(variant, pierce)] = events
            for horizon in section.get("horizon_bars", [4, 8, 16]):
                params = {"variant": variant, "pierce_pips": pierce, "horizon_bars": horizon}
                trades = ev.event_trades(close, events, horizon, pip_size, cost)
                candidates.append(Candidate(params, trades))

    holdout_pos = df.index.get_indexer([holdout_start])[0]
    eligible = session_h.london_window_positions(df, london)

    def timing_p(candidate: Candidate, n_perm: int) -> float:
        p = candidate.params
        events = event_cache[(p["variant"], p["pierce_pips"])]
        events = events[events.index.isin(candidate.trades.index)]
        research_eligible = eligible[eligible + p["horizon_bars"] < holdout_pos]
        return ev.random_timing_pvalue(
            close, events, p["horizon_bars"], pip_size, cost, research_eligible, n_perm, rng
        )

    return _finish(
        hypothesis="session_open",
        data_label=data_label,
        candidates=candidates,
        research_start=df.index[0],
        holdout_start=holdout_start,
        section=section,
        research_cfg=config,
        log=log,
        rng=rng,
        final_p_fn=timing_p,
        final_p_label="random-timing",
        family_key="variant",
        reveal_holdout=reveal_holdout,
    )


def run_carry(
    ohlc: pd.DataFrame,
    rates: pd.DataFrame,
    config: StrategyConfig,
    data_label: str,
    log: ResearchLog,
    rng: np.random.Generator,
    reveal_holdout: bool = False,
) -> ResearchReport:
    section = config.get("research", "carry", default={}) or {}
    pip_size = config.get("risk", "pip_size")
    cost = config.get("research", "cost_pips", default=0.0)
    swap_eff = section.get("swap_efficiency", 0.6)

    close_me = carry_h.month_end_close(ohlc)
    diff = carry_h.rate_differential(rates, section.get("publication_lag_months", 1))
    common = close_me.index.intersection(diff.index)
    if len(common) < 24:
        raise ValueError(
            f"only {len(common)} overlapping months of price and rate data; need at least 24"
        )
    close_me, diff = close_me.loc[common], diff.loc[common]
    holdout_start = _split_time(close_me.index, config.get("research", "holdout_fraction", default=0.2))

    candidates: list[Candidate] = []
    for min_diff in section.get("level_min_diff", [0.0, 0.5, 1.0]):
        events = carry_h.level_events(diff, min_diff)
        trades = carry_h.carry_trades(close_me, diff, events, pip_size, cost, swap_eff)
        candidates.append(Candidate({"variant": "level", "min_diff": min_diff}, trades))
    for lookback in section.get("momentum_lookback_months", [1, 3, 6]):
        events = carry_h.momentum_events(diff, lookback)
        trades = carry_h.carry_trades(close_me, diff, events, pip_size, cost, swap_eff)
        candidates.append(Candidate({"variant": "momentum", "lookback_months": lookback}, trades))

    always_long = pd.Series(1, index=close_me.index, dtype="int64")
    benchmark = carry_h.carry_trades(close_me, diff, always_long, pip_size, cost, swap_eff)

    def sign_flip_p(candidate: Candidate, n_perm: int) -> float:
        return ev.sign_flip_pvalue(candidate.trades["ret"], n_perm, rng)

    return _finish(
        hypothesis="carry",
        data_label=data_label,
        candidates=candidates,
        research_start=close_me.index[0],
        holdout_start=holdout_start,
        section=section,
        research_cfg=config,
        log=log,
        rng=rng,
        final_p_fn=sign_flip_p,
        final_p_label="sign-flip",
        family_key="variant",
        reveal_holdout=reveal_holdout,
        benchmark=benchmark,
    )


def _fmt_summary(s: ev.Summary) -> str:
    return (
        f"n={s.n:<5} mean={s.mean:+8.2f} pips  t={s.t_stat:+5.2f}  "
        f"hit={s.hit_rate * 100:5.1f}%  total={s.total:+10.1f} pips"
    )


def format_report(r: ResearchReport) -> str:
    lines = [
        f"=== {r.hypothesis} on {r.data_label} ===",
        f"Research period: {r.research_start} -> {r.holdout_start} (holdout sealed after this)",
        "",
        "Parameter grid (research period, net of costs):",
    ]
    for params, s in sorted(r.grid, key=lambda x: x[1].t_stat, reverse=True):
        lines.append(f"  {str(params):<60} {_fmt_summary(s)}")

    lines += ["", "Walk-forward (parameters chosen on the past, scored on the future):"]
    for f in r.walk_forward.folds:
        label = f"  {f.test_start.date()} -> {f.test_end.date()}: "
        if f.chosen_params is None:
            lines.append(label + "no configuration had enough trades to choose from")
        else:
            lines.append(label + f"{f.chosen_params}  {_fmt_summary(ev.summarize(f.test_trades['ret']))}")
    lines.append(f"  Out-of-sample total: {_fmt_summary(r.oos_summary)}  p={r.oos_p:.4f}")

    if r.benchmark_summary is not None:
        lines.append(f"  Benchmark (always long + carry): {_fmt_summary(r.benchmark_summary)}")

    lines += ["", f"Final configuration (best on full research period): {r.final_params}"]
    if r.final_summary is not None:
        lines.append(f"  {_fmt_summary(r.final_summary)}  {r.final_p_label} p={r.final_p:.4f}")
    if r.family_fraction_positive is not None:
        lines.append(f"  Neighbouring configs profitable: {r.family_fraction_positive * 100:.0f}%")

    lines += ["", "Checks:"]
    for label, ok in r.checks:
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    lines.append("")
    if r.passed:
        lines.append(
            "VERDICT: CANDIDATE EDGE. Survived every check on the research period. "
            "Next: --reveal-holdout (once), then paper trading."
        )
    else:
        lines.append(
            "VERDICT: NO EDGE FOUND. Don't trade this. Don't tweak parameters until it "
            "passes either -- that's how false edges get manufactured."
        )

    if r.holdout_summary is not None:
        lines += ["", "HOLDOUT (sealed data, final configuration only):"]
        if r.holdout_previously_revealed:
            lines.append(
                "  WARNING: this holdout was already revealed for this hypothesis/data. "
                "It is no longer an unbiased test."
            )
        lines.append(f"  {_fmt_summary(r.holdout_summary)}  p={r.holdout_p:.4f}")
    return "\n".join(lines)
