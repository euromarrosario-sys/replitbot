"""
execution_engine.py

Routes directional signals to market orders.
  1. _get_balance()             — live USDT balance from the client
  2. _calculate_position_size() — simple risk-based quantity estimate
  3. _open_position()           — places the order, returns exchange response
"""

import math
import time
import random

from config       import PAPER_BALANCE_USD, MAX_RISK_PER_TRADE, LEVERAGE
from risk_manager import get_account_balance
from trade_logger import log_info

SAFE_MARGIN             = 0.80   # only use 80% of available balance; 20% buffer
BASE_POSITION_USDT      = 5.0    # minimum notional value per trade (Binance futures)
MIN_TIME_BETWEEN_TRADES = 10.0   # seconds — minimum cooldown between consecutive trades


class ExecutionEngine:
    def __init__(self, binance_client, risk_engine):
        self.client           = binance_client
        self.risk_engine      = risk_engine
        self._positions:      dict  = {}
        self._step_cache:     dict  = {}    # symbol → stepSize float (fetched once)
        self._last_trade_time: float = 0.0  # epoch timestamp of last executed trade

    def get_open_positions(self) -> dict:
        """Return the current open positions snapshot (synced by Bot.run_cycle)."""
        return self._positions

    # ── public ───────────────────────────────────────────────────────────────

    def execute_signal(self, signal: dict, symbol: str, price: float) -> dict | None:
        """
        Size and open a position from a directional signal.

        `signal` fields used:
            action       – "LONG" | "SHORT"
            atr          – float (for SL/TP geometry)
            ob_sl_long/short, ob_tp_long/short  – float | None
        `price`  – current entry price (from ob["suggested_entry"])

        Returns a paper-position dict or None if rejected / order failed.
        """
        elapsed = time.time() - self._last_trade_time
        if elapsed < MIN_TIME_BETWEEN_TRADES:
            print(f"BLOCKED: cooldown ({elapsed:.1f}s < {MIN_TIME_BETWEEN_TRADES}s)")
            return None

        risk_pct    = self.risk_engine.get_risk() / 100   # e.g. 0.3 → 0.003
        available   = self._get_balance()

        risk_amount = available * risk_pct
        qty_risk    = risk_amount / price
        margin_required = (qty_risk * price) / LEVERAGE

        print("DEBUG EXEC CHECK")
        print("risk_amount:", round(risk_amount, 4))
        print("qty_risk:", qty_risk)
        print("price:", price)
        print("available:", available)
        print("margin_required:", round(margin_required, 4))
        print("leverage:", LEVERAGE)
        print("PASS CHECK:", margin_required <= available * SAFE_MARGIN)

        if margin_required > available * SAFE_MARGIN:
            print("BLOCKED: safety buffer")
            return None

        qty = self.calculate_position_size(price, symbol)

        if qty <= 0:
            log_info(
                f"[EXEC] {symbol} skipped — "
                f"qty={qty:.6f}  available={available:.2f}  risk_pct={risk_pct:.4f}"
            )
            return None

        if signal["action"] == "LONG":
            return self._open_position(symbol, "BUY",  qty)

        if signal["action"] == "SHORT":
            return self._open_position(symbol, "SELL", qty)

        return None

    def calculate_position_size(self, balance: float, risk_pct: float, price: float) -> float:
        """Public alias — kept for external callers and tests."""
        return self._calculate_position_size(balance, risk_pct, price)

    def close_all_positions(self, positions: dict) -> None:
        """
        Emergency close: for every open position —
          1. Cancel all open bracket orders (SL / TP / trailing stop)
          2. Send a reducing MARKET order to flatten the position
        Called by Bot.kill_switch(); logs every step.
        """
        if not positions:
            log_info("[EXEC] close_all_positions: no open positions")
            return

        for symbol, pos in list(positions.items()):
            side = pos.get("side", "")

            # 1. Cancel all open orders for the symbol
            try:
                self.client.futures_cancel_all_open_orders(symbol=symbol)
                log_info(f"[EXEC] kill — all open orders cancelled: {symbol}")
            except Exception as exc:
                log_info(f"[EXEC] kill — cancel orders failed: {symbol}  error={exc}")

            # 2. Flatten with a MARKET close order
            close_side = "SELL" if side == "BUY" else "BUY"
            try:
                self.client.futures_create_order(
                    symbol        = symbol,
                    side          = close_side,
                    type          = "MARKET",
                    closePosition = True,
                )
                log_info(f"[EXEC] kill — position closed: {symbol}  side={close_side}")
            except Exception as exc:
                log_info(f"[EXEC] kill — close order failed: {symbol}  error={exc}")

    def get_available_balance(self) -> float:
        """Public alias for _get_balance()."""
        return self._get_balance()

    def floor_to_step_size(self, qty: float, symbol: str) -> float:
        """Floor qty to the exchange LOT_SIZE step and strip float noise."""
        step = self._get_step_size(symbol)
        return round(math.floor(qty / step) * step, 10)

    def calculate_position_size(self, price: float, symbol: str) -> float:
        """
        Compute order quantity using a dynamic growth factor.

        position_usdt = BASE_POSITION_USDT × growth_factor
        qty           = position_usdt / price  → floored to stepSize
        """
        equity        = self.get_available_balance()   # noqa: F841 — reserved for future equity-scaling
        growth_factor = self.risk_engine.get_growth_multiplier()   # starts at 1.0
        position_usdt = BASE_POSITION_USDT * growth_factor
        qty           = position_usdt / price
        return self.floor_to_step_size(qty, symbol)

    def test_order(self) -> dict | None:
        """
        Fire a single hardcoded MARKET BUY for 0.001 BTCUSDT.
        Use to verify API credentials and order routing end-to-end.
        """
        account   = self.client.futures_account()
        available = float(account["availableBalance"])
        positions = self.client.futures_position_information(symbol="BTCUSDT")
        print(">>> TEST ORDER: BTCUSDT BUY 0.001")
        print("available balance:", available)
        print("open positions:", positions)
        try:
            order = self.client.create_order(
                symbol   = "BTCUSDT",
                side     = "BUY",
                type     = "MARKET",
                quantity = 0.001,
            )
            print("TEST ORDER SENT:", order)
            return order
        except Exception as e:
            print("❌ TEST ORDER ERROR:", str(e))
            return None

    # ── private ──────────────────────────────────────────────────────────────

    def _get_step_size(self, symbol: str) -> float:
        """
        Return the LOT_SIZE stepSize for symbol from Binance futures exchange info.
        Result is cached after the first fetch so the API is only hit once per symbol.
        Falls back to 0.001 if the fetch fails or the filter is missing.
        """
        if symbol in self._step_cache:
            return self._step_cache[symbol]
        try:
            info    = self.client.futures_exchange_info()
            symbols = info.get("symbols", [])
            for s in symbols:
                if s["symbol"] == symbol:
                    for f in s.get("filters", []):
                        if f["filterType"] == "LOT_SIZE":
                            step = float(f["stepSize"])
                            self._step_cache[symbol] = step
                            log_info(f"[EXEC] stepSize for {symbol}: {step}")
                            return step
        except Exception as exc:
            log_info(f"[EXEC] stepSize fetch failed ({exc}) — using 0.001")
        self._step_cache[symbol] = 0.001
        return 0.001

    def _get_balance(self) -> float:
        """
        Fetch available USDT margin from the futures account.
        Uses availableBalance (excludes margin locked in open positions).
        Falls back to PAPER_BALANCE_USD in paper-trading mode.
        """
        if PAPER_BALANCE_USD > 0:
            return PAPER_BALANCE_USD
        try:
            account   = self.client.futures_account()
            available = float(account["availableBalance"])
            print("balance:", available)
            return available
        except Exception as exc:
            log_info(f"[EXEC] balance fetch failed ({exc}) — using fallback")
            return get_account_balance(self.client)

    def _calculate_position_size(self, balance: float, risk_pct: float, price: float) -> float:
        """
        Simple quantity estimate:  (balance × risk_pct) / price
        risk_pct is a decimal fraction (e.g. 0.01 = 1%).
        Result is rounded to 3 decimal places (standard futures precision).
        """
        effective_risk = min(risk_pct, MAX_RISK_PER_TRADE)
        if effective_risk < risk_pct:
            log_info(
                f"[EXEC] risk_pct capped: {risk_pct:.4f} → {effective_risk:.4f} "
                f"(MAX_RISK_PER_TRADE={MAX_RISK_PER_TRADE})"
            )
        risk_amount = float(balance) * effective_risk
        qty         = risk_amount / price
        return round(qty, 3)

    def _open_position(self, symbol: str, side: str, quantity: float) -> dict:
        """Open a bracketed position: entry → SL → TP."""
        order       = self._open_market_position(symbol, side, quantity)
        entry_price      = float(order["avgPrice"]) if "avgPrice" in order else None
        risk_multiplier  = self.risk_engine.multiplier
        sl, tp           = self._calculate_sl_tp(entry_price, side, risk_multiplier) if entry_price else (None, None)

        if entry_price:
            self._place_stop_loss(symbol, side, sl)
            self._place_take_profit(symbol, side, tp)
            self._place_trailing_stop(symbol, side)

        return {**order, "entry_price": entry_price, "stop_loss": sl, "take_profit": tp}

    def _open_market_position(self, symbol: str, side: str, quantity: float) -> dict:
        """Place the MARKET entry order and return the raw exchange response."""
        try:
            print(">>> ABOUT TO SEND ORDER")
            order = self.client.create_order(
                symbol   = symbol,
                side     = side,
                type     = "MARKET",
                quantity = quantity,
            )
            print("ORDER SENT:", order)
            self._last_trade_time = time.time()
            delay = random.uniform(2, 5)
            print(f"Sleeping {delay:.1f}s between trades...")
            time.sleep(delay)
            return order
        except Exception as e:
            print("❌ BINANCE ERROR:", str(e))
            raise

    def calculate_callback_rate(self) -> float:
        """
        Adaptive trailing-stop callback rate driven by current risk level.
            rate = 1.0 × (2 − multiplier)
            multiplier=1.00 (normal)  → callback ≈ 1.00%  (wide trail)
            multiplier=0.50           → callback ≈ 1.50%
            multiplier=0.25 (floor)   → callback ≈ 1.75%  (tight trail)
        Higher risk → higher callback → trail triggers sooner.
        """
        risk     = self.risk_engine.get_multiplier()
        base     = 1.0
        callback = base * (2 - risk)
        return round(callback, 2)

    def _place_stop_loss(self, symbol: str, side: str, sl: float) -> None:
        """Place a hard STOP_MARKET at sl — maximum-loss floor."""
        try:
            self.client.create_order(
                symbol        = symbol,
                side          = "SELL" if side == "BUY" else "BUY",
                type          = "STOP_MARKET",
                stopPrice     = sl,
                closePosition = True,
            )
            log_info(f"[EXEC] SL placed: {symbol}  stopPrice={sl}")
        except Exception as exc:
            log_info(f"[EXEC] SL failed: {symbol}  stopPrice={sl}  error={exc}")

    def _place_trailing_stop(self, symbol: str, side: str) -> None:
        """
        Place a TRAILING_STOP_MARKET order via the futures endpoint.
        callbackRate is adaptive (calculate_callback_rate).
        Trails from current price — complements the hard SL floor.
        """
        callback_rate = self.calculate_callback_rate()
        try:
            self.client.futures_create_order(
                symbol        = symbol,
                side          = "SELL" if side == "BUY" else "BUY",
                type          = "TRAILING_STOP_MARKET",
                callbackRate  = callback_rate,
                closePosition = True,
            )
            log_info(f"[EXEC] trailing SL placed: {symbol}  callbackRate={callback_rate}%")
        except Exception as exc:
            log_info(f"[EXEC] trailing SL failed: {symbol}  callbackRate={callback_rate}  error={exc}")

    def _place_take_profit(self, symbol: str, side: str, tp: float) -> None:
        """Place a TAKE_PROFIT_MARKET order that closes the entire position."""
        try:
            self.client.create_order(
                symbol        = symbol,
                side          = "SELL" if side == "BUY" else "BUY",
                type          = "TAKE_PROFIT_MARKET",
                stopPrice     = tp,
                closePosition = True,
            )
            log_info(f"[EXEC] TP order placed: {symbol}  stopPrice={tp}")
        except Exception as exc:
            log_info(f"[EXEC] TP order failed: {symbol}  stopPrice={tp}  error={exc}")

    def _calculate_sl_tp(
        self, price: float, side: str, risk_multiplier: float = 1.0
    ) -> tuple[float, float]:
        """
        Percentage-based SL/TP scaled by risk_multiplier (from RiskEngine).
            base: SL = 1%,  TP = 2%
            multiplier < 1 → tighter bands (reduced-risk mode)
            multiplier = 1 → standard bands
        """
        sl_distance = price * (0.01 * risk_multiplier)
        tp_distance = price * (0.02 * risk_multiplier)

        if side == "BUY":
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance

        return sl, tp
