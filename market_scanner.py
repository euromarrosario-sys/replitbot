"""
market_scanner.py — SECONDARY filter layer.

EMA and RSI are no longer the primary signal source. This module:
  1. Fetches indicator data (ATR, RSI, EMA, volume) for a symbol.
  2. Provides check_indicator_filter() to validate an OB-derived signal.

Neither function generates a trade signal independently.
"""

import numpy as np
import pandas as pd
from binance.client import Client
from config import (
    KLINE_INTERVAL, KLINE_LIMIT,
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    EMA_FAST, EMA_SLOW,
    MIN_VOLUME_MULT, ATR_PERIOD,
    USE_EMA_FILTER, USE_RSI_FILTER,
)


# ── Private helpers ────────────────────────────────────────────────────────

def _to_dataframe(klines: list) -> pd.DataFrame:
    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df.reset_index(drop=True)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ── Public API ─────────────────────────────────────────────────────────────

def get_indicator_data(client: Client, symbol: str) -> dict:
    """
    Fetch klines and return a flat dict of indicator values.
    Used by main.py AFTER the OB signal is obtained.
    """
    klines = client.futures_klines(
        symbol=symbol, interval=KLINE_INTERVAL, limit=KLINE_LIMIT
    )
    df = _to_dataframe(klines)

    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["ema_20"]   = _ema(df["close"], 20)
    df["rsi"]      = _rsi(df["close"])
    df["atr"]      = _atr(df)

    last      = df.iloc[-1]
    avg_vol   = df["volume"].iloc[:-1].mean()
    vol_ratio = last["volume"] / avg_vol if avg_vol > 0 else 0

    prev   = df.iloc[-2]
    high_5 = float(df["high"].iloc[-5:].max())
    low_5  = float(df["low"].iloc[-5:].min())

    return {
        "symbol":        symbol,
        "current_price": float(last["close"]),
        "price":         float(last["close"]),
        "price_1m_ago":  float(prev["close"]),
        "price_change":  round((float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100, 4),
        "atr_pct":       round(float(last["atr"]) / float(last["close"]) * 100, 4),
        "rsi":           round(float(last["rsi"]), 2),
        "ema_fast":      round(float(last["ema_fast"]), 6),
        "ema_slow":      round(float(last["ema_slow"]), 6),
        "ema_20":        round(float(last["ema_20"]), 6),
        "atr":           round(float(last["atr"]), 6),
        "high_5":        round(high_5, 6),
        "low_5":         round(low_5, 6),
        "volume_ratio":  round(vol_ratio, 2),
        "uptrend":       bool(last["ema_fast"] > last["ema_slow"]),
        "downtrend":     bool(last["ema_fast"] < last["ema_slow"]),
    }


def check_indicator_filter(ob_signal: str, indicators: dict) -> tuple[bool, str]:
    """
    Validate an OB-derived signal against EMA trend and RSI extremes.

    Returns
    -------
    (passes: bool, reason: str)
      passes=False → indicator context contradicts OB signal → skip trade.
      passes=True  → no contradictions found, trade can proceed.

    Both filters are individually toggled via USE_EMA_FILTER / USE_RSI_FILTER
    in config.py. Disabling both makes this function always return True.
    """
    if ob_signal not in ("LONG", "SHORT"):
        return True, "No filter needed for NEUTRAL signal"

    blocked = []

    # ── EMA trend alignment ────────────────────────────────────────────────
    if USE_EMA_FILTER:
        if ob_signal == "LONG" and not indicators["uptrend"]:
            blocked.append(
                f"EMA trend DOWN (fast={indicators['ema_fast']:.4f} "
                f"< slow={indicators['ema_slow']:.4f})"
            )
        elif ob_signal == "SHORT" and not indicators["downtrend"]:
            blocked.append(
                f"EMA trend UP (fast={indicators['ema_fast']:.4f} "
                f"> slow={indicators['ema_slow']:.4f})"
            )

    # ── RSI exhaustion check ───────────────────────────────────────────────
    if USE_RSI_FILTER:
        rsi = indicators["rsi"]
        if ob_signal == "LONG" and rsi > RSI_OVERBOUGHT:
            blocked.append(f"RSI overbought ({rsi:.1f} > {RSI_OVERBOUGHT}) for LONG")
        elif ob_signal == "SHORT" and rsi < RSI_OVERSOLD:
            blocked.append(f"RSI oversold ({rsi:.1f} < {RSI_OVERSOLD}) for SHORT")

    if blocked:
        return False, " | ".join(blocked)

    notes = []
    if USE_EMA_FILTER:
        trend = "uptrend" if indicators["uptrend"] else "downtrend"
        notes.append(f"EMA {trend}")
    if USE_RSI_FILTER:
        notes.append(f"RSI={indicators['rsi']:.1f}")
    if not USE_EMA_FILTER and not USE_RSI_FILTER:
        notes.append("All filters disabled")

    return True, ", ".join(notes)
