import pytest

from tradebot.config import StrategyConfig, UnsafeConfigError


def _config(risk_per_trade_pct=0.5, daily_loss_limit_pct=2.0, max_concurrent_positions=1):
    return StrategyConfig(
        raw={
            "risk": {
                "risk_per_trade_pct": risk_per_trade_pct,
                "daily_loss_limit_pct": daily_loss_limit_pct,
                "max_concurrent_positions": max_concurrent_positions,
            },
            "safety_ceilings": {
                "max_risk_per_trade_pct": 2.0,
                "max_daily_loss_limit_pct": 5.0,
                "max_concurrent_positions": 3,
            },
        }
    )


def test_config_within_ceilings_is_fine():
    config = _config()
    config.validate_safety_ceilings()  # should not raise


def test_risk_per_trade_over_ceiling_raises():
    config = _config(risk_per_trade_pct=5.0)
    with pytest.raises(UnsafeConfigError):
        config.validate_safety_ceilings()


def test_daily_loss_limit_over_ceiling_raises():
    config = _config(daily_loss_limit_pct=10.0)
    with pytest.raises(UnsafeConfigError):
        config.validate_safety_ceilings()


def test_max_concurrent_positions_over_ceiling_raises():
    config = _config(max_concurrent_positions=10)
    with pytest.raises(UnsafeConfigError):
        config.validate_safety_ceilings()


def test_default_strategy_yaml_passes_its_own_ceilings():
    from tradebot.config import load_default_config

    load_default_config()  # raises on failure; from_yaml already validates
