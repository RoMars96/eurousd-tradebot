from tradebot.journal import JournalEntry
from tradebot.risk.edge_guard import EdgeConfidenceGuard


def _entry(r_multiple: float) -> JournalEntry:
    return JournalEntry(
        time="2026-01-01T00:00:00+00:00",
        direction="long",
        lots=0.1,
        entry_price=1.1000,
        exit_price=1.1000,
        initial_stop=1.0980,
        pnl=0.0,
        r_multiple=r_multiple,
        mode="paper",
    )


def test_small_sample_never_halts_even_with_all_losses():
    guard = EdgeConfidenceGuard(min_sample_size=30, degradation_threshold_r=0.0)
    entries = [_entry(-1.0) for _ in range(10)]  # 10 straight losses, but sample too small

    status = guard.evaluate(entries)

    assert status.can_trade is True
    assert status.sample_size == 10
    assert status.trailing_avg_r is None


def test_large_sample_with_negative_trailing_r_halts():
    guard = EdgeConfidenceGuard(min_sample_size=10, degradation_threshold_r=0.0)
    entries = [_entry(-1.0) for _ in range(10)]

    status = guard.evaluate(entries)

    assert status.can_trade is False
    assert status.trailing_avg_r == -1.0


def test_large_sample_with_positive_trailing_r_stays_open():
    guard = EdgeConfidenceGuard(min_sample_size=10, degradation_threshold_r=0.0)
    entries = [_entry(1.5) for _ in range(10)]

    status = guard.evaluate(entries)

    assert status.can_trade is True
    assert status.trailing_avg_r == 1.5


def test_only_trailing_window_matters_not_full_history():
    guard = EdgeConfidenceGuard(min_sample_size=5, degradation_threshold_r=0.0)
    # A rough start followed by a recovered trailing window.
    entries = [_entry(-2.0)] * 20 + [_entry(1.0)] * 5

    status = guard.evaluate(entries)

    assert status.can_trade is True
    assert status.trailing_avg_r == 1.0
