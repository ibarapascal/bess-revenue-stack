"""
Elexon Insights API client (GB electricity market).

No API key required — verified 2026-07-28 against the live endpoints. Existing
third-party wrappers (ElexonDataPortal etc.) are unmaintained, so this module is
deliberately dependency-light and self-contained.

Datasets used here:
  MID     Market Index Data — half-hourly reference prices from the GB power
          exchanges (APXMIDP = EPEX/APX, N2EXMIDP = Nord Pool). This is the
          wholesale price series an arbitrage model trades against.
  DISEBSP System prices (imbalance) — settlement buy/sell price per period.

Everything is cached to parquet on first fetch; re-runs are offline.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
CACHE = Path(__file__).resolve().parents[3] / "data" / "cache"
UA = {"User-Agent": "bess-revenue-stack/0.1 (research)"}


def _get(path: str, params: dict, retries: int = 4) -> dict:
    url = f"{BASE}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after {retries} attempts: {url}")


def _daterange(start: date, end: date, step_days: int):
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=step_days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def market_index(start: date, end: date, provider: str = "APXMIDP",
                 refresh: bool = False) -> pd.DataFrame:
    """Half-hourly wholesale reference price, £/MWh.

    Returns columns: start_time (UTC), settlement_date, settlement_period,
    price, volume. One row per settlement period.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / f"mid_{provider}_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
    if key.exists() and not refresh:
        return pd.read_parquet(key)

    frames = []
    for a, b in _daterange(start, end, step_days=7):
        js = _get("/balancing/pricing/market-index", {
            "from": f"{a:%Y-%m-%d}T00:00Z",
            "to": f"{b + timedelta(days=1):%Y-%m-%d}T00:00Z",
        })
        rows = js.get("data", [])
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("no MID data returned")

    df = pd.concat(frames, ignore_index=True)
    df = df[df.dataProvider == provider].copy()
    df["start_time"] = pd.to_datetime(df.startTime, utc=True)
    df = (df.rename(columns={"settlementDate": "settlement_date",
                             "settlementPeriod": "settlement_period"})
            [["start_time", "settlement_date", "settlement_period", "price", "volume"]]
            .drop_duplicates(subset=["start_time"])
            .sort_values("start_time")
            .reset_index(drop=True))
    df.to_parquet(key, index=False)
    return df


def system_prices(start: date, end: date, refresh: bool = False) -> pd.DataFrame:
    """Half-hourly imbalance settlement price, £/MWh (single price since P305)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / f"disebsp_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
    if key.exists() and not refresh:
        return pd.read_parquet(key)

    # this endpoint is keyed by settlement date, so it is fetched day by day
    frames = []
    for d in pd.date_range(start, end, freq="D"):
        js = _get(f"/balancing/settlement/system-prices/{d:%Y-%m-%d}", {})
        rows = js.get("data", [])
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("no system price data returned")

    df = pd.concat(frames, ignore_index=True)
    df["start_time"] = pd.to_datetime(df.startTime, utc=True)
    df = (df.rename(columns={"settlementDate": "settlement_date",
                             "settlementPeriod": "settlement_period",
                             "systemSellPrice": "system_price",
                             "netImbalanceVolume": "niv"})
            [["start_time", "settlement_date", "settlement_period", "system_price", "niv"]]
            .drop_duplicates(subset=["start_time"])
            .sort_values("start_time")
            .reset_index(drop=True))
    df.to_parquet(key, index=False)
    return df


def load_prices(start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    """Convenience: wholesale + imbalance joined on settlement period."""
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    mid = market_index(a, b, refresh=refresh)
    sysp = system_prices(a, b, refresh=refresh)
    df = mid.merge(sysp[["start_time", "system_price", "niv"]], on="start_time", how="left")
    df["date"] = df.start_time.dt.date
    return df


if __name__ == "__main__":
    df = load_prices("2025-06-01", "2025-06-07")
    print(df.head())
    print(f"\nrows={len(df)}  periods/day={len(df)/7:.1f}")
    print(df[["price", "system_price"]].describe().round(2).to_string())
