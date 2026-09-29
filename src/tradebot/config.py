"""Strategy configuration loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class UnsafeConfigError(ValueError):
    """Raised when a risk parameter exceeds its configured safety ceiling.

    Deliberately not something a CLI flag can bypass -- see PHILOSOPHY.md.
    Loosening a ceiling requires deliberately editing safety_ceilings itself
    in the YAML, not a moment of "just this once".
    """


@dataclass(frozen=True)
class StrategyConfig:
    raw: dict[str, Any]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyConfig":
        with open(path, "r") as f:
            config = cls(raw=yaml.safe_load(f))
        config.validate_safety_ceilings()
        return config

    def validate_safety_ceilings(self) -> None:
        ceilings = self.get("safety_ceilings", default={}) or {}

        risk_pct = self.get("risk", "risk_per_trade_pct")
        max_risk_pct = ceilings.get("max_risk_per_trade_pct")
        if risk_pct is not None and max_risk_pct is not None and risk_pct > max_risk_pct:
            raise UnsafeConfigError(
                f"risk.risk_per_trade_pct ({risk_pct}) exceeds "
                f"safety_ceilings.max_risk_per_trade_pct ({max_risk_pct})"
            )

        daily_loss_pct = self.get("risk", "daily_loss_limit_pct")
        max_daily_loss_pct = ceilings.get("max_daily_loss_limit_pct")
        if (
            daily_loss_pct is not None
            and max_daily_loss_pct is not None
            and daily_loss_pct > max_daily_loss_pct
        ):
            raise UnsafeConfigError(
                f"risk.daily_loss_limit_pct ({daily_loss_pct}) exceeds "
                f"safety_ceilings.max_daily_loss_limit_pct ({max_daily_loss_pct})"
            )

        max_concurrent = self.get("risk", "max_concurrent_positions")
        max_concurrent_ceiling = ceilings.get("max_concurrent_positions")
        if (
            max_concurrent is not None
            and max_concurrent_ceiling is not None
            and max_concurrent > max_concurrent_ceiling
        ):
            raise UnsafeConfigError(
                f"risk.max_concurrent_positions ({max_concurrent}) exceeds "
                f"safety_ceilings.max_concurrent_positions ({max_concurrent_ceiling})"
            )

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"


def load_default_config() -> StrategyConfig:
    return StrategyConfig.from_yaml(DEFAULT_CONFIG_PATH)
