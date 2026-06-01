"""
data_provider.py

Fetches and merges all market data needed by SignalGenerator into
a single flat dict for one symbol.

    DataProvider.get(symbol) → dict | None

Returns None when:
  - OB fetch fails
  - Indicator fetch fails AND OB signal is not NEUTRAL
  - Indicator filter blocks the signal
"""

from binance.client          import Client
from orderbook_analyzer      import analyze_orderbook
from market_scanner          import get_indicator_data, check_indicator_filter
from trade_logger            import log_info, log_error, log_ob_scan


class DataProvider:
    def __init__(self, client: Client):
        self.client = client

    def get(self, symbol: str) -> dict | None:
        """
        Return a market_data dict ready for SignalGenerator.generate(), or
        None if the symbol should be skipped this cycle.
        """
        # ── 1. Order-book primary signal ─────────────────────────────────
        try:
            ob = analyze_orderbook(self.client, symbol)
        except Exception as exc:
            log_error(symbol, f"OB fetch failed: {exc}")
            return None

        ob_signal = ob.get("signal", "NEUTRAL")

        if ob_signal == "NEUTRAL":
            log_ob_scan(ob, None, True, "Balanced book")
            return None

        # ── 2. Indicator filter ──────────────────────────────────────────
        indicators    = None
        filter_passed = True
        filter_reason = "Filters not fetched"

        try:
            indicators    = get_indicator_data(self.client, symbol)
            filter_passed, filter_reason = check_indicator_filter(ob_signal, indicators)
        except Exception as exc:
            log_error(symbol, f"Indicator fetch failed: {exc}")
            filter_reason = f"Indicator error (skipping filter): {exc}"

        log_ob_scan(ob, indicators, filter_passed, filter_reason)

        if not filter_passed:
            return None

        # ── 3. ATR guard ─────────────────────────────────────────────────
        atr = indicators["atr"] if indicators else None
        if atr is None:
            log_error(symbol, "No ATR available — skipping")
            return None

        # ── 4. Merge into flat market_data ───────────────────────────────
        ind = indicators or {}
        return {
            "symbol":       symbol,
            "ob_signal":    ob_signal,
            "entry_price":  ob["suggested_entry"],
            "atr":          atr,
            "ob_sl_long":   ob.get("suggested_sl_long"),
            "ob_sl_short":  ob.get("suggested_sl_short"),
            "ob_tp_long":   ob.get("suggested_tp_long"),
            "ob_tp_short":  ob.get("suggested_tp_short"),
            "rsi":          ind.get("rsi"),
            "ema_fast":     ind.get("ema_fast"),
            "ema_slow":     ind.get("ema_slow"),
            "ema_20":       ind.get("ema_20"),
            "price":        ind.get("price"),
            "price_1m_ago": ind.get("price_1m_ago"),
            "high_5":       ind.get("high_5"),
            "low_5":        ind.get("low_5"),
        }
