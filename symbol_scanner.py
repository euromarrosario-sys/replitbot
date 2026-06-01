"""
symbol_scanner.py

Scans a universe of symbols and returns the single best candidate
for the current cycle based on a composite score.

Score components (each contributes ±1):
    momentum  — price vs price_1m_ago
    trend     — price vs ema_20
    breakout  — price vs 5-candle high/low ± ATR

Tie-breaking: higher volume_ratio wins.
"""

from trade_logger import log_info


class SymbolScanner:
    def __init__(self, client):
        self.client         = client
        self.current_symbol: str | None = None

    def scan(self, symbols: list[str]) -> tuple[str | None, int]:
        """
        Iterate over symbols, score each, return (best_symbol, best_score).
        Returns (None, -999) if every fetch fails.
        """
        best_symbol = None
        best_score  = -999

        for symbol in symbols:
            data = self._get_market_data(symbol)
            if data is None:
                continue

            score = self._score(data)
            log_info(
                f"[SCAN] {symbol:<12} score={score:+.4f}  "
                f"price={data['price']:.2f}  vol_ratio={data['volume_ratio']:.2f}"
            )

            if score > best_score or (
                score == best_score and
                data.get("volume_ratio", 0) > self._best_vol_ratio
            ):
                best_score          = score
                best_symbol         = symbol
                self._best_vol_ratio = data.get("volume_ratio", 0)

        self._best_vol_ratio = 0  # reset for next scan
        self.current_symbol  = best_symbol
        return best_symbol, best_score

    # ── private ──────────────────────────────────────────────────────────────

    def _get_market_data(self, symbol: str) -> dict | None:
        """
        Fetch 20 × 1m klines directly and compute scoring fields in-place.
        No external indicator dependencies.
        """
        try:
            klines  = self.client.get_klines(symbol=symbol, interval="1m", limit=20)
            prices  = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            avg_vol = sum(volumes) / len(volumes)

            return {
                "price":        prices[-1],
                "price_change": (prices[-1] - prices[0]) / prices[0],
                "atr_pct":      self._atr(prices) / prices[-1] * 100,
                "volume_ratio": volumes[-1] / avg_vol if avg_vol > 0 else 0,
            }
        except Exception as exc:
            log_info(f"[SCAN] {symbol} fetch failed: {exc}")
            return None

    def _atr(self, prices: list[float]) -> float:
        """Average absolute candle-to-candle range in price units."""
        if len(prices) < 2:
            return 0.0
        ranges = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        return sum(ranges) / len(ranges)

    def _score(self, data: dict) -> float:
        """
        Weighted continuous score for ranking symbols.
            volatility (atr_pct)    × 0.5 — wider moves = more opportunity
            volume     (volume_ratio) × 0.3 — above-average activity
            momentum   (price_change) × 0.2 — recent directional pressure
        Higher score → better candidate for entry this cycle.
        """
        volatility = data.get("atr_pct", 0)
        volume     = data.get("volume_ratio", 0)
        momentum   = data.get("price_change", 0)

        return (volatility * 0.5) + (volume * 0.3) + (momentum * 0.2)

    def _momentum(self, data: dict) -> int:
        price, prev = data.get("price"), data.get("price_1m_ago")
        if price is None or prev is None:
            return 0
        return 1 if price > prev else -1

    def _trend(self, data: dict) -> int:
        price, ema20 = data.get("price"), data.get("ema_20")
        if price is None or ema20 is None:
            return 0
        return 1 if price > ema20 else -1

    def _breakout(self, data: dict) -> int:
        price  = data.get("price")
        high_5 = data.get("high_5")
        low_5  = data.get("low_5")
        atr    = data.get("atr")
        if any(v is None for v in (price, high_5, low_5, atr)):
            return 0
        if price > high_5 + atr:
            return 1
        if price < low_5 - atr:
            return -1
        return 0
