"""Minimal Alpaca client for historical research data: assets, bars, news.

A free Alpaca account is enough -- a paper-only account signs up with just
an email and gets API keys. Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY.

Written against Alpaca's documented REST API (Market Data v2, news
v1beta1, Trading v2 assets). The sandbox this was built in can't reach
Alpaca, so it's tested against mocked responses only -- if a request
fails on first real use, the error message will say which endpoint.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import pandas as pd
import requests

DATA_URL = "https://data.alpaca.markets"
TRADING_URL = "https://paper-api.alpaca.markets"

_RETRY_STATUSES = {429, 500, 502, 503, 504}


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        feed: str = "sip",
        session: requests.Session | None = None,
        max_requests_per_minute: int = 180,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
    ) -> None:
        self.feed = feed
        self.session = session or requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key})
        self._min_interval = 60.0 / max_requests_per_minute
        self._last_request = 0.0
        self._sleep = sleep
        self._max_retries = max_retries

    @classmethod
    def from_env(cls, feed: str = "sip") -> "AlpacaClient":
        key_id = os.environ.get("ALPACA_API_KEY_ID")
        secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret:
            raise AlpacaError(
                "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (free paper account at alpaca.markets)"
            )
        return cls(key_id, secret, feed=feed)

    def _get(self, url: str, params: dict) -> dict | list:
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = time.monotonic()

            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                self._sleep(min(60.0, 2.0 ** attempt))
                continue
            if resp.status_code >= 400:
                raise AlpacaError(f"GET {url} failed with {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise AlpacaError(f"GET {url} failed after {self._max_retries} retries")

    def assets(self) -> list[dict]:
        """Active AND inactive US equities -- inactive ones are needed so
        stocks that later delisted (common among small caps) aren't silently
        dropped from history (survivorship bias)."""
        out: list[dict] = []
        for status in ("active", "inactive"):
            out.extend(self._get(f"{TRADING_URL}/v2/assets", {"status": status, "asset_class": "us_equity"}))
        return out

    def bars(
        self,
        symbols: list[str],
        timeframe: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        adjustment: str = "raw",
    ) -> pd.DataFrame:
        """Columns: symbol, time (UTC), open, high, low, close, volume."""
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": pd.Timestamp(start).isoformat(),
            "end": pd.Timestamp(end).isoformat(),
            "limit": 10000,
            "adjustment": adjustment,
            "feed": self.feed,
        }
        rows = []
        while True:
            payload = self._get(f"{DATA_URL}/v2/stocks/bars", params)
            for symbol, bars in (payload.get("bars") or {}).items():
                for b in bars:
                    rows.append((symbol, b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]))
            token = payload.get("next_page_token")
            if not token:
                break
            params = {**params, "page_token": token}

        df = pd.DataFrame(rows, columns=["symbol", "time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    def news(self, symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
        """Headline metadata only: created_at, headline, symbols, source."""
        params = {
            "symbols": ",".join(symbols),
            "start": pd.Timestamp(start).isoformat(),
            "end": pd.Timestamp(end).isoformat(),
            "limit": 50,
            "include_content": "false",
            "sort": "asc",
        }
        items: list[dict] = []
        while True:
            payload = self._get(f"{DATA_URL}/v1beta1/news", params)
            for n in payload.get("news") or []:
                items.append(
                    {
                        "created_at": n.get("created_at"),
                        "headline": n.get("headline", ""),
                        "symbols": n.get("symbols", []),
                        "source": n.get("source", ""),
                    }
                )
            token = payload.get("next_page_token")
            if not token:
                break
            params = {**params, "page_token": token}
        return items
