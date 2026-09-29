import copy

import numpy as np
import pandas as pd
import pytest
from research_fixtures import synthetic_gbpjpy_m15

from tradebot.config import StrategyConfig
from tradebot.data.loader import detect_mt5_export, load_ohlc_csv, load_ohlc_for_research
from tradebot.research import evaluation as ev
from tradebot.research.hypotheses import carry as carry_h
from tradebot.research.hypotheses.session_open import london_open_events
from tradebot.research.log import ResearchLog
from tradebot.research.runner import run_carry, run_session_open
from tradebot.research.walk_forward import Candidate, walk_forward


def _gbpjpy_config(tmp_path, **research_overrides) -> StrategyConfig:
    raw = copy.deepcopy(StrategyConfig.from_yaml("config/gbpjpy.yaml").raw)
    raw["research"]["log_path"] = str(tmp_path / "log.jsonl")
    raw["research"].update(research_overrides)
    return StrategyConfig(raw=raw)


# --- evaluation -------------------------------------------------------------

def test_event_trades_long_and_short_net_of_cost():
    idx = pd.date_range("2026-01-01", periods=5, freq="15min", tz="UTC")
    close = pd.Series([100.00, 100.10, 100.20, 100.30, 100.40], index=idx)
    events = pd.Series([1, -1], index=[idx[0], idx[1]])

    trades = ev.event_trades(close, events, horizon=2, pip_size=0.01, cost_pips=3.0)

    assert trades.loc[idx[0], "ret"] == pytest.approx(20.0 - 3.0)
    assert trades.loc[idx[1], "ret"] == pytest.approx(-20.0 - 3.0)
    assert trades.loc[idx[0], "exit_time"] == idx[2]


def test_event_trades_drops_events_without_enough_future_bars():
    idx = pd.date_range("2026-01-01", periods=3, freq="15min", tz="UTC")
    close = pd.Series([1.0, 1.0, 1.0], index=idx)
    trades = ev.event_trades(close, pd.Series([1], index=[idx[2]]), 1, 0.01, 0.0)
    assert trades.empty


def test_sign_flip_pvalue_separates_edge_from_noise():
    rng = np.random.default_rng(0)
    edge = pd.Series(rng.normal(5.0, 10.0, 300))
    noise = pd.Series(rng.normal(0.0, 10.0, 300))
    assert ev.sign_flip_pvalue(edge, 500, rng) < 0.01
    assert ev.sign_flip_pvalue(noise, 500, rng) > 0.05


# --- walk-forward -----------------------------------------------------------

def _trades(times, rets):
    idx = pd.DatetimeIndex(times)
    return pd.DataFrame({"ret": rets, "exit_time": idx + pd.Timedelta(hours=1)}, index=idx)


def test_walk_forward_chooses_on_past_and_scores_on_future():
    times = pd.date_range("2026-01-01", periods=600, freq="12h", tz="UTC")
    good = Candidate({"name": "good"}, _trades(times, np.full(600, 5.0)))
    bad = Candidate({"name": "bad"}, _trades(times, np.full(600, -5.0)))

    result = walk_forward([bad, good], times[0], times[-1], n_folds=3, min_trades=10)

    assert all(f.chosen_params == {"name": "good"} for f in result.folds)
    assert (result.oos_trades["ret"] == 5.0).all()
    # nothing from the first (train-only) chunk may appear out of sample
    assert result.oos_trades.index.min() >= result.folds[0].test_start


def test_walk_forward_purges_trades_whose_outcome_crosses_the_window():
    idx = pd.DatetimeIndex(["2026-01-01", "2026-01-02"], tz="UTC")
    trades = pd.DataFrame(
        {"ret": [1.0, 1.0], "exit_time": [idx[0] + pd.Timedelta(days=30), idx[1] + pd.Timedelta(hours=1)]},
        index=idx,
    )
    result = walk_forward(
        [Candidate({}, trades)], idx[0], idx[0] + pd.Timedelta(days=3), n_folds=2, min_trades=1
    )
    assert idx[0] not in result.oos_trades.index


# --- research log -----------------------------------------------------------

def test_research_log_counts_unique_configs_across_runs(tmp_path):
    log = ResearchLog(tmp_path / "log.jsonl")
    s = ev.Summary(1, 0.0, 0.0, 0.0, 0.0, 0.0)
    log.record("h", {"a": 1}, "data.csv", s)
    log.record("h", {"a": 1}, "data.csv", s)  # same config re-run: not a new test
    log.record("h", {"a": 2}, "data.csv", s)
    log.record("h", {"a": 1}, "other.csv", s)  # same config, different data: a new test

    assert log.unique_configs() == 3
    assert not log.holdout_revealed("h", "data.csv")
    log.record_event("holdout_revealed", {"hypothesis": "h", "data": "data.csv"})
    assert log.holdout_revealed("h", "data.csv")


# --- hypotheses -------------------------------------------------------------

def _one_day(london_bars):
    """Flat Asian range 190.00-190.20, then the given London (h, l, c) bars."""
    rows = []
    day = pd.Timestamp("2026-01-05", tz="UTC")
    for i in range(28):
        rows.append((day + pd.Timedelta(minutes=15 * i), 190.10, 190.20, 190.00, 190.10))
    for j, (h, l, c) in enumerate(london_bars):
        rows.append((day + pd.Timedelta(hours=7, minutes=15 * j), 190.10, h, l, c))
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")


def test_london_open_reversal_after_low_sweep_goes_long():
    df = _one_day([(190.10, 189.80, 189.85), (190.10, 189.85, 190.05)])  # pierce low, close back in
    events = london_open_events(df, "reversal", pierce_pips=5, pip_size=0.01)
    assert list(events) == [1]
    assert events.index[0].hour == 7 and events.index[0].minute == 15


def test_london_open_breakout_after_high_pierce_goes_long():
    df = _one_day([(190.40, 190.10, 190.35)])
    events = london_open_events(df, "breakout", pierce_pips=5, pip_size=0.01)
    assert list(events) == [1]


def test_london_open_skips_ambiguous_outside_bar():
    df = _one_day([(190.40, 189.80, 190.10)])  # pierces both sides at once
    assert london_open_events(df, "reversal", 5, 0.01).empty


def test_carry_events_and_accrual_signs():
    idx = pd.date_range("2020-01-31", periods=4, freq="ME", tz="UTC")
    diff = pd.Series([2.0, -2.0, 0.2, 3.0], index=idx)

    level = carry_h.level_events(diff, min_diff=0.5)
    assert list(level) == [1, -1, 1] and idx[2] not in level.index

    momentum = carry_h.momentum_events(diff, lookback=1)
    assert list(momentum) == [-1, 1, 1]

    close = pd.Series([150.0] * 4, index=idx)  # flat price: return is carry minus cost only
    trades = carry_h.carry_trades(close, diff, level, 0.01, cost_pips=0.0, swap_efficiency=0.5)
    # long with +2% differential: 150 * 0.02/12 = 0.25 JPY = 25 pips, half passed on by broker
    assert trades.loc[idx[0], "ret"] == pytest.approx(12.5)
    # short with -2% differential also earns positive carry
    assert trades.loc[idx[1], "ret"] == pytest.approx(12.5)


# --- MT5 export loading -----------------------------------------------------

def test_mt5_native_export_is_parsed_and_broker_time_corrected(tmp_path):
    path = tmp_path / "GBPJPY_M15.csv"
    path.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2026.01.15\t10:00:00\t190.10\t190.20\t190.00\t190.15\t120\t0\t12\n"
        "2026.01.15\t10:15:00\t190.15\t190.25\t190.05\t190.20\t130\t0\t12\n"
    )
    assert detect_mt5_export(path)
    raw = load_ohlc_csv(path)
    assert list(raw.columns) == ["open", "high", "low", "close", "volume"]
    assert raw.index[0] == pd.Timestamp("2026-01-15 10:00", tz="UTC")

    config = StrategyConfig.from_yaml("config/gbpjpy.yaml")
    corrected, was_corrected = load_ohlc_for_research(path, config)
    assert was_corrected
    assert corrected.index[0] == pd.Timestamp("2026-01-15 08:00", tz="UTC")  # GMT+2 in January


def test_dukascopy_node_csv_with_epoch_ms_timestamps(tmp_path):
    path = tmp_path / "gbpjpy-m15-bid.csv"
    path.write_text(
        "timestamp,open,high,low,close\n"
        "1736899200000,190.1,190.2,190.0,190.15\n"  # 2025-01-15 00:00 UTC
        "1736900100000,190.15,190.25,190.05,190.2\n"
    )
    config = StrategyConfig.from_yaml("config/gbpjpy.yaml")
    df, was_corrected = load_ohlc_for_research(path, config)
    assert not was_corrected  # already UTC, no broker-time shift
    assert df.index[0] == pd.Timestamp("2025-01-15 00:00", tz="UTC")
    assert df.index[1] - df.index[0] == pd.Timedelta(minutes=15)


# --- the pipeline itself ----------------------------------------------------

def test_pipeline_finds_no_edge_in_pure_noise(tmp_path):
    config = _gbpjpy_config(tmp_path, permutations=200)
    df = synthetic_gbpjpy_m15(n_days=520, seed=3)
    report = run_session_open(df, config, "noise", ResearchLog(tmp_path / "log.jsonl"), np.random.default_rng(0))
    assert not report.passed


def test_pipeline_detects_a_planted_edge(tmp_path):
    config = _gbpjpy_config(tmp_path, permutations=200)
    df = synthetic_gbpjpy_m15(n_days=520, seed=3, planted_edge_pips_per_bar=1.5)
    report = run_session_open(df, config, "planted", ResearchLog(tmp_path / "log.jsonl"), np.random.default_rng(0))
    assert report.passed
    assert report.final_params["variant"] == "reversal"


def test_carry_pipeline_runs_and_rejects_unrelated_rates(tmp_path):
    config = _gbpjpy_config(tmp_path, permutations=200)
    rng = np.random.default_rng(5)
    days = pd.bdate_range("2005-01-03", "2024-12-31", tz="UTC")
    close = 150.0 + np.cumsum(rng.normal(0, 0.8, len(days)))
    ohlc = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=days)
    months = pd.date_range("2005-01-31", "2024-12-31", freq="ME", tz="UTC")
    rates = pd.DataFrame(
        {"uk": np.cumsum(rng.normal(0, 0.2, len(months))), "jp": np.zeros(len(months))}, index=months
    )

    report = run_carry(ohlc, rates, config, "synthetic", ResearchLog(tmp_path / "log.jsonl"), np.random.default_rng(0))

    assert report.benchmark_summary is not None
    assert len(report.grid) == 6
    assert not report.passed
