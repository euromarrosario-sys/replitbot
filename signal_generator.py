"""
signal_generator.py

Scores the market with three independent sub-signals and produces a
final LONG / SHORT / NO_TRADE decision.

    _momentum  — price vs price 1m ago                  (+1 / 0 / −1)
    _trend     — price vs EMA-20                        (+1 / 0 / −1)
    _breakout  — ATR-filtered range breakout            (+1 / 0 / −1)

score      = sum of the three  (range −3 … +3)
confidence = abs(score) / 3    (range  0 … 1.0)

Trade opens when: abs(score) >= 1  AND  confidence >= 0.6
  score ±1 → confidence 0.33  → NO_TRADE
  score ±2 → confidence 0.67  → trade
  score ±3 → confidence 1.00  → trade
"""

from trade_logger import log_info


LONG_THRESHOLD   =  1
SHORT_THRESHOLD  = -1
MIN_CONFIDENCE   =  0.65


class SignalGenerator:
    def __init__(self):
        pass

    def generate(self, market_data: dict) -> dict:
        """
        Score the market and return a signal dict.

        Returned dict always contains:
            action  – "LONG" | "SHORT" | "NO_TRADE"
            score   – int  (sum of three sub-signals)
            + all market_data fields forwarded unchanged
        """
        momentum = self._momentum(market_data)
        trend    = self._trend(market_data)
        breakout = self._breakout(market_data)

        score      = momentum + trend + breakout
        confidence = round(abs(score) / 3, 4)

        if score >= 1 and confidence > MIN_CONFIDENCE:
            action = "LONG"
        elif score <= -1 and confidence > MIN_CONFIDENCE:
            action = "SHORT"
        else:
            action = "NO_TRADE"

        log_info(
            f"[SIG] {action:<8} score={score:+d}  confidence={confidence:.2f}  "
            f"momentum={momentum:+d}  trend={trend:+d}  breakout={breakout:+d}"
        )

        return {**market_data, "action": action, "score": score, "confidence": confidence}

    # ── sub-signals ──────────────────────────────────────────────────────────

    def _momentum(self, market_data: dict) -> int:
        """
        Price-based momentum: current close vs close 1 candle ago.
            price > price_1m_ago → +1  (price rising)
            price < price_1m_ago → -1  (price falling)
        Returns 0 when either field is missing.
        """
        price       = market_data.get("price")
        price_1m    = market_data.get("price_1m_ago")
        if price is None or price_1m is None:
            return 0
        if price > price_1m:
            return 1
        return -1

    def _trend(self, market_data: dict) -> int:
        """
        Price vs EMA-20 trend.
            price > ema_20 → +1  (price above trend)
            price < ema_20 → -1  (price below trend)
        Returns 0 when either field is missing.
        """
        price  = market_data.get("price")
        ema_20 = market_data.get("ema_20")
        if price is None or ema_20 is None:
            return 0
        if price > ema_20:
            return 1
        return -1

    def _breakout(self, market_data: dict) -> int:
        """
        ATR-filtered price breakout beyond the 5-candle range.
            price > high_5 + atr → +1  (bullish breakout)
            price < low_5  − atr → -1  (bearish breakout)
            inside range         →  0
        Returns 0 when any required field is missing.
        """
        price  = market_data.get("price")
        high_5 = market_data.get("high_5")
        low_5  = market_data.get("low_5")
        atr    = market_data.get("atr")
        if any(v is None for v in (price, high_5, low_5, atr)):
            return 0
        if price > high_5 + atr:
            return 1
        if price < low_5 - atr:
            return -1
        return 0
