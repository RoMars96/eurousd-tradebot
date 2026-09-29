from tradebot.journal import JournalEntry, TradeJournal


def _entry(r_multiple: float) -> JournalEntry:
    return JournalEntry(
        time="2026-01-01T00:00:00+00:00",
        direction="long",
        lots=0.1,
        entry_price=1.1000,
        exit_price=1.1020,
        initial_stop=1.0980,
        pnl=20.0,
        r_multiple=r_multiple,
        mode="paper",
    )


def test_journal_round_trips_entries(tmp_path):
    journal = TradeJournal(tmp_path / "journal.jsonl")
    assert journal.count() == 0

    journal.record(_entry(1.5))
    journal.record(_entry(-1.0))

    loaded = journal.load_all()
    assert journal.count() == 2
    assert [e.r_multiple for e in loaded] == [1.5, -1.0]


def test_journal_creates_parent_directories(tmp_path):
    nested = tmp_path / "nested" / "dir" / "journal.jsonl"
    journal = TradeJournal(nested)
    assert nested.exists()
    assert journal.load_all() == []
