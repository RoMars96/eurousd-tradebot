#!/usr/bin/env python3
"""Merge two single-series interest-rate CSVs into the `date,uk,jp` file
that `research.py carry --rates` expects.

Built for FRED downloads (fred.stlouisfed.org -> series page -> Download
-> CSV), which have a date column and one value column, with "." for
missing values. Suggested series, monthly, percent:
    UK:    IRSTCI01GBM156N   (call money / interbank rate)
    Japan: IRSTCI01JPM156N
Check each series' last observation is recent before relying on it.

Any other source works too if each file is `<date>,<rate in percent>`.

Usage:
    python scripts/make_rates_csv.py --uk IRSTCI01GBM156N.csv \
        --jp IRSTCI01JPM156N.csv --out ~/Downloads/uk_jp_rates.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def read_series(path: str | Path, name: str) -> pd.Series:
    df = pd.read_csv(path)
    if df.shape[1] < 2:
        raise ValueError(f"{path}: expected a date column and a value column")
    dates = pd.to_datetime(df.iloc[:, 0])
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    return pd.Series(values.to_numpy(), index=dates, name=name).dropna().sort_index()


def merge_rates(uk: pd.Series, jp: pd.Series) -> pd.DataFrame:
    merged = pd.concat([uk, jp], axis=1, sort=True).ffill().dropna()
    merged.index.name = "date"
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uk", required=True)
    parser.add_argument("--jp", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    merged = merge_rates(read_series(args.uk, "uk"), read_series(args.jp, "jp"))
    out = Path(args.out).expanduser()
    merged.to_csv(out, date_format="%Y-%m-%d")
    print(f"Wrote {len(merged)} rows, {merged.index[0].date()} -> {merged.index[-1].date()}, to {out}")
    print(f"Latest: uk={merged['uk'].iloc[-1]}%  jp={merged['jp'].iloc[-1]}%  (sanity-check these against today's policy rates)")


if __name__ == "__main__":
    main()
