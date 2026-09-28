"""Strategy configuration loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StrategyConfig:
    raw: dict[str, Any]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyConfig":
        with open(path, "r") as f:
            return cls(raw=yaml.safe_load(f))

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
